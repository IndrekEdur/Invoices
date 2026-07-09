from django.db import transaction

from apps.accounting.services import ProjectCodeAllocationService, SuggestNextProjectCodeCommand
from apps.core.services import AuditService
from apps.projects.models import Project

from .commands import CreateProjectWithSuggestedCodeCommand, CreateProjectWithSuggestedCodeResult


class ProjectCreationService:
    """Create projects through the controlled platform workflow."""

    @staticmethod
    def create_with_suggested_code(
        command: CreateProjectWithSuggestedCodeCommand,
    ) -> CreateProjectWithSuggestedCodeResult:
        metadata = dict(command.metadata or {})

        with transaction.atomic():
            allocation = ProjectCodeAllocationService.suggest_next_code(
                SuggestNextProjectCodeCommand(
                    organization=command.organization,
                    prefix=command.prefix,
                    min_code=command.min_code,
                    metadata=metadata,
                )
            )

            project = Project.objects.create(
                organization=command.organization,
                code=allocation.suggested_code,
                name=command.name,
                description=command.description,
                project_type=command.project_type,
                status=command.status,
                start_date=command.start_date,
                end_date=command.end_date,
                metadata=metadata,
            )

            AuditService.record(
                event_type="project.created_with_suggested_code",
                message=f"Project created with suggested code: {project.code} {project.name}",
                organization=command.organization,
                actor=command.actor,
                object_type="Project",
                object_id=str(project.id),
                metadata={
                    "project_uuid": str(project.uuid),
                    "suggested_code": allocation.suggested_code,
                    "allocation_summary": allocation.source_summary,
                },
            )

            return CreateProjectWithSuggestedCodeResult(
                project=project,
                suggested_code=allocation.suggested_code,
                allocation_summary=allocation.source_summary,
                metadata=metadata,
            )
