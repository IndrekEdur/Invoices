from copy import deepcopy

from django.db import transaction

from apps.core.services import AuditService
from apps.projects.models import Project

from .commands import (
    ChangeProjectStatusCommand,
    ChangeProjectStatusResult,
    UpdateProjectDetailsCommand,
)


class ProjectStatusService:
    """Manage local Workspace project lifecycle without external accounting writes."""

    ALLOWED_TRANSITIONS = {
        Project.Status.ACTIVE: {Project.Status.COMPLETED, Project.Status.ARCHIVED},
        Project.Status.COMPLETED: {Project.Status.ACTIVE, Project.Status.ARCHIVED},
        Project.Status.ARCHIVED: {Project.Status.ACTIVE, Project.Status.COMPLETED},
    }

    @classmethod
    def change_status(cls, command: ChangeProjectStatusCommand) -> ChangeProjectStatusResult:
        metadata = deepcopy(command.metadata or {})
        project = command.project
        new_status = command.new_status
        previous_status = project.status
        cls._validate_status(new_status)

        if previous_status == new_status:
            return ChangeProjectStatusResult(
                project=project,
                previous_status=previous_status,
                new_status=new_status,
                changed=False,
                message=f"Project status was already {new_status}.",
                metadata=metadata,
            )

        if new_status not in cls.ALLOWED_TRANSITIONS.get(previous_status, set()):
            raise ValueError(f"Project status transition {previous_status} -> {new_status} is not allowed.")

        with transaction.atomic():
            project.status = new_status
            project.save(update_fields=["status", "updated_at"])
            AuditService.record(
                event_type="project.status_changed",
                message=f"Project {project.code} status changed from {previous_status} to {new_status}.",
                organization=project.organization,
                actor=command.actor,
                object_type="Project",
                object_id=str(project.id),
                metadata={
                    "project_id": project.id,
                    "project_code": project.code,
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "reason": command.reason,
                    "source": metadata.get("source", "project_status_service"),
                    # TODO: MERIT-014 closes matching Merit dimension values when a project is completed.
                },
            )
        return ChangeProjectStatusResult(
            project=project,
            previous_status=previous_status,
            new_status=new_status,
            changed=True,
            message=f"Project {project.code} marked {new_status}.",
            metadata=metadata,
        )

    @staticmethod
    def _validate_status(status):
        if status not in Project.Status.values:
            raise ValueError("Project status is not valid.")


class ProjectDetailsService:
    """Update safe editable Project fields while keeping project code stable."""

    @staticmethod
    def update(command: UpdateProjectDetailsCommand):
        metadata = deepcopy(command.metadata or {})
        project = command.project
        old_values = {
            "name": project.name,
            "description": project.description,
            "project_type": project.project_type,
            "start_date": str(project.start_date) if project.start_date else "",
            "end_date": str(project.end_date) if project.end_date else "",
        }
        if command.project_type not in Project.Type.values:
            raise ValueError("Project type is not valid.")

        with transaction.atomic():
            project.name = command.name
            project.description = command.description
            project.project_type = command.project_type
            project.start_date = command.start_date
            project.end_date = command.end_date
            project.save(
                update_fields=[
                    "name",
                    "description",
                    "project_type",
                    "start_date",
                    "end_date",
                    "updated_at",
                ]
            )
            AuditService.record(
                event_type="project.details_updated",
                message=f"Project {project.code} details updated.",
                organization=project.organization,
                actor=command.actor,
                object_type="Project",
                object_id=str(project.id),
                metadata={
                    "project_id": project.id,
                    "project_code": project.code,
                    "old": old_values,
                    "new": {
                        "name": project.name,
                        "description": project.description,
                        "project_type": project.project_type,
                        "start_date": str(project.start_date) if project.start_date else "",
                        "end_date": str(project.end_date) if project.end_date else "",
                    },
                    "source": metadata.get("source", "project_details_service"),
                },
            )
        return project
