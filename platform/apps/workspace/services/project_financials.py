from datetime import date, timedelta
from decimal import Decimal

from django.core.paginator import Paginator
from django.utils import timezone

from apps.accounting.models import (
    AccountingAccountClassification,
    AccountingGLAllocation,
    AccountingIntegration,
    AccountingSyncRun,
    AccountingSyncState,
)
from apps.accounting.services import (
    AccountClassificationService,
    AggregateProjectFinancialsCommand,
    ProjectFinancialAggregationService,
)
from apps.projects.models import Project


ZERO = Decimal("0")
OPERATIONAL_COST_CATEGORIES = [
    AccountingAccountClassification.Category.MATERIAL_COST,
    AccountingAccountClassification.Category.SUBCONTRACTOR_COST,
    AccountingAccountClassification.Category.LABOR_COST,
    AccountingAccountClassification.Category.EQUIPMENT_COST,
    AccountingAccountClassification.Category.TRANSPORT_COST,
    AccountingAccountClassification.Category.OTHER_DIRECT_COST,
    AccountingAccountClassification.Category.OVERHEAD,
]
OTHER_CATEGORIES = [
    AccountingAccountClassification.Category.FINANCIAL_INCOME,
    AccountingAccountClassification.Category.FINANCIAL_COST,
    AccountingAccountClassification.Category.DEPRECIATION,
    AccountingAccountClassification.Category.TAX,
    AccountingAccountClassification.Category.EXCLUDED,
    AccountingAccountClassification.Category.UNCLASSIFIED,
]


