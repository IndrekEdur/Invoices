from django.db import transaction

from apps.core.services import AuditService

from ..connectors import IMAPEmailConnector
from ..models import EmailAccount
from .imports import EmailImportService
from .processing import EmailProcessingService
from .commands import ProcessEmailCommand


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

        raw_messages = []
        try:
            connector.connect()
            raw_messages = connector.fetch_messages(limit=command.limit)
        finally:
            connector.disconnect()

        imported_messages = [
            EmailImportService.import_message(
                email_account,
                raw_message,
                actor=command.actor,
                metadata=metadata,
            )
            for raw_message in raw_messages
        ]
        processing_results = []

        if command.process_imported:
            processing_results = [
                EmailProcessingService.process(
                    ProcessEmailCommand(
                        email_message=message,
                        actor=command.actor,
                        metadata=metadata,
                    )
                )
                for message in imported_messages
            ]

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
                    "fetched_count": len(raw_messages),
                    "imported_count": len(imported_messages),
                    "processed_count": len(processing_results),
                    "sync_metadata": metadata,
                },
            )

        return {
            "email_account": email_account,
            "fetched_count": len(raw_messages),
            "imported_count": len(imported_messages),
            "raw_messages": raw_messages,
            "imported_messages": imported_messages,
            "processed_count": len(processing_results),
            "processing_results": processing_results,
            "synced": True,
        }

    @staticmethod
    def _connector_for(email_account):
        if email_account.provider == EmailAccount.Provider.IMAP:
            return IMAPEmailConnector(email_account)

        raise ValueError(f"Unsupported email provider: {email_account.provider}")
