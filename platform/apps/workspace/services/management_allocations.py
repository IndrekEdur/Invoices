from calendar import monthrange
from datetime import date
from decimal import Decimal

from apps.accounting.models import (
    AllocationSourceAmountBasis,
    AllocationSourceType,
    AllocationStrategy,
    ManagementAllocationPeriod,
    ManagementAllocationVersion,
    ManagementCostPool,
    PeriodStatus,
    VersionStatus,
)
from apps.accounting.services import AggregateProjectFinancialsCommand, ProjectFinancialAggregationService
from apps.core.models import Organization
from apps.projects.models import Project, ProjectParty

from .formatting import format_money, format_percent


class ManagementAllocationContextBuilder:
    """Read-only context for Workspace management allocation screens."""

    PRESELECTION_NONE = "none"
    PRESELECTION_POSITIVE_REVENUE = "positive_revenue"
    PRESELECTION_ANY_REVENUE = "any_revenue"
    PRESELECTION_FINANCIAL_ACTIVITY = "financial_activity"
    PRESELECTION_ACTIVE_PROJECTS = "active_projects"

    PRESELECTION_CHOICES = (
        (PRESELECTION_NONE, "None"),
        (PRESELECTION_POSITIVE_REVENUE, "Positive revenue"),
        (PRESELECTION_ANY_REVENUE, "Any revenue"),
        (PRESELECTION_FINANCIAL_ACTIVITY, "Financial activity"),
        (PRESELECTION_ACTIVE_PROJECTS, "Active Projects"),
    )

    PROJECT_FILTER_CHOICES = (
        ("", "All Projects"),
        ("has_revenue", "Has revenue"),
        ("has_cost", "Has direct cost"),
        ("financial_activity", "Has financial activity"),
    )

    SORT_CHOICES = (
        ("revenue", "Revenue"),
        ("code", "Project code"),
        ("name", "Name"),
        ("status", "Status"),
        ("cost", "Direct cost"),
    )

    @staticmethod
    def get_default_organization():
        return Organization.objects.order_by("id").first()

    @classmethod
    def build_list(cls, *, month="", pool_id="", status="", strategy="", query=""):
        organization = cls.get_default_organization()
        versions = ManagementAllocationVersion.objects.none()
        if organization:
            versions = ManagementAllocationVersion.objects.filter(period__organization=organization).select_related(
                "period", "pool", "source_project", "created_by", "approved_by"
            )
        if month:
            year, month_number = cls._parse_month(month)
            if year and month_number:
                versions = versions.filter(period__year=year, period__month=month_number)
        if pool_id:
            versions = versions.filter(pool_id=pool_id)
        if status:
            versions = versions.filter(status=status)
        if strategy:
            versions = versions.filter(metadata__strategy=strategy)
        if query:
            versions = (
                versions.filter(pool__name__icontains=query)
                | versions.filter(source_project__code__icontains=query)
                | versions.filter(source_project__name__icontains=query)
                | versions.filter(reason__icontains=query)
            )
        versions = versions.order_by(
            "-period__year",
            "-period__month",
            "source_type",
            "pool__display_order",
            "pool__name",
            "source_project__code",
            "-version_number",
        )
        rows = [cls._version_row(version) for version in versions]
        selected_month = month or date.today().strftime("%Y-%m")
        return {
            "organization": organization,
            "versions": rows,
            "pools": ManagementCostPool.objects.filter(organization=organization).order_by("display_order", "name") if organization else [],
            "status_choices": VersionStatus.choices,
            "strategy_choices": AllocationStrategy.choices,
            "source_type_choices": AllocationSourceType.choices,
            "filters": {"month": selected_month, "pool_id": pool_id, "status": status, "strategy": strategy, "q": query},
            "summary": cls._summary(organization, selected_month),
        }

    @classmethod
    def build_create(
        cls,
        *,
        month="",
        source_type="",
        source_project_id="",
        source_currency="",
        recipient_preselection="",
        selected_project_ids=None,
        project_query="",
        project_status="",
        project_filter="",
        sort="",
        preserve_selection=False,
    ):
        organization = cls.get_default_organization()
        selected_month = month or date.today().strftime("%Y-%m")
        year, month_number = cls._parse_month(selected_month)
        projects = []
        managers = []
        if organization:
            projects = list(Project.objects.filter(organization=organization).order_by("code", "id"))
            managers = list(
                ProjectParty.objects.filter(
                    organization=organization,
                    role=ProjectParty.Role.PROJECT_MANAGER,
                    is_active=True,
                ).order_by("name", "email", "project__code")
            )
        selected_source_type = source_type or AllocationSourceType.COST_POOL
        source_project = None
        if selected_source_type == AllocationSourceType.WORKSPACE_PROJECT and source_project_id:
            source_project = Project.objects.filter(organization=organization, id=source_project_id).first()
        criterion = cls._valid_preselection(recipient_preselection)
        selected_ids = cls._normalize_ids(selected_project_ids or [])
        project_rows = cls._project_rows(
            projects,
            year,
            month_number,
            source_project=source_project,
            criterion=criterion,
            selected_project_ids=selected_ids,
            preserve_selection=preserve_selection,
        )
        suggested_ids = [row["project"].id for row in project_rows if row["suggested"]]
        if not preserve_selection:
            selected_ids = suggested_ids
        visible_rows = cls._filter_project_rows(
            project_rows,
            query=project_query,
            status=project_status,
            project_filter=project_filter,
        )
        visible_rows = cls._sort_project_rows(visible_rows, sort)
        selected_count = sum(1 for row in project_rows if row["selected"])
        no_preselection_message = ""
        if (
            criterion == cls.PRESELECTION_POSITIVE_REVENUE
            and not suggested_ids
            and not preserve_selection
        ):
            no_preselection_message = "No Projects with positive revenue were found for the selected month."
        return {
            "organization": organization,
            "pools": ManagementCostPool.objects.filter(organization=organization, is_active=True).order_by("display_order", "name") if organization else [],
            "source_type_choices": AllocationSourceType.choices,
            "source_amount_basis_choices": AllocationSourceAmountBasis.choices,
            "recipient_preselection_choices": cls.PRESELECTION_CHOICES,
            "project_filter_choices": cls.PROJECT_FILTER_CHOICES,
            "project_sort_choices": cls.SORT_CHOICES,
            "project_status_choices": Project.Status.choices,
            "source_projects": projects,
            "selected_source_type": selected_source_type,
            "selected_source_project": source_project,
            "source_currency": source_currency,
            "source_preview": cls._source_preview(source_project, year, month_number, source_currency) if source_project else None,
            "projects": visible_rows,
            "all_project_rows": project_rows,
            "selected_project_ids": selected_ids,
            "suggested_project_ids": suggested_ids,
            "suggested_project_ids_csv": ",".join(str(project_id) for project_id in suggested_ids),
            "selected_count": selected_count,
            "no_preselection_message": no_preselection_message,
            "project_filters": {
                "recipient_preselection": criterion,
                "project_query": project_query,
                "project_status": project_status,
                "project_filter": project_filter,
                "sort": cls._valid_sort(sort),
            },
            "project_managers": managers,
            "strategy_choices": AllocationStrategy.choices,
            "selected_month": selected_month,
        }

    @classmethod
    def build_detail(cls, version_id):
        version = ManagementAllocationVersion.objects.select_related(
            "period", "pool", "source_project", "created_by", "approved_by"
        ).get(id=version_id)
        entries = list(version.entries.select_related("project").order_by("project__code", "project_id"))
        source_amount = Decimal(str((version.metadata or {}).get("source_amount", "0")))
        allocated = sum(entry.amount for entry in entries)
        percentage_total = sum(entry.percentage for entry in entries)
        history = [
            cls._version_row(item)
            for item in ManagementAllocationVersion.objects.filter(**cls._source_filter(version))
            .select_related("period", "pool", "source_project", "created_by", "approved_by")
            .order_by("-version_number")
        ]
        return {
            "version": version,
            "entries": entries,
            "history": history,
            "source_amount": source_amount,
            "source_amount_display": format_money(source_amount, "EUR"),
            "source_type": version.source_type,
            "source_label": version.source_label,
            "source_display_name": version.source_display_name,
            "source_amount_basis": version.source_amount_basis,
            "source_currency": version.source_currency or "EUR",
            "allocated_amount": allocated,
            "allocated_amount_display": format_money(allocated, "EUR"),
            "unallocated_amount": source_amount - allocated,
            "unallocated_amount_display": format_money(source_amount - allocated, "EUR"),
            "total_percentage": percentage_total,
            "total_percentage_display": format_percent(percentage_total, places=4),
            "balanced": source_amount == allocated and (source_amount == 0 or percentage_total == Decimal("100.0000")),
            "warnings": (version.metadata or {}).get("calculation_diagnostics", {}).get("warnings", []),
            "diagnostics": (version.metadata or {}).get("calculation_diagnostics", {}),
            "source_origin": (version.metadata or {}).get("source_amount_origin", ""),
            "strategy": (version.metadata or {}).get("strategy", ""),
            "projects": Project.objects.filter(organization=version.period.organization).order_by("code", "id"),
        }

    @classmethod
    def _project_rows(
        cls,
        projects,
        year,
        month,
        source_project=None,
        criterion=PRESELECTION_POSITIVE_REVENUE,
        selected_project_ids=None,
        preserve_selection=False,
    ):
        selected_project_ids = set(selected_project_ids or [])
        if not year or not month:
            return [
                {
                    "project": project,
                    "revenue": Decimal("0"),
                    "revenue_display": format_money(Decimal("0"), "EUR"),
                    "cost": Decimal("0"),
                    "cost_display": format_money(Decimal("0"), "EUR"),
                    "allocation_count": 0,
                    "unclassified_amount": Decimal("0"),
                    "data_quality_status": "unknown",
                    "data_quality_badge": "unknown",
                    "managers": [],
                    "is_source_project": bool(source_project and project.id == source_project.id),
                    "suggested": False,
                    "selected": False,
                    "selection_reason": "",
                }
                for project in projects
            ]
        period_start = date(year, month, 1)
        period_end = date(year, month, monthrange(year, month)[1])
        aggregation_service = ProjectFinancialAggregationService()
        rows = []
        for project in projects:
            result = aggregation_service.aggregate(
                AggregateProjectFinancialsCommand(project=project, period_start=period_start, period_end=period_end)
            )
            is_source_project = bool(source_project and project.id == source_project.id)
            suggested = cls._matches_preselection(project, result, criterion) and not is_source_project
            selected = (project.id in selected_project_ids) if preserve_selection else suggested
            if is_source_project:
                selected = False
                suggested = False
            rows.append(
                {
                    "project": project,
                    "revenue": result.revenue,
                    "revenue_display": format_money(result.revenue, result.currency or "EUR"),
                    "cost": result.total_cost,
                    "cost_display": format_money(result.total_cost, result.currency or "EUR"),
                    "allocation_count": result.allocation_count,
                    "unclassified_amount": result.unclassified_amount,
                    "data_quality_status": result.data_quality_status,
                    "data_quality_badge": cls._data_quality_badge(result),
                    "managers": list(project.parties.filter(role=ProjectParty.Role.PROJECT_MANAGER, is_active=True)),
                    "is_source_project": is_source_project,
                    "suggested": suggested,
                    "selected": selected,
                    "selection_reason": cls._selection_reason(criterion, suggested, is_source_project),
                }
            )
        return cls._sort_project_rows(rows, "")

    @classmethod
    def _matches_preselection(cls, project, result, criterion):
        if criterion == cls.PRESELECTION_NONE:
            return False
        if criterion == cls.PRESELECTION_POSITIVE_REVENUE:
            return result.revenue > Decimal("0")
        if criterion == cls.PRESELECTION_ANY_REVENUE:
            return result.revenue != Decimal("0")
        if criterion == cls.PRESELECTION_FINANCIAL_ACTIVITY:
            return (
                result.revenue != Decimal("0")
                or result.total_cost != Decimal("0")
                or result.allocation_count > 0
                or result.unclassified_amount != Decimal("0")
            )
        if criterion == cls.PRESELECTION_ACTIVE_PROJECTS:
            return project.status == Project.Status.ACTIVE
        return False

    @classmethod
    def _filter_project_rows(cls, rows, *, query="", status="", project_filter=""):
        query = (query or "").strip().lower()
        filtered = []
        for row in rows:
            project = row["project"]
            if query and query not in str(project.id).lower() and query not in project.code.lower() and query not in project.name.lower():
                continue
            if status and project.status != status:
                continue
            if project_filter == "has_revenue" and row["revenue"] == Decimal("0"):
                continue
            if project_filter == "has_cost" and row["cost"] == Decimal("0"):
                continue
            if project_filter == "financial_activity" and not cls._has_financial_activity(row):
                continue
            filtered.append(row)
        return filtered

    @staticmethod
    def _has_financial_activity(row):
        return (
            row["revenue"] != Decimal("0")
            or row["cost"] != Decimal("0")
            or row["allocation_count"] > 0
            or row["unclassified_amount"] != Decimal("0")
        )

    @classmethod
    def _sort_project_rows(cls, rows, sort):
        sort = cls._valid_sort(sort)
        if sort == "code":
            return sorted(rows, key=lambda row: (row["project"].code, row["project"].id))
        if sort == "name":
            return sorted(rows, key=lambda row: (row["project"].name.lower(), row["project"].code, row["project"].id))
        if sort == "status":
            return sorted(rows, key=lambda row: (row["project"].status, row["project"].code, row["project"].id))
        if sort == "cost":
            return sorted(rows, key=lambda row: (row["cost"], row["project"].code), reverse=True)
        return sorted(rows, key=lambda row: (row["revenue"], row["project"].code), reverse=True)

    @classmethod
    def _valid_preselection(cls, criterion):
        values = {value for value, _label in cls.PRESELECTION_CHOICES}
        return criterion if criterion in values else cls.PRESELECTION_POSITIVE_REVENUE

    @classmethod
    def _valid_sort(cls, sort):
        values = {value for value, _label in cls.SORT_CHOICES}
        return sort if sort in values else "revenue"

    @staticmethod
    def _normalize_ids(project_ids):
        normalized = []
        for project_id in project_ids:
            try:
                normalized.append(int(project_id))
            except (TypeError, ValueError):
                continue
        return list(dict.fromkeys(normalized))

    @staticmethod
    def _data_quality_badge(result):
        if result.data_quality_status != "ok":
            return result.data_quality_status
        if result.unclassified_amount != Decimal("0"):
            return "unclassified"
        return "ok"

    @classmethod
    def _selection_reason(cls, criterion, suggested, is_source_project):
        if is_source_project:
            return "Source Project cannot receive its own redistributed cost."
        if not suggested:
            return ""
        labels = dict(cls.PRESELECTION_CHOICES)
        return f"Suggested by {labels.get(criterion, criterion)}."

    @staticmethod
    def _source_preview(source_project, year, month, source_currency=""):
        if not source_project or not year or not month:
            return None
        period_start = date(year, month, 1)
        period_end = date(year, month, monthrange(year, month)[1])
        result = ProjectFinancialAggregationService().aggregate(
            AggregateProjectFinancialsCommand(
                project=source_project,
                period_start=period_start,
                period_end=period_end,
                currency=source_currency or None,
                metadata={"source": "workspace_management_allocation_source_preview"},
            )
        )
        return {
            "project": source_project,
            "amount": result.total_cost,
            "amount_display": format_money(result.total_cost, result.currency or source_currency or "EUR"),
            "currency": result.currency or source_currency or "EUR",
            "data_quality_status": result.data_quality_status,
            "warnings": result.warnings,
            "period_start": period_start,
            "period_end": period_end,
        }

    @staticmethod
    def _version_row(version):
        entries = list(version.entries.all())
        source_amount = Decimal(str((version.metadata or {}).get("source_amount", "0")))
        allocated = sum(entry.amount for entry in entries)
        warnings = (version.metadata or {}).get("calculation_diagnostics", {}).get("warnings", [])
        return {
            "version": version,
            "period": version.period.period_label,
            "strategy": (version.metadata or {}).get("strategy", ""),
            "source_label": version.source_label,
            "source_type": version.source_type,
            "source_display_name": version.source_display_name,
            "source_amount": source_amount,
            "source_amount_display": format_money(source_amount, "EUR"),
            "allocated_amount": allocated,
            "allocated_amount_display": format_money(allocated, "EUR"),
            "project_count": len(entries),
            "warning_count": len(warnings),
        }

    @staticmethod
    def _source_filter(version):
        if version.source_type == AllocationSourceType.WORKSPACE_PROJECT:
            return {
                "period": version.period,
                "source_type": AllocationSourceType.WORKSPACE_PROJECT,
                "source_project": version.source_project,
            }
        return {"period": version.period, "source_type": AllocationSourceType.COST_POOL, "pool": version.pool}

    @classmethod
    def _summary(cls, organization, selected_month):
        if not organization:
            return {}
        year, month_number = cls._parse_month(selected_month)
        month_versions = ManagementAllocationVersion.objects.filter(period__organization=organization)
        if year and month_number:
            month_versions = month_versions.filter(period__year=year, period__month=month_number)
        allocated = sum(sum(entry.amount for entry in version.entries.all()) for version in month_versions.prefetch_related("entries"))
        return {
            "active_pools": ManagementCostPool.objects.filter(organization=organization, is_active=True).count(),
            "drafts": month_versions.filter(status=VersionStatus.DRAFT).count(),
            "approved": month_versions.filter(status=VersionStatus.APPROVED).count(),
            "needs_review": month_versions.filter(status=VersionStatus.DRAFT).count(),
            "superseded": month_versions.filter(status=VersionStatus.SUPERSEDED).count(),
            "allocated_amount_display": format_money(allocated, "EUR"),
        }

    @staticmethod
    def _parse_month(month):
        try:
            year_text, month_text = str(month or "").split("-", 1)
            year = int(year_text)
            month_number = int(month_text)
            date(year, month_number, 1)
            return year, month_number
        except (TypeError, ValueError):
            return None, None