class ProjectFinancialContextBuilder:
    """Build read-only Project Workspace financial context from accounting DTOs."""

    @classmethod
    def build(cls, *, project_id, params):
        project = Project.objects.get(id=project_id)
        period = cls._period(project, params)
        currency = (params.get("currency") or "").strip().upper() or None
        include_overhead = params.get("include_overhead", "1") != "0"
        errors = list(period["errors"])

        result = ProjectFinancialAggregationService().aggregate(
            AggregateProjectFinancialsCommand(
                project=project,
                period_start=period["start"],
                period_end=period["end"],
                currency=currency,
                include_overhead=include_overhead,
                metadata={"source": "workspace_project_financials"},
            )
        )

        return {
            "project": project,
            "financial_result": result,
            "period": period,
            "period_presets": cls._period_presets(),
            "currency_filter": currency or "",
            "include_overhead": include_overhead,
            "form_errors": errors,
            "summary_cards": cls._summary_cards(result),
            "cost_breakdown": cls._category_rows(result, OPERATIONAL_COST_CATEGORIES),
            "other_breakdown": cls._category_rows(result, OTHER_CATEGORIES),
            "months_newest_first": cls._month_rows(result),
            "trend_rows": cls._trend_rows(result),
            "monthly_chart": cls._monthly_chart(result),
            "warnings": cls._warnings(result, include_overhead, currency),
            "unclassified_accounts": cls._unclassified_accounts(project, period["start"], period["end"], currency),
            "sync_context": cls._sync_context(project),
            "result_status": cls._result_status(result.result),
        }

    @classmethod
    def build_allocations(cls, *, project_id, params):
        project = Project.objects.get(id=project_id)
        period = cls._period(project, params)
        currency = (params.get("currency") or "").strip().upper() or None
        category_filter = (params.get("category") or "").strip()
        account_code_filter = (params.get("account_code") or "").strip()
        month_filter = (params.get("month") or "").strip()

        allocations = cls._base_allocations(project, period["start"], period["end"], currency)
        if account_code_filter:
            allocations = allocations.filter(entry__account_code=account_code_filter)
        if month_filter:
            try:
                year, month = [int(part) for part in month_filter.split("-", 1)]
                allocations = allocations.filter(entry__batch__batch_date__year=year, entry__batch__batch_date__month=month)
            except (TypeError, ValueError):
                period["errors"].append("Invalid month filter. Use YYYY-MM.")

        cache = AccountClassificationService.preload(
            project.organization,
            {allocation.integration for allocation in allocations},
        )
        rows = []
        for allocation in allocations[:500]:
            classification = AccountClassificationService.lookup_from_cache(
                cache,
                allocation.integration,
                allocation.entry.account_code,
            )
            category = classification["category"]
            if category_filter and category != category_filter:
                continue
            normalized = (allocation.amount or ZERO) * classification["reporting_sign"]
            rows.append(
                {
                    "allocation": allocation,
                    "category": category,
                    "reporting_sign": classification["reporting_sign"],
                    "normalized_amount": normalized,
                    "source_amount_display": cls._money(allocation.amount or ZERO),
                    "normalized_amount_display": cls._money(normalized),
                }
            )

        paginator = Paginator(rows, 50)
        page = paginator.get_page(params.get("page") or 1)
        return {
            "project": project,
            "period": period,
            "currency_filter": currency or "",
            "category_filter": category_filter,
            "account_code_filter": account_code_filter,
            "month_filter": month_filter,
            "category_choices": AccountingAccountClassification.Category.choices,
            "page_obj": page,
            "allocation_rows": page.object_list,
        }

    @classmethod
    def _period(cls, project, params):
        today = timezone.localdate()
        preset = params.get("period") or "current_year"
        errors = []

        if preset == "current_month":
            start = today.replace(day=1)
            end = today
        elif preset == "previous_month":
            first_this_month = today.replace(day=1)
            end = first_this_month - timedelta(days=1)
            start = end.replace(day=1)
        elif preset == "previous_year":
            start = date(today.year - 1, 1, 1)
            end = date(today.year - 1, 12, 31)
        elif preset == "project_lifetime":
            start = project.start_date or date(today.year, 1, 1)
            end = project.end_date or today
        elif preset == "custom":
            start = cls._parse_date(params.get("start"), "start", errors) or date(today.year, 1, 1)
            end = cls._parse_date(params.get("end"), "end", errors) or today
        else:
            preset = "current_year"
            start = date(today.year, 1, 1)
            end = today

        if project.start_date and start < project.start_date and preset != "previous_year":
            start = project.start_date
        if end < start:
            errors.append("Period end cannot be before period start.")
            start = date(today.year, 1, 1)
            end = today
        return {"preset": preset, "start": start, "end": end, "errors": errors}

    @staticmethod
    def _parse_date(value, label, errors):
        try:
            return date.fromisoformat((value or "").strip())
        except ValueError:
            errors.append(f"Invalid {label} date. Use YYYY-MM-DD.")
            return None

    @staticmethod
    def _period_presets():
        return [
            ("current_month", "Current month"),
            ("previous_month", "Previous month"),
            ("current_year", "Current year"),
            ("previous_year", "Previous year"),
            ("project_lifetime", "Project lifetime"),
            ("custom", "Custom"),
        ]

    @staticmethod
    def _summary_cards(result):
        return [
            {"label": "Revenue", "display_value": ProjectFinancialContextBuilder._money(result.revenue), "status": "info"},
            {"label": "Total cost", "display_value": ProjectFinancialContextBuilder._money(result.total_cost), "status": "neutral"},
            {"label": "Result", "display_value": ProjectFinancialContextBuilder._money(result.result), "status": ProjectFinancialContextBuilder._result_status(result.result)},
            {"label": "Margin", "display_value": ProjectFinancialContextBuilder._percent(result.margin), "status": "info"},
            {"label": "Unclassified", "display_value": ProjectFinancialContextBuilder._money(result.unclassified_amount), "status": "warning" if result.unclassified_amount else "success"},
            {"label": "Allocations", "display_value": str(result.allocation_count), "status": "neutral"},
        ]

    @staticmethod
    def _category_rows(result, categories):
        totals = result.metadata.get("category_totals", {})
        rows = []
        for category in categories:
            total = totals.get(category)
            rows.append(
                {
                    "category": category,
                    "amount": total.amount if total else ZERO,
                    "amount_display": ProjectFinancialContextBuilder._money(total.amount if total else ZERO),
                    "allocation_count": total.allocation_count if total else 0,
                    "entry_count": total.entry_count if total else 0,
                    "source_account_codes": total.source_account_codes if total else [],
                }
            )
        return rows

    @staticmethod
    def _month_rows(result):
        return list(reversed(result.months))

    @staticmethod
    def _trend_rows(result):
        max_value = max(
            [abs(month.revenue) for month in result.months]
            + [abs(month.total_cost) for month in result.months]
            + [abs(month.result) for month in result.months]
            + [Decimal("1")]
        )
        rows = []
        for month in reversed(result.months):
            rows.append(
                {
                    "month": month,
                    "revenue_width": int(abs(month.revenue) / max_value * 100),
                    "cost_width": int(abs(month.total_cost) / max_value * 100),
                    "result_width": int(abs(month.result) / max_value * 100),
                    "result_status": ProjectFinancialContextBuilder._result_status(month.result),
                }
            )
        return rows

    @classmethod
    def _monthly_chart(cls, result):
        months = list(result.months)
        values = []
        for month in months:
            values.extend([month.revenue, month.total_cost, month.result])
        max_absolute = max([abs(value or ZERO) for value in values] + [ZERO])
        has_activity = bool(months) and any((value or ZERO) != ZERO for value in values)
        has_positive = any((value or ZERO) > ZERO for value in values)
        has_negative = any((value or ZERO) < ZERO for value in values)
        positive_area_percent = Decimal("50") if has_positive and has_negative else (Decimal("100") if has_positive else ZERO)
        negative_area_percent = Decimal("50") if has_positive and has_negative else (Decimal("100") if has_negative else ZERO)

        return {
            "max_absolute_value": max_absolute,
            "max_absolute_display": cls._money_with_currency(max_absolute, result.currency),
            "has_activity": has_activity,
            "has_positive": has_positive,
            "has_negative": has_negative,
            "positive_area_percent": int(positive_area_percent),
            "negative_area_percent": int(negative_area_percent),
            "zero_line_percent": int(positive_area_percent),
            "currency": result.currency,
            "months": [
                cls._monthly_chart_month(
                    month,
                    max_absolute=max_absolute,
                    positive_area_percent=positive_area_percent,
                    negative_area_percent=negative_area_percent,
                    currency=result.currency,
                )
                for month in months
            ],
        }

    @classmethod
    def _monthly_chart_month(cls, month, *, max_absolute, positive_area_percent, negative_area_percent, currency):
        return {
            "label": month.period_start.strftime("%Y-%m"),
            "month": month,
            "revenue": cls._chart_bar(
                "Revenue",
                month.revenue,
                max_absolute=max_absolute,
                positive_area_percent=positive_area_percent,
                negative_area_percent=negative_area_percent,
                currency=currency,
                css_class="financial-chart__bar--revenue",
            ),
            "cost": cls._chart_bar(
                "Cost",
                month.total_cost,
                max_absolute=max_absolute,
                positive_area_percent=positive_area_percent,
                negative_area_percent=negative_area_percent,
                currency=currency,
                css_class="financial-chart__bar--cost",
            ),
            "result": cls._chart_bar(
                "Result",
                month.result,
                max_absolute=max_absolute,
                positive_area_percent=positive_area_percent,
                negative_area_percent=negative_area_percent,
                currency=currency,
                css_class=(
                    "financial-chart__bar--result-negative"
                    if month.result < ZERO
                    else "financial-chart__bar--result-positive"
                ),
            ),
        }

    @classmethod
    def _chart_bar(cls, label, value, *, max_absolute, positive_area_percent, negative_area_percent, currency, css_class):
        value = value or ZERO
        is_negative = value < ZERO
        area_percent = negative_area_percent if is_negative else positive_area_percent
        height_percent = ZERO
        if max_absolute:
            height_percent = (abs(value) / max_absolute * area_percent).quantize(Decimal("0.01"))
            if value != ZERO and height_percent < Decimal("2"):
                height_percent = Decimal("2")
        display = cls._money_with_currency(value, currency)
        return {
            "label": label,
            "value": value,
            "display": display,
            "height_percent": height_percent,
            "height_percent_display": f"{height_percent:.2f}",
            "is_negative": is_negative,
            "is_zero": value == ZERO,
            "css_class": css_class,
            "aria_label": f"{label} - {display}",
        }

    @staticmethod
    def _warnings(result, include_overhead, currency):
        warnings = list(result.warnings)
        if not include_overhead:
            warnings.append("overhead_excluded")
        if currency:
            warnings.append(f"currency_filter_active:{currency}")
        if result.data_quality_status == "no_data" and "no_financial_data" not in warnings:
            warnings.append("no_financial_data")
        return warnings

    @classmethod
    def _unclassified_accounts(cls, project, start, end, currency):
        allocations = cls._base_allocations(project, start, end, currency)
        cache = AccountClassificationService.preload(
            project.organization,
            {allocation.integration for allocation in allocations},
        )
        rows = {}
        for allocation in allocations:
            classification = AccountClassificationService.lookup_from_cache(
                cache,
                allocation.integration,
                allocation.entry.account_code,
            )
            if classification["classification"] and classification["category"] != AccountingAccountClassification.Category.UNCLASSIFIED:
                continue
            code = allocation.entry.account_code
            row = rows.setdefault(
                code,
                {
                    "account_code": code,
                    "account_name": allocation.entry.account_name,
                    "allocation_count": 0,
                    "amount": ZERO,
                    "months": set(),
                },
            )
            row["allocation_count"] += 1
            row["amount"] += allocation.amount or ZERO
            row["months"].add(allocation.entry.batch.batch_date.strftime("%Y-%m"))
        for row in rows.values():
            row["months"] = sorted(row["months"])
            row["amount_display"] = cls._money(row["amount"])
        return sorted(rows.values(), key=lambda row: row["account_code"])

    @staticmethod
    def _base_allocations(project, start, end, currency):
        queryset = (
            AccountingGLAllocation.objects.filter(
                organization=project.organization,
                project=project,
                entry__batch__batch_date__gte=start,
                entry__batch__batch_date__lte=end,
                entry__organization=project.organization,
                entry__batch__organization=project.organization,
                integration__organization=project.organization,
            )
            .select_related("entry", "entry__batch", "integration", "project")
            .order_by("-entry__batch__batch_date", "-id")
        )
        if currency:
            queryset = queryset.filter(entry__batch__currency_code=currency)
        return queryset

    @staticmethod
    def _sync_context(project):
        integration = AccountingIntegration.objects.filter(
            organization=project.organization,
            provider=AccountingIntegration.Provider.MERIT,
            is_active=True,
        ).order_by("id").first()
        state = None
        latest_run = None
        if integration:
            state = AccountingSyncState.objects.filter(
                integration=integration,
                source_type=AccountingSyncState.SourceType.GL,
            ).order_by("id").first()
            latest_run = AccountingSyncRun.objects.filter(
                integration=integration,
                source_type=AccountingSyncState.SourceType.GL,
            ).order_by("-started_at", "-id").first()

        status = "unknown"
        if not state:
            status = "never_synced"
        elif state.sync_status == AccountingSyncState.SyncStatus.FAILED:
            status = "failed"
        elif state.sync_status == AccountingSyncState.SyncStatus.RUNNING:
            status = "running"
        elif state.last_successful_sync_at:
            status = "successful"
        return {
            "integration": integration,
            "state": state,
            "latest_run": latest_run,
            "status": status,
            "last_successful_sync_at": state.last_successful_sync_at if state else None,
            "last_error": state.last_error if state else "",
        }

    @staticmethod
    def _result_status(value):
        if value > ZERO:
            return "success"
        if value < ZERO:
            return "danger"
        return "neutral"

    @staticmethod
    def _money(value):
        return f"{Decimal(value or ZERO):.6f}"

    @staticmethod
    def _money_with_currency(value, currency):
        amount = ProjectFinancialContextBuilder._money(value)
        return f"{amount} {currency}" if currency else amount

    @staticmethod
    def _percent(value):
        if value is None:
            return "-"
        return f"{Decimal(value):.2f}%"
