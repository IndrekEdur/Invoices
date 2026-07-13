from django.db.models import Q

from apps.accounting.models import AccountingDimension
from apps.accounting.services import ProjectCodeAllocationService, SuggestNextProjectCodeCommand
from apps.core.models import Organization
from apps.knowledge.services import BuildProjectKnowledgeCommand, ProjectKnowledgeBuilder
from apps.projects.models import Project


class ProjectsContextBuilder:
    """Read-only context builder for Workspace project management views."""

    @staticmethod
    def get_default_organization():
        return Organization.objects.order_by("id").first()

    @staticmethod
    def build(*, filter_value="all", query="", sort="code", direction="desc"):
        organization = ProjectsContextBuilder.get_default_organization()
        if not organization:
            return {
                "organization": None,
                "filter_value": filter_value,
                "query": query,
                "sort": "code",
                "direction": "desc",
                "project_rows": [],
                "status_counts": {
                    "total": 0,
                    "active": 0,
                    "completed": 0,
                    "archived": 0,
                    "linked": 0,
                    "missing_in_workspace": 0,
                    "workspace_only": 0,
                },
            }

        sort = sort if sort in ProjectsContextBuilder._sort_keys() else "code"
        direction = direction if direction in ("asc", "desc") else "desc"

        projects = Project.objects.filter(organization=organization)
        dimensions = AccountingDimension.objects.filter(
            organization=organization,
            dimension_type=AccountingDimension.DimensionType.PROJECT,
            is_active=True,
        )

        if query:
            project_query = (
                Q(code__icontains=query)
                | Q(name__icontains=query)
                | Q(description__icontains=query)
            )
            if query.isdigit():
                project_query |= Q(id=int(query))
            projects = projects.filter(project_query)
            dimensions = dimensions.filter(Q(code__icontains=query) | Q(name__icontains=query))

        project_by_code = {project.code: project for project in projects}
        dimension_by_code = {dimension.code: dimension for dimension in dimensions}
        all_codes = set(project_by_code) | set(dimension_by_code)

        rows = []
        for code in all_codes:
            project = project_by_code.get(code)
            dimension = dimension_by_code.get(code)
            sync_status = ProjectsContextBuilder._sync_status(project, dimension)

            if not ProjectsContextBuilder._matches_filter(project, sync_status, filter_value):
                continue

            rows.append(
                {
                    "id": project.id if project else None,
                    "code": code,
                    "name": project.name if project else dimension.name,
                    "status": project.status if project else "",
                    "project_type": project.project_type if project else "",
                    "start_date": project.start_date if project else None,
                    "end_date": project.end_date if project else None,
                    "created_at": project.created_at if project else dimension.created_at,
                    "updated_at": project.updated_at if project else dimension.updated_at,
                    "project": project,
                    "dimension": dimension,
                    "sync_status": sync_status,
                    "source": ProjectsContextBuilder._source(project, dimension),
                }
            )
        rows = ProjectsContextBuilder._sort_rows(rows, sort=sort, direction=direction)

        return {
            "organization": organization,
            "filter_value": filter_value,
            "query": query,
            "sort": sort,
            "direction": direction,
            "sort_options": (
                ("id", "Database ID"),
                ("code", "Project code"),
                ("name", "Name"),
                ("status", "Status"),
                ("project_type", "Type"),
                ("created_at", "Created"),
                ("updated_at", "Updated"),
            ),
            "direction_options": (("asc", "Ascending"), ("desc", "Descending")),
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
        organization = ProjectsContextBuilder.get_default_organization()
        project_query = Project.objects
        if organization:
            project_query = project_query.filter(organization=organization)
        project = project_query.get(id=project_id)
        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))
        dimension = AccountingDimension.objects.filter(
            organization=project.organization,
            dimension_type=AccountingDimension.DimensionType.PROJECT,
            code=project.code,
            is_active=True,
        ).first()

        return {
            "project": project,
            "knowledge": knowledge,
            "dimension": dimension,
            "parties_count": len(knowledge.parties),
            "addresses_count": len(knowledge.addresses),
            "related_email_count": len(knowledge.emails),
            "related_document_count": len(knowledge.documents),
            "question_count": len(knowledge.questions),
            "evidence_count": len(knowledge.evidence),
            "latest_activity": tuple(reversed(knowledge.timeline))[:5],
            "timeline_entries": tuple(reversed(knowledge.timeline)),
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
        if filter_value in ("linked", "missing_in_workspace", "workspace_only"):
            return sync_status == filter_value
        if filter_value in ("active", "completed", "archived"):
            return bool(project and project.status == filter_value)
        return True

    @staticmethod
    def _status_counts(projects, dimensions):
        project_list = list(projects)
        dimension_codes = {dimension.code for dimension in dimensions}
        project_codes = {project.code for project in project_list}

        return {
            "total": len(project_codes | dimension_codes),
            "active": sum(1 for project in project_list if project.status == Project.Status.ACTIVE),
            "completed": sum(1 for project in project_list if project.status == Project.Status.COMPLETED),
            "archived": sum(1 for project in project_list if project.status == Project.Status.ARCHIVED),
            "linked": len(project_codes & dimension_codes),
            "missing_in_workspace": len(dimension_codes - project_codes),
            "workspace_only": len(project_codes - dimension_codes),
        }

    @staticmethod
    def _sort_keys():
        return {
            "id": lambda row: row["id"] or 0,
            "code": lambda row: row["code"] or "",
            "name": lambda row: row["name"] or "",
            "status": lambda row: row["status"] or "",
            "project_type": lambda row: row["project_type"] or "",
            "created_at": lambda row: row["created_at"],
            "updated_at": lambda row: row["updated_at"],
        }

    @staticmethod
    def _sort_rows(rows, *, sort, direction):
        return sorted(
            rows,
            key=ProjectsContextBuilder._sort_keys()[sort],
            reverse=direction == "desc",
        )
