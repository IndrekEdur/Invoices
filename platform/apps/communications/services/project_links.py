from apps.core.services import AuditService

from . import project_linking
from .commands import (
    ConfirmCommunicationProjectLinkCommand,
    CorrectCommunicationProjectLinkCommand,
    RejectCommunicationProjectLinkCommand,
)
from ..models import EmailProjectLink
from .project_linking import CommunicationProjectLinkReviewService


class EmailProjectLinkService:
    """Backwards-compatible service for human e-mail Project decisions."""

    @staticmethod
    def confirm(command):
        project_linking.AuditService = AuditService
        return CommunicationProjectLinkReviewService.confirm(
            ConfirmCommunicationProjectLinkCommand(
                link=command.link,
                make_primary=True,
                actor=command.actor,
                metadata=command.metadata,
            )
        )

    @staticmethod
    def reject(command):
        project_linking.AuditService = AuditService
        return CommunicationProjectLinkReviewService.reject(
            RejectCommunicationProjectLinkCommand(
                link=command.link,
                reason=command.reason,
                actor=command.actor,
                metadata=command.metadata,
            )
        )

    @staticmethod
    def correct(command):
        project_linking.AuditService = AuditService
        confirmed_link = CommunicationProjectLinkReviewService.correct(
            CorrectCommunicationProjectLinkCommand(
                email_message=command.link.email_message,
                project=command.new_project,
                actor=command.actor,
                reason=command.reason,
                make_primary=True,
                metadata=command.metadata,
            )
        )
        if command.link.id != confirmed_link.id:
            original_metadata = dict(command.link.metadata or {})
            if command.reason:
                original_metadata["correction_reason"] = command.reason
            command.link.status = EmailProjectLink.Status.CORRECTED
            command.link.is_primary = False
            command.link.metadata = original_metadata
            command.link.save(update_fields=["status", "is_primary", "metadata", "updated_at"])
        return confirmed_link
