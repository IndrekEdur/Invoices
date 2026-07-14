import calendar
from dataclasses import dataclass

from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import (
    FinancialAlert,
    FinancialAlertBasis,
    FinancialAlertEvaluationRun,
    FinancialAlertRule,
    FinancialAlertSeverity,
    FinancialAlertStatus,
    FinancialAlertType,
)
from apps.projects.models import Project

from .formatting import format_money


ACTIVE_STATUSES = [FinancialAlertStatus.OPEN, FinancialAlertStatus.ACKNOWLEDGED]
SAFE_METADATA_KEYS = {
    "accounting_amount",
    "accounting_result",
    "accounting_revenue",
    "accounting_total_cost",
    "activity_allocation_count",
    "activity_total_cost",
    "activity_unclassified_amount",
    "allocation_count",
    "data_quality_status",
    "evaluation_date",
    "evaluation_day",
    "is_partial_month",
    "management_amount",
    "management_total_cost",
    "month_end",
    "sync_freshness_status",
    "unclassified_amount",
    "warnings",
    "wording_limitation",
}
SEVERITY_RANK = {
    FinancialAlertSeverity.CRITICAL: 0,
    FinancialAlertSeverity.WARNING: 1,
    FinancialAlertSeverity.INFO: 2,
}


@dataclass(frozen=True)
class AlertListFilters:
    quick_filter: str
    project: str
    month: str
    alert_type: str
    severity: str
    status: str
    basis: str
    project_status: str
    data_quality: str
    rule: str
    search: str
    sort: str
    direction: str
    page: int


