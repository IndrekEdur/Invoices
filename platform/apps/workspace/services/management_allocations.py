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
    def build_create(cls, *, month="", source_type="", source_project_id="", source_currency=""):
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
        project_rows = cls._project_rows(projects, year, month_number, source_project=source_project)
        return {
            "organization": organization,
            "pools": ManagementCostPool.objects.filter(organization=organization, is_active=True).order_by("display_order", "name") if organization else [],
            "source_type_choices": AllocationSourceType.choices,
            "source_amount_basis_choices": AllocationSourceAmountBasis.choices,
            "source_projects": projects,
            "selected_source_type": selected_source_type,
            "selected_source_project": source_project,
            "source_currency": source_currency,
            "source_preview": cls._source_preview(source_project, year, month_number, source_currency) if source_project else None,
            "projects": project_rows,
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
    def _project_rows(cls, projects, year, month, source_project=None):
        if not year or not month:
            return [
                {
                    "project": project,
                    "revenue": Decimal("0"),
                    "cost": Decimal("0"),
                    "managers": [],
                    "is_source_project": bool(source_project and project.id == source_project.id),
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
            rows.append(
                {
                    "project": project,
                    "revenue": result.revenue,
                    "revenue_display": format_money(result.revenue, result.currency or "EUR"),
                    "cost": result.total_cost,
                    "cost_display": format_money(result.total_cost, result.currency or "EUR"),
                    "managers": list(project.parties.filter(role=ProjectParty.Role.PROJECT_MANAGER, is_active=True)),
                    "is_source_project": bool(source_project and project.id == source_project.id),
                }
            )
        return rows

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
