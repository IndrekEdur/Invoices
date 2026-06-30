from django.db import transaction

from apps.core.services import AuditService

from ..models import EmailMessage, EmailThread


class EmailImportService:
    """Persists provider-neutral raw e-mail DTOs as communication records."""

    @staticmethod
    def import_message(email_account, raw_message, actor=None, metadata=None):
        import_metadata = dict(metadata or {})
        raw_metadata = dict(raw_message.metadata or {})

        with transaction.atomic():
            thread = EmailImportService._get_or_create_thread(email_account, raw_message)
            message, created = EmailMessage.objects.update_or_create(
                account=email_account,
                external_message_id=raw_message.external_message_id,
                defaults={
                    "organization": email_account.organization,
                    "thread": thread,
                    "internet_message_id": raw_message.internet_message_id,
                    "subject": raw_message.subject,
                    "body_text": raw_message.body_text,
                    "body_html": raw_message.body_html,
                    "sender_email": raw_message.sender_email,
                    "sender_name": raw_message.sender_name,
                    "recipients": list(raw_message.recipients or []),
                    "cc": list(raw_message.cc or []),
                    "bcc": list(raw_message.bcc or []),
                    "direction": raw_message.direction,
                    "sent_at": raw_message.sent_at,
                    "received_at": raw_message.received_at,
                    "metadata": raw_metadata,
                },
            )

            if thread is not None:
                EmailImportService._refresh_thread_summary(thread)

            AuditService.record(
                event_type="email.message_imported",
                message=f"Email message imported: {message}",
                organization=email_account.organization,
                actor=actor,
                object_type="EmailMessage",
                object_id=str(message.id),
                metadata={
                    "account_id": email_account.id,
                    "external_message_id": raw_message.external_message_id,
                    "external_thread_id": raw_message.external_thread_id,
                    "created": created,
                    "import_metadata": import_metadata,
                },
            )

        return message

    @staticmethod
    def _get_or_create_thread(email_account, raw_message):
        if not raw_message.external_thread_id:
            return None

        thread, _created = EmailThread.objects.get_or_create(
            account=email_account,
            external_thread_id=raw_message.external_thread_id,
            defaults={
                "organization": email_account.organization,
                "subject": raw_message.subject,
                "normalized_subject": raw_message.subject.casefold(),
                "metadata": {},
            },
        )

        if not thread.subject and raw_message.subject:
            thread.subject = raw_message.subject
            thread.normalized_subject = raw_message.subject.casefold()
            thread.save(update_fields=["subject", "normalized_subject", "updated_at"])

        return thread

    @staticmethod
    def _refresh_thread_summary(thread):
        message_count = thread.messages.count()
        latest_at = None

        for message in thread.messages.all():
            message_at = message.received_at or message.sent_at
            if message_at and (latest_at is None or message_at > latest_at):
                latest_at = message_at

        thread.message_count = message_count
        thread.last_message_at = latest_at
        thread.save(update_fields=["message_count", "last_message_at", "updated_at"])
