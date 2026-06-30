from django.db import transaction

from apps.core.services import AuditService

from ..connectors import IMAPEmailConnector
from ..models import EmailAccount


class EmailSyncService:
    """Coordinates provider-specific e-mail sync connectors."""

    @staticmethod
    def sync(command):
        email_account = command.email_account
        metadata = dict(command.metadata or {})
        connector = EmailSyncService._connector_for(email_account)

        with transaction.atomic():
            AuditService.record(
                event_type="email.sync_started",
                message=f"Email sync started: {email_account}",
                organization=email_account.organization,
                actor=command.actor,
                object_type="EmailAccount",
                object_id=str(email_account.id),
                metadata={
                    "provider": email_account.provider,
                    "limit": command.limit,
                    "sync_metadata": metadata,
                },
            )

        messages = []
        try:
            connector.connect()
            messages = connector.fetch_messages(limit=command.limit)
        finally:
            connector.disconnect()

        with transaction.atomic():
            AuditService.record(
                event_type="email.sync_completed",
                message=f"Email sync completed: {email_account}",
                organization=email_account.organization,
                actor=command.actor,
                object_type="EmailAccount",
                object_id=str(email_account.id),
                metadata={
                    "provider": email_account.provider,
                    "limit": command.limit,
                    "fetched_count": len(messages),
                    "sync_metadata": metadata,
                },
            )

        return {
            "email_account": email_account,
            "fetched_count": len(messages),
            "messages": messages,
            "synced": True,
        }

    @staticmethod
    def _connector_for(email_account):
        if email_account.provider == EmailAccount.Provider.IMAP:
            return IMAPEmailConnector(email_account)

        raise ValueError(f"Unsupported email provider: {email_account.provider}")
