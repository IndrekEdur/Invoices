from django.db import transaction
from django.utils import timezone

from apps.core.services import AuditService

from ..models import EmailProjectLink


class EmailProjectLinkService:
    """Records human decisions about project context for e-mail messages."""

    @staticmethod
    def confirm(command):
        link = command.link
        metadata = dict(command.metadata or {})

        with transaction.atomic():
            link.status = EmailProjectLink.Status.CONFIRMED
            link.confirmed_by = command.actor
            link.confirmed_at = timezone.now()
            link.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])

            AuditService.record(
                event_type="email_project_link.confirmed",
                message=f"Email project link confirmed: {link}",
                organization=link.organization,
                actor=command.actor,
                object_type="EmailProjectLink",
                object_id=str(link.id),
                metadata={
                    "email_message_id": link.email_message_id,
                    "project_id": link.project_id,
                    "confidence": link.confidence,
                    "evidence": link.evidence,
                    "decision_metadata": metadata,
                },
            )

            return link

    @staticmethod
    def reject(command):
        link = command.link
        metadata = dict(command.metadata or {})
        link_metadata = dict(link.metadata or {})
        if command.reason:
            link_metadata["rejection_reason"] = command.reason

        with transaction.atomic():
            link.status = EmailProjectLink.Status.REJECTED
            link.metadata = link_metadata
            link.save(update_fields=["status", "metadata", "updated_at"])

            AuditService.record(
                event_type="email_project_link.rejected",
                message=f"Email project link rejected: {link}",
                organization=link.organization,
                actor=command.actor,
                object_type="EmailProjectLink",
                object_id=str(link.id),
                metadata={
                    "email_message_id": link.email_message_id,
                    "project_id": link.project_id,
                    "reason": command.reason,
                    "confidence": link.confidence,
                    "evidence": link.evidence,
                    "decision_metadata": metadata,
                },
            )

            return link

    @staticmethod
    def correct(command):
        original_link = command.link
        metadata = dict(command.metadata or {})
        original_metadata = dict(original_link.metadata or {})
        if command.reason:
            original_metadata["correction_reason"] = command.reason

        with transaction.atomic():
            original_link.status = EmailProjectLink.Status.CORRECTED
            original_link.metadata = original_metadata
            original_link.save(update_fields=["status", "metadata", "updated_at"])

            confirmed_link, _created = EmailProjectLink.objects.get_or_create(
                email_message=original_link.email_message,
                project=command.new_project,
                defaults={
                    "organization": original_link.organization,
                    "status": EmailProjectLink.Status.CONFIRMED,
                    "confidence": 100,
                    "evidence": {
                        "corrected_from_project_id": original_link.project_id,
                        "reason": command.reason,
                    },
                    "confirmed_by": command.actor,
                    "confirmed_at": timezone.now(),
                    "metadata": metadata,
                },
            )

            if not _created:
                confirmed_link.status = EmailProjectLink.Status.CONFIRMED
                confirmed_link.confirmed_by = command.actor
                confirmed_link.confirmed_at = timezone.now()
                confirmed_link.metadata = metadata
                confirmed_link.save(
                    update_fields=["status", "confirmed_by", "confirmed_at", "metadata", "updated_at"]
                )

            AuditService.record(
                event_type="email_project_link.corrected",
                message=f"Email project link corrected: {original_link} -> {command.new_project.code}",
                organization=original_link.organization,
                actor=command.actor,
                object_type="EmailProjectLink",
                object_id=str(original_link.id),
                metadata={
                    "email_message_id": original_link.email_message_id,
                    "old_project_id": original_link.project_id,
                    "new_project_id": command.new_project.id,
                    "confirmed_link_id": confirmed_link.id,
                    "reason": command.reason,
                    "evidence": original_link.evidence,
                    "decision_metadata": metadata,
                },
            )

            return confirmed_link