class FinancialAlertsContextBuilder:
    """Read-only presentation builder for persisted financial alerts."""

    @classmethod
    def build(cls, params, *, project=None, organization=None):
        filters = cls._filters(params)
        queryset = cls._base_queryset(project=project, organization=organization)
        queryset = cls._apply_filters(queryset, filters, fixed_project=project)
        queryset = cls._apply_sort(queryset, filters)

        paginator = Paginator(queryset, 25)
        page_obj = paginator.get_page(filters.page)
        rows = [cls._row(alert) for alert in page_obj.object_list]
        summary_queryset = cls._base_queryset(project=project, organization=organization)

        return {
            "alerts": rows,
            "filters": filters,
            "page_obj": page_obj,
            "paginator": paginator,
            "summary": cls._summary(summary_queryset),
            "latest_run": cls._latest_run(organization=organization or getattr(project, "organization", None)),
            "projects": Project.objects.filter(organization=organization).order_by("code", "name") if organization else Project.objects.order_by("code", "name"),
            "rules": FinancialAlertRule.objects.filter(organization=organization).order_by("name") if organization else FinancialAlertRule.objects.order_by("name"),
            "alert_type_choices": FinancialAlertType.choices,
            "severity_choices": FinancialAlertSeverity.choices,
            "status_choices": FinancialAlertStatus.choices,
            "basis_choices": FinancialAlertBasis.choices,
            "project_status_choices": Project.Status.choices,
            "fixed_project": project,
            "query_without_page": cls._query_without_page(params),
        }

    @classmethod
    def build_detail(cls, alert):
        alert = (
            FinancialAlert.objects.select_related("organization", "project", "rule", "acknowledged_by", "dismissed_by")
            .get(pk=alert.pk)
        )
        return {
            "alert": alert,
            "row": cls._row(alert),
            "safe_metadata": cls._safe_metadata(alert.metadata),
            "can_acknowledge": alert.status == FinancialAlertStatus.OPEN,
            "can_dismiss": alert.status in ACTIVE_STATUSES,
            "related_active_alerts": [
                cls._row(item)
                for item in cls._base_queryset(project=alert.project)
                .filter(status__in=ACTIVE_STATUSES)
                .exclude(pk=alert.pk)[:5]
            ],
        }

    @classmethod
    def active_count(cls, organization=None):
        queryset = FinancialAlert.objects.filter(status__in=ACTIVE_STATUSES)
        if organization:
            queryset = queryset.filter(organization=organization)
        return queryset.count()

    @classmethod
    def project_summary(cls, project):
        queryset = cls._base_queryset(project=project).filter(status__in=ACTIVE_STATUSES)
        latest = list(queryset[:5])
        severity_counts = queryset.values("severity").annotate(count=Count("id"))
        counts = {row["severity"]: row["count"] for row in severity_counts}
        highest = cls._highest_severity(queryset)
        return {
            "active_count": queryset.count(),
            "critical_count": counts.get(FinancialAlertSeverity.CRITICAL, 0),
            "warning_count": counts.get(FinancialAlertSeverity.WARNING, 0),
            "highest_severity": highest,
            "latest": [cls._row(alert) for alert in latest],
            "alerts_url": reverse("workspace:project_alerts", kwargs={"project_id": project.id}),
        }

    @classmethod
    def project_financial_banner(cls, *, project, period_start, period_end):
        queryset = cls._base_queryset(project=project).filter(status__in=ACTIVE_STATUSES)
        period_queryset = queryset.filter(
            Q(alert_type=FinancialAlertType.PROJECT_LIFETIME_NEGATIVE)
            | Q(period_start__isnull=True)
            | Q(period_start__lte=period_end, period_end__gte=period_start)
        )
        alerts = list(period_queryset[:5])
        return {
            "active_count": period_queryset.count(),
            "highest_severity": cls._highest_severity(period_queryset),
            "alerts": [cls._row(alert) for alert in alerts],
            "alerts_url": f"{reverse('workspace:project_alerts', kwargs={'project_id': project.id})}?status=active",
        }

    @classmethod
    def dashboard_alert_map(cls, project_ids):
        alerts = (
            FinancialAlert.objects.filter(project_id__in=project_ids, status__in=ACTIVE_STATUSES)
            .values("project_id", "severity")
            .annotate(count=Count("id"))
        )
        mapped = {}
        for item in alerts:
            project_id = item["project_id"]
            existing = mapped.setdefault(project_id, {"active_count": 0, "highest_severity": ""})
            existing["active_count"] += item["count"]
            severity = item["severity"]
            if not existing["highest_severity"] or SEVERITY_RANK.get(severity, 9) < SEVERITY_RANK.get(existing["highest_severity"], 9):
                existing["highest_severity"] = severity
        return mapped

    @classmethod
    def _base_queryset(cls, *, project=None, organization=None):
        queryset = FinancialAlert.objects.select_related("organization", "project", "rule").order_by("-last_detected_at", "-id")
        if project:
            queryset = queryset.filter(project=project, organization=project.organization)
        elif organization:
            queryset = queryset.filter(organization=organization)
        return queryset

    @classmethod
    def _apply_filters(cls, queryset, filters: AlertListFilters, *, fixed_project=None):
        if filters.status and filters.status != "all":
            if filters.status == "active":
                queryset = queryset.filter(status__in=ACTIVE_STATUSES)
            else:
                queryset = queryset.filter(status=filters.status)
        elif filters.quick_filter == "all":
            pass
        elif filters.quick_filter == "critical":
            queryset = queryset.filter(status__in=ACTIVE_STATUSES, severity=FinancialAlertSeverity.CRITICAL)
        elif filters.quick_filter == "warning":
            queryset = queryset.filter(status__in=ACTIVE_STATUSES, severity=FinancialAlertSeverity.WARNING)
        elif filters.quick_filter in {"resolved", "dismissed", "open", "acknowledged"}:
            queryset = queryset.filter(status=filters.quick_filter)
        else:
            queryset = queryset.filter(status__in=ACTIVE_STATUSES)
        if filters.project and not fixed_project:
            queryset = queryset.filter(project_id=filters.project)
        if filters.month:
            month_start, month_end = cls._month_bounds(filters.month)
            if month_start and month_end:
                queryset = queryset.filter(period_start__lte=month_end, period_end__gte=month_start)
        if filters.alert_type and filters.alert_type != "all":
            queryset = queryset.filter(alert_type=filters.alert_type)
        if filters.severity and filters.severity != "all":
            queryset = queryset.filter(severity=filters.severity)
        if filters.basis and filters.basis != "all":
            queryset = queryset.filter(financial_basis=filters.basis)
        if filters.project_status and filters.project_status != "all":
            queryset = queryset.filter(project__status=filters.project_status)
        if filters.data_quality and filters.data_quality != "all":
            queryset = queryset.filter(data_quality_status=filters.data_quality)
        if filters.rule and filters.rule != "all":
            queryset = queryset.filter(rule_id=filters.rule)
        if filters.search:
            query = filters.search.strip()
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(message__icontains=query)
                | Q(project__code__icontains=query)
                | Q(project__name__icontains=query)
                | Q(fingerprint__icontains=query)
            )
        return queryset

    @classmethod
    def _apply_sort(cls, queryset, filters):
        queryset = queryset.annotate(
            severity_rank=Case(
                When(severity=FinancialAlertSeverity.CRITICAL, then=Value(0)),
                When(severity=FinancialAlertSeverity.WARNING, then=Value(1)),
                When(severity=FinancialAlertSeverity.INFO, then=Value(2)),
                default=Value(9),
                output_field=IntegerField(),
            ),
            status_rank=Case(
                When(status=FinancialAlertStatus.OPEN, then=Value(0)),
                When(status=FinancialAlertStatus.ACKNOWLEDGED, then=Value(1)),
                When(status=FinancialAlertStatus.RESOLVED, then=Value(2)),
                When(status=FinancialAlertStatus.DISMISSED, then=Value(3)),
                default=Value(9),
                output_field=IntegerField(),
            ),
        )
        sort_map = {
            "project": "project__code",
            "severity": "severity_rank",
            "status": "status_rank",
            "type": "alert_type",
            "basis": "financial_basis",
            "period": "period_start",
            "evaluated": "evaluated_amount",
            "last_detected": "last_detected_at",
        }
        sort_field = sort_map.get(filters.sort, "status_rank")
        prefix = "-" if filters.direction == "desc" else ""
        if filters.sort:
            return queryset.order_by(f"{prefix}{sort_field}", "-last_detected_at", "-id")
        return queryset.order_by("status_rank", "severity_rank", "-last_detected_at", "-id")

    @classmethod
    def _summary(cls, queryset):
        active = queryset.filter(status__in=ACTIVE_STATUSES)
        return {
            "total": queryset.count(),
            "active": active.count(),
            "open": queryset.filter(status=FinancialAlertStatus.OPEN).count(),
            "acknowledged": queryset.filter(status=FinancialAlertStatus.ACKNOWLEDGED).count(),
            "critical": active.filter(severity=FinancialAlertSeverity.CRITICAL).count(),
            "warning": active.filter(severity=FinancialAlertSeverity.WARNING).count(),
            "resolved": queryset.filter(status=FinancialAlertStatus.RESOLVED).count(),
            "dismissed": queryset.filter(status=FinancialAlertStatus.DISMISSED).count(),
        }

    @staticmethod
    def _latest_run(organization=None):
        queryset = FinancialAlertEvaluationRun.objects.order_by("-started_at", "-id")
        if organization:
            queryset = queryset.filter(organization=organization)
        return queryset.first()

    @staticmethod
    def _filters(params):
        def value(name, default=""):
            return (params.get(name, default) or "").strip()

        try:
            page = max(1, int(value("page", "1")))
        except ValueError:
            page = 1
        return AlertListFilters(
            quick_filter=value("filter", "active") or "active",
            project=value("project"),
            month=value("month"),
            alert_type=value("alert_type", "all") or "all",
            severity=value("severity", "all") or "all",
            status=value("status"),
            basis=value("basis", "all") or "all",
            project_status=value("project_status", "all") or "all",
            data_quality=value("data_quality", "all") or "all",
            rule=value("rule", "all") or "all",
            search=value("q"),
            sort=value("sort"),
            direction="asc" if value("direction") == "asc" else "desc",
            page=page,
        )

    @staticmethod
    def _row(alert):
        currency = alert.currency or "EUR"
        return {
            "alert": alert,
            "type_label": alert.get_alert_type_display(),
            "basis_label": alert.get_financial_basis_display(),
            "severity_label": alert.get_severity_display(),
            "status_label": alert.get_status_display(),
            "period_label": FinancialAlertsContextBuilder._period_label(alert),
            "accounting_display": format_money(alert.accounting_amount, currency) if alert.accounting_amount is not None else "-",
            "management_display": format_money(alert.management_amount, currency) if alert.management_amount is not None else "-",
            "evaluated_display": format_money(alert.evaluated_amount, currency) if alert.evaluated_amount is not None else "-",
            "threshold_display": format_money(alert.threshold_amount, currency) if alert.threshold_amount is not None else "-",
            "currency": currency,
            "warnings": list((alert.metadata or {}).get("warnings") or []),
            "detail_url": reverse("workspace:financial_alert_detail", kwargs={"alert_id": alert.id}),
            "project_url": reverse("workspace:project_detail", kwargs={"project_id": alert.project_id}),
            "project_financials_url": reverse("workspace:project_financials", kwargs={"project_id": alert.project_id}),
            "project_alerts_url": reverse("workspace:project_alerts", kwargs={"project_id": alert.project_id}),
            "can_acknowledge": alert.status == FinancialAlertStatus.OPEN,
            "can_dismiss": alert.status in ACTIVE_STATUSES,
        }

    @staticmethod
    def _period_label(alert):
        if alert.alert_type == FinancialAlertType.PROJECT_LIFETIME_NEGATIVE or not alert.period_start:
            return "Lifetime"
        if alert.period_start == alert.period_end:
            return alert.period_start.strftime("%Y-%m-%d")
        return f"{alert.period_start:%Y-%m-%d} to {alert.period_end:%Y-%m-%d}"

    @staticmethod
    def _safe_metadata(metadata):
        if not isinstance(metadata, dict):
            return {}
        return {key: metadata[key] for key in sorted(metadata) if key in SAFE_METADATA_KEYS}

    @staticmethod
    def _highest_severity(queryset):
        severities = list(queryset.values_list("severity", flat=True).distinct())
        if not severities:
            return ""
        return sorted(severities, key=lambda item: SEVERITY_RANK.get(item, 9))[0]

    @staticmethod
    def _month_bounds(value):
        try:
            year, month = [int(part) for part in value.split("-", 1)]
            last_day = calendar.monthrange(year, month)[1]
            return timezone.datetime(year, month, 1).date(), timezone.datetime(year, month, last_day).date()
        except (TypeError, ValueError):
            return None, None

    @staticmethod
    def _query_without_page(params):
        query = params.copy()
        query.pop("page", None)
        return query.urlencode()
