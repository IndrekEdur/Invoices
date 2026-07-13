from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import AccountingGLAllocation, AccountingIntegration, AccountingSyncRun, AccountingSyncState
from apps.accounting.services import AggregateProjectFinancialsCommand, ProjectFinancialAggregationService
from apps.core.models import Organization
from apps.projects.models import Project
from apps.workspace.services.formatting import format_money, format_percent


ZERO = Decimal("0")
VALID_DATA_QUALITY = {"all", "complete", "unclassified", "mixed_currency", "partial", "no_data"}
VALID_RESULT_STATUS = {"all", "positive", "negative", "zero", "costs_without_revenue", "no_data"}
VALID_STATUS = {"all", Project.Status.ACTIVE, Project.Status.COMPLETED, Project.Status.ARCHIVED}
VALID_SORTS = {
    "project_code",
    "project_name",
    "status",
    "revenue",
    "total_cost",
    "result",
    "margin",
    "unclassified_amount",
    "allocation_count",
    "data_quality",
}


@dataclass(frozen=True)
class ProjectFinancialDashboardRow:
    project: object
    project_id: int
    project_code: str
    project_name: str
    project_status: str
    currency: str
    revenue: Decimal
    total_cost: Decimal
    result: Decimal
    margin: Decimal | None
    unclassified_amount: Decimal
    allocation_count: int
    data_quality_status: str
    result_status: str
    financials_url: str
    allocations_url: str
    project_url: str
    warnings: list[str]
    metadata: dict = field(default_factory=dict)

    @property
    def has_activity(self):
        return any(
            [
                self.revenue != ZERO,
                self.total_cost != ZERO,
                self.result != ZERO,
                self.unclassified_amount != ZERO,
                self.allocation_count,
            ]
        )

    @property
    def revenue_display(self):
        return format_money(self.revenue, self.currency)

    @property
    def total_cost_display(self):
        return format_money(self.total_cost, self.currency)

    @property
    def result_display(self):
        return format_money(self.result, self.currency)

    @property
    def margin_display(self):
        return format_percent(self.margin)

    @property
    def unclassified_amount_display(self):
        return format_money(self.unclassified_amount, self.currency)


