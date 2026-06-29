from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.services import AuditService

from ..models import Document


class DocumentStatusService:
    """Central service for changing document summary status."""

    @staticmethod
    def change_status(command):
        valid_statuses = {choice for choice, _label in Document.Status.choices}
        if command.new_status not in valid_statuses:
            raise ValidationError({"new_status": "Unknown document status."})

        metadata = dict(command.metadata or {})
        document = command.document
        previous_status = document.status
        message = command.message or f"Document status changed from {previous_status} to {command.new_status}."

        with transaction.atomic():
            document.status = command.new_status
            document.save(update_fields=["status", "updated_at"])
            AuditService.record(
                event_type="document.status_changed",
                message=message,
                organization=document.organization,
                actor=command.actor,
                object_type="Document",
                object_id=str(document.uuid),
                metadata={
                    "previous_status": previous_status,
                    "new_status": command.new_status,
                    **metadata,
                },
            )

            return document
