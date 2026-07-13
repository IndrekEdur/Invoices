from copy import deepcopy

from django.db import transaction
from django.db.models import Q

from apps.core.services import AuditService
from apps.projects.models import Project

from .commands import (
    CreateProjectFromAccountingDimensionCommand,
    CreateProjectFromAccountingDimensionResult,
)


class ProjectDimensionImportService:
    """Create a Workspace Project from a cached accounting project dimension."""

    @staticmethod
    def create_project(
        command: CreateProjectFromAccountingDimensionCommand,
    ) -> CreateProjectFromAccountingDimensionResult:
        from apps.accounting.models import AccountingDimension, AccountingGLAllocation

        metadata = deepcopy(command.metadata or {})
        dimension = command.accounting_dimension
        if dimension.dimension_type != AccountingDimension.DimensionType.PROJECT:
            raise ValueError("Only project accounting dimensions can be imported as Workspace projects.")
        if command.status not in Project.Status.values:
            raise ValueError("Project status is not valid.")
        if command.project_type not in Project.Type.values:
            raise ValueError("Project type is not valid.")

        with transaction.atomic():
            project = Project.objects.filter(
                organization=dimension.organization,
                code=dimension.code,
            ).first()
            created = project is None
            if created:
                project = Project.objects.create(
                    organization=dimension.organization,
                    code=dimension.code,
                    name=command.project_name or dimension.name,
                    description=command.description,
                    project_type=command.project_type,
                    status=command.status,
                    metadata={
                        "source": "accounting_dimension_import",
                        "accounting_dimension_id": dimension.id,
                        "accounting_provider": dimension.provider,
                        **metadata,
                    },
                )

            allocations = AccountingGLAllocation.objects.filter(
                organization=dimension.organization,
                project__isnull=True,
                dimension_code=project.code,
            ).filter(Q(accounting_dimension=dimension) | Q(accounting_dimension__isnull=True))
            linked_count = allocations.update(project=project)

            AuditService.record(
                event_type="project.created_from_accounting_dimension",
                message=(
                    f"Project {project.code} linked from accounting dimension "
                    f"{dimension.id}; allocations linked: {linked_count}."
                ),
                organization=dimension.organization,
                actor=command.actor,
                object_type="Project",
                object_id=str(project.id),
                metadata={
                    "project_id": project.id,
                    "project_code": project.code,
                    "accounting_dimension_id": dimension.id,
                    "accounting_dimension_code": dimension.code,
                    "provider": dimension.provider,
                    "integration_id": dimension.integration_id,
                    "created": created,
                    "linked_allocation_count": linked_count,
                    "source": metadata.get("source", "project_dimension_import_service"),
                },
            )

        message = "Workspace project created from Merit dimension." if created else "Workspace project already existed."
        return CreateProjectFromAccountingDimensionResult(
            project=project,
            accounting_dimension=dimension,
            created=created,
            linked_allocation_count=linked_count,
            message=message,
            metadata=metadata,
        )