class OrganizationFinancialDashboardContextBuilder:
    """Build read-only organization financial dashboard context from local GL cache."""

    @classmethod
    def build(cls, params):
        organization = Organization.objects.order_by("id").first()
        filters = cls._filters(params)
        rows = []
        if organization:
            rows = cls._rows(organization, filters)
            rows = cls._apply_filters(rows, filters)
            rows = cls._sort_rows(rows, filters["sort"], filters["direction"])

        paginator = Paginator(rows, 25)
        page = paginator.get_page(params.get("page") or 1)
        query_without_page = cls._query_string(filters, include_page=False)

        return {
            "organization": organization,
            "filters": filters,
            "form_errors": filters["errors"],
            "rows": page.object_list,
            "page_obj": page,
            "summary_cards": cls._summary_cards(rows, filters),
            "totals_by_currency": cls._totals_by_currency(rows),
            "currency_warning": cls._currency_warning(rows, filters),
            "chart_rows": cls._chart_rows(rows),
            "sync_context": cls._sync_context(organization, filters),
            "sort_links": cls._sort_links(filters),
            "query_without_page": query_without_page,
            "previous_month_query": cls._month_query(filters, -1),
            "next_month_query": cls._month_query(filters, 1),
            "current_month_query": cls._current_month_query(filters),
            "show_no_data": filters["show_no_data"],
        }

    @classmethod
    def _filters(cls, params):
        today = timezone.localdate()
        errors = []
        month_value = (params.get("month") or today.strftime("%Y-%m")).strip()
        try:
            year, month = [int(part) for part in month_value.split("-", 1)]
            month_start = date(year, month, 1)
        except (TypeError, ValueError):
            errors.append("Invalid month. Use YYYY-MM.")
            month_start = date(today.year, today.month, 1)
            month_value = month_start.strftime("%Y-%m")
        month_end = cls._month_end(month_start)

        status = params.get("status") or "all"
        if status not in VALID_STATUS:
            status = "all"
        data_quality = params.get("data_quality") or "all"
        if data_quality not in VALID_DATA_QUALITY:
            data_quality = "all"
        result_status = params.get("result_status") or "all"
        if result_status not in VALID_RESULT_STATUS:
            result_status = "all"
        sort = params.get("sort") or "revenue"
        if sort not in VALID_SORTS:
            sort = "revenue"
        direction = params.get("direction") or "desc"
        if direction not in {"asc", "desc"}:
            direction = "desc"

        return {
            "month": month_value,
            "period_start": month_start,
            "period_end": month_end,
            "currency": (params.get("currency") or "").strip().upper(),
            "include_overhead": params.get("include_overhead", "1") != "0",
            "status": status,
            "data_quality": data_quality,
            "result_status": result_status,
            "search": (params.get("search") or "").strip(),
            "sort": sort,
            "direction": direction,
            "show_no_data": params.get("show_no_data") == "1",
            "errors": errors,
        }

    @staticmethod
    def _month_end(month_start):
        if month_start.month == 12:
            return date(month_start.year, 12, 31)
        return date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)

    @classmethod
    def _rows(cls, organization, filters):
        projects = cls._candidate_projects(organization, filters)
        service = ProjectFinancialAggregationService()
        rows = []
        for project in projects:
            result = service.aggregate(
                AggregateProjectFinancialsCommand(
                    project=project,
                    period_start=filters["period_start"],
                    period_end=filters["period_end"],
                    currency=filters["currency"] or None,
                    include_overhead=filters["include_overhead"],
                    metadata={"source": "workspace_organization_financial_dashboard"},
                )
            )
            row = cls._row_from_result(result, filters)
            if row.has_activity or filters["show_no_data"]:
                rows.append(row)
        return rows

    @staticmethod
    def _candidate_projects(organization, filters):
        projects = Project.objects.filter(organization=organization)
        if not filters["show_no_data"]:
            queryset = AccountingGLAllocation.objects.filter(
                organization=organization,
                project__isnull=False,
                entry__batch__batch_date__gte=filters["period_start"],
                entry__batch__batch_date__lte=filters["period_end"],
                project__organization=organization,
            )
            if filters["currency"]:
                queryset = queryset.filter(entry__batch__currency_code=filters["currency"])
            project_ids = queryset.values_list("project_id", flat=True).distinct()
            projects = projects.filter(id__in=project_ids)
        projects = projects.order_by("code", "name", "id")
        if filters["status"] != "all":
            projects = projects.filter(status=filters["status"])
        if filters["search"]:
            needle = filters["search"]
            query = Q(code__icontains=needle) | Q(name__icontains=needle)
            if needle.isdigit():
                query |= Q(id=int(needle))
            projects = projects.filter(query)
        return projects

    @classmethod
    def _row_from_result(cls, result, filters):
        project = result.project
        query = {
            "period": "custom",
            "start": filters["period_start"].isoformat(),
            "end": filters["period_end"].isoformat(),
            "currency": filters["currency"],
            "include_overhead": "1" if filters["include_overhead"] else "0",
        }
        query_string = urlencode(query)
        return ProjectFinancialDashboardRow(
            project=project,
            project_id=project.id,
            project_code=project.code,
            project_name=project.name,
            project_status=project.status,
            currency=result.currency,
            revenue=result.revenue,
            total_cost=result.total_cost,
            result=result.result,
            margin=result.margin,
            unclassified_amount=result.unclassified_amount,
            allocation_count=result.allocation_count,
            data_quality_status=result.data_quality_status,
            result_status=cls._result_status(result),
            financials_url=f"{reverse('workspace:project_financials', args=[project.id])}?{query_string}",
            allocations_url=f"{reverse('workspace:project_financial_allocations', args=[project.id])}?{query_string}",
            project_url=reverse("workspace:project_detail", args=[project.id]),
            warnings=list(result.warnings),
            metadata={"source_batch_count": result.source_batch_count, "source_entry_count": result.source_entry_count},
        )

    @staticmethod
    def _result_status(result):
        if result.allocation_count == 0 and all(
            value == ZERO
            for value in [result.revenue, result.total_cost, result.result, result.unclassified_amount]
        ):
            return "no_data"
        if result.revenue == ZERO and result.total_cost != ZERO:
            return "costs_without_revenue"
        if result.result > ZERO:
            return "positive"
        if result.result < ZERO:
            return "negative"
        return "zero"

    @staticmethod
    def _apply_filters(rows, filters):
        filtered = rows
        if filters["data_quality"] != "all":
            filtered = [row for row in filtered if row.data_quality_status == filters["data_quality"]]
        if filters["result_status"] != "all":
            filtered = [row for row in filtered if row.result_status == filters["result_status"]]
        return filtered

    @staticmethod
    def _sort_rows(rows, sort, direction):
        def key(row):
            value = {
                "project_code": row.project_code,
                "project_name": row.project_name.lower(),
                "status": row.project_status,
                "revenue": row.revenue,
                "total_cost": row.total_cost,
                "result": row.result,
                "margin": row.margin if row.margin is not None else Decimal("-999999999"),
                "unclassified_amount": row.unclassified_amount,
                "allocation_count": row.allocation_count,
                "data_quality": row.data_quality_status,
            }[sort]
            return (value, row.project_code, row.project_name.lower(), row.project_id)

        return sorted(rows, key=key, reverse=direction == "desc")

    @classmethod
    def _summary_cards(cls, rows, filters):
        currencies = cls._distinct_currencies(rows)
        trusted_totals = bool(filters["currency"]) or len(currencies) <= 1
        totals = cls._totals(rows) if trusted_totals else None
        total_revenue = totals["revenue"] if totals else ZERO
        total_result = totals["result"] if totals else ZERO
        overall_margin = None
        if trusted_totals and total_revenue:
            overall_margin = total_result / total_revenue * Decimal("100")
        return [
            {"label": "Projects with activity", "display_value": str(len(rows)), "status": "info"},
            {"label": "Total revenue", "display_value": cls._money_or_mixed(totals, "revenue", rows), "status": "info"},
            {"label": "Total cost", "display_value": cls._money_or_mixed(totals, "total_cost", rows), "status": "neutral"},
            {"label": "Total result", "display_value": cls._money_or_mixed(totals, "result", rows), "status": cls._amount_status(total_result) if trusted_totals else "warning"},
            {"label": "Overall margin", "display_value": format_percent(overall_margin), "status": "info"},
            {"label": "Profitable projects", "display_value": str(sum(1 for row in rows if row.result_status == "positive")), "status": "success"},
            {"label": "Negative projects", "display_value": str(sum(1 for row in rows if row.result_status == "negative")), "status": "danger"},
            {"label": "Costs no revenue", "display_value": str(sum(1 for row in rows if row.result_status == "costs_without_revenue")), "status": "warning"},
            {"label": "Unclassified", "display_value": cls._money_or_mixed(totals, "unclassified_amount", rows), "status": "warning"},
        ]

    @staticmethod
    def _totals(rows):
        return {
            "revenue": sum((row.revenue for row in rows), ZERO),
            "total_cost": sum((row.total_cost for row in rows), ZERO),
            "result": sum((row.result for row in rows), ZERO),
            "unclassified_amount": sum((row.unclassified_amount for row in rows), ZERO),
        }

    @classmethod
    def _totals_by_currency(cls, rows):
        totals = {}
        for row in rows:
            currency = row.currency or "unknown"
            bucket = totals.setdefault(currency, {"currency": currency, "revenue": ZERO, "total_cost": ZERO, "result": ZERO, "unclassified_amount": ZERO, "project_count": 0})
            bucket["revenue"] += row.revenue
            bucket["total_cost"] += row.total_cost
            bucket["result"] += row.result
            bucket["unclassified_amount"] += row.unclassified_amount
            bucket["project_count"] += 1
        return [
            {
                **bucket,
                "revenue_display": format_money(bucket["revenue"], currency),
                "total_cost_display": format_money(bucket["total_cost"], currency),
                "result_display": format_money(bucket["result"], currency),
                "unclassified_display": format_money(bucket["unclassified_amount"], currency),
            }
            for currency, bucket in sorted(totals.items())
        ]

    @staticmethod
    def _distinct_currencies(rows):
        return sorted({row.currency for row in rows if row.currency})

    @classmethod
    def _money_or_mixed(cls, totals, key, rows):
        if totals is None:
            return "Select currency"
        currency = cls._distinct_currencies(rows)[0] if cls._distinct_currencies(rows) else ""
        return format_money(totals[key], currency)

    @staticmethod
    def _amount_status(value):
        if value > ZERO:
            return "success"
        if value < ZERO:
            return "danger"
        return "neutral"

    @classmethod
    def _currency_warning(cls, rows, filters):
        currencies = cls._distinct_currencies(rows)
        if not filters["currency"] and len(currencies) > 1:
            return f"Multiple currencies found ({', '.join(currencies)}). Select a currency to view trusted organization totals."
        return ""

    @classmethod
    def _chart_rows(cls, rows):
        top_rows = rows[:10]
        positive_values = [value for row in top_rows for value in [row.revenue, row.total_cost, row.result]]
        max_positive = max(positive_values + [ZERO])
        min_negative = min([row.result for row in top_rows] + [ZERO])
        axis_range = max_positive - min_negative
        if axis_range == ZERO:
            return []
        zero_line = (abs(min_negative) / axis_range * Decimal("100")).quantize(Decimal("0.01"))
        has_negative = min_negative < ZERO
        axis = {
            "min_negative": min_negative,
            "max_positive": max_positive,
            "zero_line_percent": f"{zero_line:.2f}",
            "negative_label": format_money(min_negative, top_rows[0].currency) if has_negative else "",
            "positive_label": format_money(max_positive, top_rows[0].currency),
            "zero_label": format_money(ZERO, top_rows[0].currency),
        }
        chart_rows = []
        for row in top_rows:
            chart_rows.append(
                {
                    "row": row,
                    "project_label": f"{row.project_code} {row.project_name}",
                    "margin_display": row.margin_display,
                    "max_value_display": format_money(max_positive, row.currency),
                    "has_negative": has_negative,
                    "axis": axis,
                    "metrics": [
                        cls._chart_metric(
                            row=row,
                            label="Revenue",
                            value=row.revenue,
                            min_negative=min_negative,
                            axis_range=axis_range,
                            css_class="bg-blue-500",
                        ),
                        cls._chart_metric(
                            row=row,
                            label="Cost",
                            value=row.total_cost,
                            min_negative=min_negative,
                            axis_range=axis_range,
                            css_class="bg-slate-500",
                        ),
                        cls._chart_metric(
                            row=row,
                            label="Result",
                            value=row.result,
                            min_negative=min_negative,
                            axis_range=axis_range,
                            css_class="bg-green-500" if row.result >= ZERO else "bg-red-500",
                        ),
                    ],
                    "aria_label": (
                        f"{row.project_code} {row.project_name}: revenue {row.revenue_display}, "
                        f"cost {row.total_cost_display}, result {row.result_display}, margin {row.margin_display}"
                    ),
                }
            )
        return chart_rows

    @staticmethod
    def _chart_metric(row, label, value, min_negative, axis_range, css_class):
        width = Decimal("0")
        if axis_range:
            width = (abs(value) / axis_range * Decimal("100")).quantize(Decimal("0.01"))
        zero_line = (abs(min_negative) / axis_range * Decimal("100")).quantize(Decimal("0.01")) if axis_range else ZERO
        if value < ZERO:
            left = zero_line - width
        else:
            left = zero_line
        display_value = format_money(value, row.currency)
        return {
            "label": label,
            "value": value,
            "display_value": display_value,
            "width_percent": f"{width:.2f}",
            "left_percent": f"{left:.2f}",
            "is_negative": value < ZERO,
            "css_class": css_class,
            "aria_label": f"{row.project_code} {row.project_name} {label}: {display_value}",
        }

    @staticmethod
    def _sync_context(organization, filters):
        integration = None
        state = None
        latest_run = None
        selected_month_run = None
        active_integrations = AccountingIntegration.objects.none()
        if organization:
            active_integrations = AccountingIntegration.objects.filter(
                organization=organization,
                provider=AccountingIntegration.Provider.MERIT,
                is_active=True,
            ).order_by("display_name", "id")
            integration = active_integrations.first()
        if integration:
            state = AccountingSyncState.objects.filter(
                integration=integration,
                source_type=AccountingSyncState.SourceType.GL,
            ).order_by("id").first()
            latest_run = AccountingSyncRun.objects.filter(
                integration=integration,
                source_type=AccountingSyncState.SourceType.GL,
            ).order_by("-started_at", "-id").first()
            selected_month_run = AccountingSyncRun.objects.filter(
                organization=organization,
                integration=integration,
                source_type=AccountingSyncState.SourceType.GL,
                requested_period_start=filters["period_start"],
                requested_period_end=filters["period_end"],
            ).order_by("-started_at", "-id").first()
        is_running = bool(state and state.sync_status == AccountingSyncState.SyncStatus.RUNNING)
        return {
            "integration": integration,
            "active_integrations": active_integrations,
            "integration_count": active_integrations.count(),
            "state": state,
            "latest_run": latest_run,
            "selected_month_run": selected_month_run,
            "selected_month": filters["month"],
            "status": state.sync_status if state else "never_synced",
            "is_running": is_running,
            "can_sync": bool(integration) and not is_running,
            "last_successful_sync_at": state.last_successful_sync_at if state else None,
            "last_error": state.last_error if state else "",
        }

    @classmethod
    def _sort_links(cls, filters):
        return {sort: cls._sort_query(filters, sort) for sort in VALID_SORTS}

    @classmethod
    def _sort_query(cls, filters, sort):
        direction = "asc" if filters["sort"] == sort and filters["direction"] == "desc" else "desc"
        return cls._query_string({**filters, "sort": sort, "direction": direction}, include_page=False)

    @staticmethod
    def _query_string(filters, include_page=False):
        query = {
            "month": filters["month"],
            "currency": filters["currency"],
            "include_overhead": "1" if filters["include_overhead"] else "0",
            "status": filters["status"],
            "data_quality": filters["data_quality"],
            "result_status": filters["result_status"],
            "search": filters["search"],
            "sort": filters["sort"],
            "direction": filters["direction"],
        }
        if filters["show_no_data"]:
            query["show_no_data"] = "1"
        if include_page and filters.get("page"):
            query["page"] = filters["page"]
        return urlencode({key: value for key, value in query.items() if value not in {None, ""}})

    @classmethod
    def _month_query(cls, filters, offset):
        current = filters["period_start"]
        month = current.month + offset
        year = current.year
        if month < 1:
            month = 12
            year -= 1
        if month > 12:
            month = 1
            year += 1
        return cls._query_string({**filters, "month": date(year, month, 1).strftime("%Y-%m")})

    @classmethod
    def _current_month_query(cls, filters):
        today = timezone.localdate()
        return cls._query_string({**filters, "month": today.strftime("%Y-%m")})
