from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING
from urllib.parse import urlencode

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
    BuildManagementFinancialsCommand,
    ProjectManagementFinancialService,
    ProjectFinancialAggregationService,
)
from apps.projects.models import Project
from apps.workspace.services.formatting import format_axis_number, format_money, format_percent


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
        financial_view_mode = "accounting" if params.get("view") == "accounting" else "management"
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
        management_result = ProjectManagementFinancialService.build(
            BuildManagementFinancialsCommand(
                accounting_result=result,
                metadata={"source": "workspace_project_financials"},
            )
        )

        return {
            "project": project,
            "financial_result": result,
            "management_financial_result": management_result,
            "financial_view_mode": financial_view_mode,
            "accounting_view_query": cls._view_query(params, "accounting"),
            "management_view_query": cls._view_query(params, "management"),
            "period": period,
            "period_presets": cls._period_presets(),
            "currency_filter": currency or "",
            "include_overhead": include_overhead,
            "form_errors": errors,
            "summary_cards": cls._summary_cards(result, management_result, financial_view_mode),
            "management_cost_breakdown": cls._management_breakdown_rows(management_result),
            "allocated_management_cost_display": cls._money(management_result.allocated_management_cost),
            "cost_breakdown": cls._category_rows(result, OPERATIONAL_COST_CATEGORIES),
            "other_breakdown": cls._category_rows(result, OTHER_CATEGORIES),
            "months_newest_first": cls._month_rows(result, management_result, financial_view_mode),
            "trend_rows": cls._trend_rows(result),
            "monthly_chart": cls._monthly_chart(result, management_result, financial_view_mode),
            "warnings": cls._warnings(result, management_result, include_overhead, currency),
            "unclassified_accounts": cls._unclassified_accounts(project, period["start"], period["end"], currency),
            "sync_context": cls._sync_context(project),
            "result_status": cls._result_status(
                management_result.management_result if financial_view_mode == "management" else result.result
            ),
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
    def _summary_cards(result, management_result, financial_view_mode):
        if financial_view_mode == "accounting":
            return [
                {"label": "Revenue", "display_value": ProjectFinancialContextBuilder._money(result.revenue), "status": "info"},
                {"label": "Direct Cost", "display_value": ProjectFinancialContextBuilder._money(result.total_cost), "status": "neutral"},
                {"label": "Accounting Result", "display_value": ProjectFinancialContextBuilder._money(result.result), "status": ProjectFinancialContextBuilder._result_status(result.result)},
                {"label": "Accounting Margin", "display_value": ProjectFinancialContextBuilder._percent(result.margin), "status": "info"},
                {"label": "Unclassified", "display_value": ProjectFinancialContextBuilder._money(result.unclassified_amount), "status": "warning" if result.unclassified_amount else "success"},
                {"label": "GL Allocations", "display_value": str(result.allocation_count), "status": "neutral"},
            ]
        return [
            {"label": "Revenue", "display_value": ProjectFinancialContextBuilder._money(management_result.direct_revenue), "status": "info"},
            {"label": "Direct Cost", "display_value": ProjectFinancialContextBuilder._money(management_result.direct_cost), "status": "neutral"},
            {"label": "Allocated Cost", "display_value": ProjectFinancialContextBuilder._money(management_result.allocated_management_cost), "status": "warning" if management_result.allocated_management_cost else "neutral"},
            {"label": "Management Total Cost", "display_value": ProjectFinancialContextBuilder._money(management_result.management_total_cost), "status": "neutral"},
            {"label": "Accounting Result", "display_value": ProjectFinancialContextBuilder._money(management_result.accounting_result), "status": ProjectFinancialContextBuilder._result_status(management_result.accounting_result)},
            {"label": "Management Result", "display_value": ProjectFinancialContextBuilder._money(management_result.management_result), "status": ProjectFinancialContextBuilder._result_status(management_result.management_result)},
            {"label": "Accounting Margin", "display_value": ProjectFinancialContextBuilder._percent(management_result.accounting_margin), "status": "info"},
            {"label": "Management Margin", "display_value": ProjectFinancialContextBuilder._percent(management_result.management_margin), "status": "info"},
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
    def _month_rows(result, management_result, financial_view_mode):
        management_months = {(month.year, month.month): month for month in management_result.months}
        rows = []
        for month in reversed(result.months):
            management_month = management_months[(month.year, month.month)]
            other_cost = month.equipment_cost + month.transport_cost + month.other_direct_cost
            visible_cost = management_month.management_total_cost if financial_view_mode == "management" else month.total_cost
            visible_result = management_month.management_result if financial_view_mode == "management" else month.result
            visible_margin = management_month.management_margin if financial_view_mode == "management" else month.margin
            rows.append(
                {
                    "month": month,
                    "management_month": management_month,
                    "period_start": month.period_start,
                    "revenue_display": ProjectFinancialContextBuilder._money(month.revenue),
                    "material_cost_display": ProjectFinancialContextBuilder._money(month.material_cost),
                    "subcontractor_cost_display": ProjectFinancialContextBuilder._money(month.subcontractor_cost),
                    "labor_cost_display": ProjectFinancialContextBuilder._money(month.labor_cost),
                    "other_cost_display": ProjectFinancialContextBuilder._money(other_cost),
                    "overhead_display": ProjectFinancialContextBuilder._money(month.overhead),
                    "total_cost_display": ProjectFinancialContextBuilder._money(month.total_cost),
                    "allocated_management_cost_display": ProjectFinancialContextBuilder._money(management_month.allocated_management_cost),
                    "management_total_cost_display": ProjectFinancialContextBuilder._money(management_month.management_total_cost),
                    "result_display": ProjectFinancialContextBuilder._money(month.result),
                    "management_result_display": ProjectFinancialContextBuilder._money(management_month.management_result),
                    "margin_display": ProjectFinancialContextBuilder._percent(month.margin),
                    "management_margin_display": ProjectFinancialContextBuilder._percent(management_month.management_margin),
                    "visible_cost_display": ProjectFinancialContextBuilder._money(visible_cost),
                    "visible_result_display": ProjectFinancialContextBuilder._money(visible_result),
                    "visible_margin_display": ProjectFinancialContextBuilder._percent(visible_margin),
                    "unclassified_amount_display": ProjectFinancialContextBuilder._money(month.unclassified_amount),
                    "has_unclassified": bool(month.unclassified_amount),
                    "result_status": ProjectFinancialContextBuilder._result_status(visible_result),
                }
            )
        return rows

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
    def _monthly_chart(cls, result, management_result, financial_view_mode):
        months = list(result.months)
        management_months = {(month.year, month.month): month for month in management_result.months}
        values = []
        for month in months:
            if financial_view_mode == "management":
                management_month = management_months[(month.year, month.month)]
                values.extend([management_month.direct_revenue, management_month.management_total_cost, management_month.management_result])
            else:
                values.extend([month.revenue, month.total_cost, month.result])
        max_absolute = max([abs(value or ZERO) for value in values] + [ZERO])
        has_activity = bool(months) and any((value or ZERO) != ZERO for value in values)
        has_positive = any((value or ZERO) > ZERO for value in values)
        has_negative = any((value or ZERO) < ZERO for value in values)
        scale = cls._chart_scale(values)
        axis_min = scale["axis_min"]
        axis_max = scale["axis_max"]
        axis_range = axis_max - axis_min
        zero_line_percent = ZERO
        if axis_range:
            zero_line_percent = ((axis_max - ZERO) / axis_range * Decimal("100")).quantize(Decimal("0.01"))
        positive_area_percent = zero_line_percent
        negative_area_percent = Decimal("100") - zero_line_percent

        return {
            "max_absolute_value": max_absolute,
            "max_absolute_display": cls._money_with_currency(max_absolute, result.currency),
            "axis_min": axis_min,
            "axis_max": axis_max,
            "axis_interval": scale["interval"],
            "ticks": scale["ticks"],
            "has_activity": has_activity,
            "has_positive": has_positive,
            "has_negative": has_negative,
            "positive_area_percent": f"{positive_area_percent:.2f}",
            "negative_area_percent": f"{negative_area_percent:.2f}",
            "zero_line_percent": f"{zero_line_percent:.2f}",
            "currency": result.currency,
            "view_mode": financial_view_mode,
            "cost_label": "Management total cost" if financial_view_mode == "management" else "Cost",
            "result_label": "Management result" if financial_view_mode == "management" else "Result",
            "months": [
                cls._monthly_chart_month(
                    month,
                    management_month=management_months[(month.year, month.month)],
                    financial_view_mode=financial_view_mode,
                    axis_min=axis_min,
                    axis_max=axis_max,
                    positive_area_percent=positive_area_percent,
                    negative_area_percent=negative_area_percent,
                    currency=result.currency,
                )
                for month in months
            ],
        }

    @classmethod
    def _monthly_chart_month(cls, month, *, management_month, financial_view_mode, axis_min, axis_max, positive_area_percent, negative_area_percent, currency):
        revenue = month.revenue
        cost = month.total_cost
        result = month.result
        cost_label = "Cost"
        result_label = "Result"
        if financial_view_mode == "management":
            revenue = management_month.direct_revenue
            cost = management_month.management_total_cost
            result = management_month.management_result
            cost_label = "Management total cost"
            result_label = "Management result"
        return {
            "label": month.period_start.strftime("%Y-%m"),
            "month": month,
            "revenue": cls._chart_bar(
                "Revenue",
                revenue,
                axis_min=axis_min,
                axis_max=axis_max,
                positive_area_percent=positive_area_percent,
                negative_area_percent=negative_area_percent,
                currency=currency,
                css_class="financial-chart__bar--revenue",
            ),
            "cost": cls._chart_bar(
                cost_label,
                cost,
                axis_min=axis_min,
                axis_max=axis_max,
                positive_area_percent=positive_area_percent,
                negative_area_percent=negative_area_percent,
                currency=currency,
                css_class="financial-chart__bar--cost",
            ),
            "result": cls._chart_bar(
                result_label,
                result,
                axis_min=axis_min,
                axis_max=axis_max,
                positive_area_percent=positive_area_percent,
                negative_area_percent=negative_area_percent,
                currency=currency,
                css_class=(
                    "financial-chart__bar--result-negative"
                    if result < ZERO
                    else "financial-chart__bar--result-positive"
                ),
            ),
        }

    @classmethod
    def _chart_bar(cls, label, value, *, axis_min, axis_max, positive_area_percent, negative_area_percent, currency, css_class):
        value = value or ZERO
        is_negative = value < ZERO
        area_limit = abs(axis_min) if is_negative else axis_max
        height_percent = ZERO
        if area_limit:
            height_percent = (abs(value) / area_limit * Decimal("100")).quantize(Decimal("0.01"))
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

    @classmethod
    def _chart_scale(cls, values):
        numeric_values = [Decimal(value or ZERO) for value in values]
        max_positive = max([value for value in numeric_values if value > ZERO] + [ZERO])
        min_negative = min([value for value in numeric_values if value < ZERO] + [ZERO])
        max_absolute = max(abs(max_positive), abs(min_negative))
        if max_absolute == ZERO:
            return {"axis_min": ZERO, "axis_max": ZERO, "interval": ZERO, "ticks": []}

        scale_basis = (max_positive - min_negative) if max_positive and min_negative else max_absolute
        interval = cls._nice_interval(scale_basis)
        axis_max = cls._round_up_to_interval(max_positive, interval) if max_positive else ZERO
        axis_min = -cls._round_up_to_interval(abs(min_negative), interval) if min_negative else ZERO
        if axis_max == ZERO and axis_min == ZERO:
            axis_max = interval

        ticks = []
        value = axis_min
        axis_range = axis_max - axis_min
        guard = 0
        while value <= axis_max and guard < 20:
            position = ((axis_max - value) / axis_range * Decimal("100")).quantize(Decimal("0.01")) if axis_range else ZERO
            ticks.append(
                {
                    "value": value,
                    "label": format_axis_number(value),
                    "position_percent": f"{position:.2f}",
                    "is_zero": value == ZERO,
                }
            )
            value += interval
            guard += 1
        if not any(tick["is_zero"] for tick in ticks):
            position = ((axis_max - ZERO) / axis_range * Decimal("100")).quantize(Decimal("0.01")) if axis_range else ZERO
            ticks.append(
                {
                    "value": ZERO,
                    "label": "0",
                    "position_percent": f"{position:.2f}",
                    "is_zero": True,
                }
            )
            ticks = sorted(ticks, key=lambda tick: tick["value"], reverse=True)
        return {"axis_min": axis_min, "axis_max": axis_max, "interval": interval, "ticks": ticks}

    @staticmethod
    def _nice_interval(max_absolute):
        target = Decimal(max_absolute) / Decimal("5")
        exponent = target.adjusted()
        base = Decimal(10) ** exponent
        normalized = target / base
        if normalized <= Decimal("1"):
            factor = Decimal("1")
        elif normalized <= Decimal("2"):
            factor = Decimal("2")
        elif normalized <= Decimal("2.5"):
            factor = Decimal("2.5")
        elif normalized <= Decimal("5"):
            factor = Decimal("5")
        else:
            factor = Decimal("10")
        return factor * base

    @staticmethod
    def _round_up_to_interval(value, interval):
        if not value:
            return ZERO
        return (Decimal(value) / interval).to_integral_value(rounding=ROUND_CEILING) * interval

    @staticmethod
    def _warnings(result, management_result, include_overhead, currency):
        warnings = list(result.warnings)
        warnings.extend(management_result.warnings)
        if not include_overhead:
            warnings.append("overhead_excluded")
        if currency:
            warnings.append(f"currency_filter_active:{currency}")
        if result.data_quality_status == "no_data" and "no_financial_data" not in warnings:
            warnings.append("no_financial_data")
        return warnings

    @staticmethod
    def _management_breakdown_rows(management_result):
        rows = []
        for item in management_result.allocation_breakdown:
            rows.append(
                {
                    "pool": item.pool,
                    "version": item.version,
                    "period": item.period,
                    "amount": item.amount,
                    "amount_display": ProjectFinancialContextBuilder._money(item.amount),
                    "percentage_display": ProjectFinancialContextBuilder._percent(item.percentage_of_total),
                    "source_version": item.source_version,
                    "approved_at": item.approved_at,
                }
            )
        return rows

    @staticmethod
    def _view_query(params, view_mode):
        query = {
            "period": params.get("period") or "current_year",
            "start": params.get("start") or "",
            "end": params.get("end") or "",
            "currency": params.get("currency") or "",
            "include_overhead": params.get("include_overhead", "1"),
            "view": view_mode,
        }
        return urlencode({key: value for key, value in query.items() if value not in {None, ""}})

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
        return format_money(value)

    @staticmethod
    def _money_with_currency(value, currency):
        return format_money(value, currency)

    @staticmethod
    def _percent(value):
        return format_percent(value)
