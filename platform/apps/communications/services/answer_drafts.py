import copy

from django.db import transaction

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
