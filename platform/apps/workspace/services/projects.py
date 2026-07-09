from django.db.models import Q

from apps.accounting.models import AccountingDimension
from apps.accounting.services import ProjectCodeAllocationService, SuggestNextProjectCodeCommand
from apps.communications.models import EmailProjectLink
from apps.core.models import Organization
from apps.projects.models import Project


class ProjectsContextBuilder:
    """Read-only context builder for Workspace project management views."""

    @staticmethod
    def get_default_organization():
        return Organization.objects.order_by("id").first()

    @staticmethod
    def build(*, filter_value="all", query=""):
        organization = ProjectsContextBuilder.get_default_organization()
        if not organization:
            return {
                "organization": None,
                "filter_value": filter_value,
                "query": query,
                "project_rows": [],
                "status_counts": {
                    "all": 0,
                    "active": 0,
                    "planned": 0,
                    "archived": 0,
                    "missing_in_workspace": 0,
                    "workspace_only": 0,
                },
            }

        projects = Project.objects.filter(organization=organization).order_by("code", "id")
        dimensions = AccountingDimension.objects.filter(
            organization=organization,
            dimension_type=AccountingDimension.DimensionType.PROJECT,
            is_active=True,
        ).order_by("code", "id")

        if query:
            projects = projects.filter(Q(code__icontains=query) | Q(name__icontains=query))
            dimensions = dimensions.filter(Q(code__icontains=query) | Q(name__icontains=query))

        project_by_code = {project.code: project for project in projects}
        dimension_by_code = {dimension.code: dimension for dimension in dimensions}
        all_codes = sorted(set(project_by_code) | set(dimension_by_code))

        rows = []
        for code in all_codes:
            project = project_by_code.get(code)
            dimension = dimension_by_code.get(code)
            sync_status = ProjectsContextBuilder._sync_status(project, dimension)

            if not ProjectsContextBuilder._matches_filter(project, sync_status, filter_value):
                continue

            rows.append(
                {
                    "code": code,
                    "name": project.name if project else dimension.name,
                    "status": project.status if project else "",
                    "project_type": project.project_type if project else "",
                    "start_date": project.start_date if project else None,
                    "end_date": project.end_date if project else None,
                    "created_at": project.created_at if project else dimension.created_at,
                    "project": project,
                    "dimension": dimension,
                    "sync_status": sync_status,
                    "source": ProjectsContextBuilder._source(project, dimension),
                }
            )

        return {
            "organization": organization,
            "filter_value": filter_value,
            "query": query,
            "project_rows": rows,
            "status_counts": ProjectsContextBuilder._status_counts(projects, dimensions),
        }

    @staticmethod
    def build_create_context(*, prefix="", min_code=None):
        organization = ProjectsContextBuilder.get_default_organization()
        suggestion = None
        if organization:
            suggestion = ProjectCodeAllocationService.suggest_next_code(
                SuggestNextProjectCodeCommand(
                    organization=organization,
                    prefix=prefix,
                    min_code=min_code,
                    metadata={"source": "workspace_project_create"},
                )
            )

        return {
            "organization": organization,
            "prefix": prefix,
            "min_code": min_code or "",
            "suggestion": suggestion,
            "project_status_choices": Project.Status.choices,
            "project_type_choices": Project.Type.choices,
        }

    @staticmethod
    def build_detail(*, project_id):
        project = Project.objects.get(id=project_id)
        dimension = AccountingDimension.objects.filter(
            organization=project.organization,
            dimension_type=AccountingDimension.DimensionType.PROJECT,
            code=project.code,
            is_active=True,
        ).first()

        return {
            "project": project,
            "dimension": dimension,
            "parties_count": project.parties.count(),
            "addresses_count": project.addresses.count(),
            "related_email_count": EmailProjectLink.objects.filter(
                organization=project.organization,
                project=project,
            ).count(),
            "sync_status": ProjectsContextBuilder._sync_status(project, dimension),
        }

    @staticmethod
    def _sync_status(project, dimension):
        if project and dimension:
            return "linked"
        if dimension and not project:
            return "missing_in_workspace"
        return "workspace_only"

    @staticmethod
    def _source(project, dimension):
        if project and dimension:
            return "Workspace + Merit cache"
        if dimension:
            return "Merit cache"
        return "Workspace"

    @staticmethod
    def _matches_filter(project, sync_status, filter_value):
        if filter_value in ("", "all"):
            return True
        if filter_value in ("missing_in_workspace", "workspace_only"):
            return sync_status == filter_value
        if filter_value in ("active", "planned", "archived"):
            return bool(project and project.status == filter_value)
        return True

    @staticmethod
    def _status_counts(projects, dimensions):
        project_list = list(projects)
        dimension_codes = {dimension.code for dimension in dimensions}
        project_codes = {project.code for project in project_list}

        return {
            "all": len(project_codes | dimension_codes),
            "active": sum(1 for project in project_list if project.status == Project.Status.ACTIVE),
            "planned": sum(1 for project in project_list if project.status == Project.Status.PLANNED),
            "archived": sum(1 for project in project_list if project.status == Project.Status.ARCHIVED),
            "missing_in_workspace": len(dimension_codes - project_codes),
            "workspace_only": len(project_codes - dimension_codes),
        }
