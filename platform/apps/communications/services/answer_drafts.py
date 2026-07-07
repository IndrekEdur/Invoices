import copy

from django.db import transaction
from django.utils import timezone

from apps.core.services import AuditService

from ..models import EmailAnswerDraft


class EmailAnswerDraftService:
    """Creates stored e-mail answer drafts without generating or sending replies."""

    @staticmethod
    def create_draft(command):
        evidence = copy.deepcopy(command.evidence or {})
        context_snapshot = copy.deepcopy(command.context_snapshot or {})
        metadata = copy.deepcopy(command.metadata or {})

        with transaction.atomic():
            draft = EmailAnswerDraft.objects.create(
                organization=command.email_message.organization,
                email_message=command.email_message,
                question=command.question,
                draft_text=command.draft_text,
                evidence=evidence,
                context_snapshot=context_snapshot,
                generated_by=command.generated_by,
                metadata=metadata,
            )

            AuditService.record(
                event_type="email.answer_draft_created",
                message=f"Email answer draft created: {draft}",
                organization=draft.organization,
                actor=command.actor,
                object_type="EmailAnswerDraft",
                object_id=str(draft.id),
                metadata={
                    "email_message_id": draft.email_message_id,
                    "question_id": draft.question_id,
                    "generated_by": draft.generated_by,
                    "draft_metadata": metadata,
                },
            )

        return draft

    @staticmethod
    def mark_needs_review(command):
        metadata = copy.deepcopy(command.metadata or {})
        draft = command.draft

        with transaction.atomic():
            draft.status = EmailAnswerDraft.Status.NEEDS_REVIEW
            draft.reviewed_by = command.actor
            draft.save(update_fields=["status", "reviewed_by", "updated_at"])
            EmailAnswerDraftService._record_review_event(
                draft=draft,
                event_type="email.answer_draft_needs_review",
                message=f"Email answer draft marked needs review: {draft}",
                actor=command.actor,
                metadata=metadata,
            )

        return draft

    @staticmethod
    def approve(command):
        metadata = copy.deepcopy(command.metadata or {})
        draft = command.draft

        with transaction.atomic():
            draft.status = EmailAnswerDraft.Status.APPROVED
            draft.approved_by = command.actor
            draft.approved_at = timezone.now()
            if command.final_text is not None:
                draft.final_text = command.final_text
            elif not draft.final_text:
                draft.final_text = draft.draft_text
            draft.save(update_fields=["status", "approved_by", "approved_at", "final_text", "updated_at"])
            EmailAnswerDraftService._record_review_event(
                draft=draft,
                event_type="email.answer_draft_approved",
                message=f"Email answer draft approved: {draft}",
                actor=command.actor,
                metadata=metadata,
            )

        return draft

    @staticmethod
    def reject(command):
        metadata = copy.deepcopy(command.metadata or {})
        reason = command.reason
        draft = command.draft

        with transaction.atomic():
            draft.status = EmailAnswerDraft.Status.REJECTED
            draft.reviewed_by = command.actor
            draft.metadata = {**draft.metadata, "rejection_reason": reason}
            draft.save(update_fields=["status", "reviewed_by", "metadata", "updated_at"])
            EmailAnswerDraftService._record_review_event(
                draft=draft,
                event_type="email.answer_draft_rejected",
                message=f"Email answer draft rejected: {draft}",
                actor=command.actor,
                metadata={**metadata, "reason": reason},
            )

        return draft

    @staticmethod
    def _record_review_event(*, draft, event_type, message, actor, metadata):
        AuditService.record(
            event_type=event_type,
            message=message,
            organization=draft.organization,
            actor=actor,
            object_type="EmailAnswerDraft",
            object_id=str(draft.id),
            metadata={
                "email_message_id": draft.email_message_id,
                "question_id": draft.question_id,
                "status": draft.status,
                "review_metadata": metadata,
            },
        )
