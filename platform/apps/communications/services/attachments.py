from django.db import transaction

from apps.core.services import AuditService
from apps.documents.models import Document
from apps.documents.services import DocumentStorageService, StoreDocumentCommand


class EmailAttachmentDocumentService:
    """Converts e-mail attachment records into Document root aggregates."""

    @staticmethod
    def convert(command):
        attachment = command.attachment
        metadata = dict(command.metadata or {})

        with transaction.atomic():
            document = DocumentStorageService.store(
                StoreDocumentCommand(
                    organization=attachment.organization,
                    file=command.file,
                    original_filename=attachment.original_filename,
                    title=attachment.original_filename,
                    source=Document.Source.EMAIL_ATTACHMENT,
                    metadata=metadata,
                    actor=command.actor,
                    workflow=command.workflow,
                )
            )

            attachment.document = document
            attachment.save(update_fields=["document", "updated_at"])

            AuditService.record(
                event_type="email_attachment.converted_to_document",
                message=f"Email attachment converted to document: {attachment.original_filename}",
                organization=attachment.organization,
                actor=command.actor,
                object_type="EmailAttachment",
                object_id=str(attachment.id),
                metadata={
                    "document_uuid": str(document.uuid),
                    "email_message_id": attachment.email_message_id,
                    "original_filename": attachment.original_filename,
                    "conversion_metadata": metadata,
                },
            )

            return document
