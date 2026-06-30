from django.db import transaction

from apps.core.services import AuditService

from .commands import DetectEmailQuestionsCommand, SuggestEmailProjectLinksCommand
from .project_suggestions import EmailProjectSuggestionService
from .question_detection import EmailQuestionDetectionService


class EmailProcessingService:
    """Coordinates the first internal processing pipeline for stored e-mails."""

    @staticmethod
    def process(command):
        email_message = command.email_message
        metadata = dict(command.metadata or {})

        with transaction.atomic():
            project_links = EmailProjectSuggestionService.suggest(
                SuggestEmailProjectLinksCommand(
                    email_message=email_message,
                    actor=command.actor,
                    metadata=metadata,
                )
            )
            questions = EmailQuestionDetectionService.detect(
                DetectEmailQuestionsCommand(
                    email_message=email_message,
                    actor=command.actor,
                    metadata=metadata,
                )
            )

            AuditService.record(
                event_type="email.processing_completed",
                message=f"Email processing completed: {email_message}",
                organization=email_message.organization,
                actor=command.actor,
                object_type="EmailMessage",
                object_id=str(email_message.id),
                metadata={
                    "project_link_count": len(project_links),
                    "question_count": len(questions),
                    "processing_metadata": metadata,
                },
            )

            return {
                "email_message": email_message,
                "project_links": project_links,
                "questions": questions,
                "processed": True,
            }
