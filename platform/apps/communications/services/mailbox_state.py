from copy import deepcopy

from django.db import transaction
from django.utils import timezone

from apps.core.services import AuditService

from ..models import EmailMailboxState
from .commands import (
    GetOrCreateMailboxStateCommand,
    MarkMailboxSyncCompletedCommand,
    MarkMailboxSyncFailedCommand,
    MarkMailboxSyncStartedCommand,
    UpdateMailboxSyncProgressCommand,
)


class MailboxUIDValidityChangedError(ValueError):
    """Raised when observed UIDVALIDITY differs from the stored cursor state.

    IMAP UIDVALIDITY changes mean stored UID cursors may no longer be
    trustworthy. This service deliberately does not reset cursors or re-import
    messages automatically.
    """


class EmailMailboxStateService:
    """Persistence service for mailbox-level sync cursors and progress.

    This service performs no network work. Connectors discover provider state,
    EmailSyncService remains the sync orchestrator, and this service only
    persists local mailbox state.
    """

    @staticmethod
    def get_or_create(command: GetOrCreateMailboxStateCommand):
        metadata = deepcopy(command.metadata or {})
        email_account = command.email_account

        with transaction.atomic():
            mailbox_state, created = EmailMailboxState.objects.get_or_create(
                email_account=email_account,
                mailbox_name=command.mailbox_name,
                defaults={
                    "organization": email_account.organization,
                    "external_mailbox_id": command.external_mailbox_id,
                    "uid_validity": command.uid_validity,
                    "metadata": metadata,
                },
            )

            if not created and mailbox_state.organization_id != email_account.organization_id:
                raise ValueError("EmailMailboxState organization must match EmailAccount organization.")

            if not created and command.uid_validity is not None:
                EmailMailboxStateService._validate_uid_validity(mailbox_state, command.uid_validity)
                if mailbox_state.uid_validity is None:
                    mailbox_state.uid_validity = command.uid_validity
                    mailbox_state.save(update_fields=["uid_validity", "updated_at"])

            if not created and command.external_mailbox_id and not mailbox_state.external_mailbox_id:
                mailbox_state.external_mailbox_id = command.external_mailbox_id
                mailbox_state.save(update_fields=["external_mailbox_id", "updated_at"])

            return mailbox_state

    @staticmethod
    def mark_started(command: MarkMailboxSyncStartedCommand):
        metadata = deepcopy(command.metadata or {})
        now = timezone.now()

        with transaction.atomic():
            mailbox_state = command.mailbox_state
            mailbox_state.sync_status = EmailMailboxState.SyncStatus.RUNNING
            mailbox_state.last_sync_started_at = now
            mailbox_state.last_progress_at = now
            mailbox_state.last_error = ""
            if command.initial_import:
                mailbox_state.initial_import_status = EmailMailboxState.InitialImportStatus.RUNNING
            mailbox_state.save()

            EmailMailboxStateService._audit(
                mailbox_state,
                "email.mailbox_sync_started",
                "Email mailbox sync started.",
                metadata,
            )
            return mailbox_state

    @staticmethod
    def update_progress(command: UpdateMailboxSyncProgressCommand):
        metadata = deepcopy(command.metadata or {})
        cursor_metadata = deepcopy(command.cursor_metadata or {})
        EmailMailboxStateService._validate_increments(command)

        with transaction.atomic():
            mailbox_state = command.mailbox_state

            for field in ["last_discovered_uid", "last_processed_uid", "highest_modseq"]:
                value = getattr(command, field)
                if value is not None:
                    setattr(mailbox_state, field, value)

            mailbox_state.discovered_count += command.discovered_increment
            mailbox_state.imported_count += command.imported_increment
            mailbox_state.processed_count += command.processed_increment
            mailbox_state.skipped_count += command.skipped_increment
            mailbox_state.failed_count += command.failed_increment
            mailbox_state.last_progress_at = timezone.now()

            if cursor_metadata:
                existing_cursor_metadata = dict(mailbox_state.cursor_metadata or {})
                existing_cursor_metadata.update(cursor_metadata)
                mailbox_state.cursor_metadata = existing_cursor_metadata
            if metadata:
                existing_metadata = dict(mailbox_state.metadata or {})
                existing_metadata.update(metadata)
                mailbox_state.metadata = existing_metadata

            mailbox_state.save()
            return mailbox_state

    @staticmethod
    def mark_completed(command: MarkMailboxSyncCompletedCommand):
        metadata = deepcopy(command.metadata or {})
        now = timezone.now()

        with transaction.atomic():
            mailbox_state = command.mailbox_state
            mailbox_state.sync_status = EmailMailboxState.SyncStatus.IDLE
            mailbox_state.last_sync_completed_at = now
            mailbox_state.last_successful_sync_at = now
            mailbox_state.last_progress_at = now
            mailbox_state.last_error = ""
            if command.initial_import:
                mailbox_state.initial_import_status = EmailMailboxState.InitialImportStatus.COMPLETED
            mailbox_state.save()

            EmailMailboxStateService._audit(
                mailbox_state,
                "email.mailbox_sync_completed",
                "Email mailbox sync completed.",
                metadata,
            )
            return mailbox_state

    @staticmethod
    def mark_failed(command: MarkMailboxSyncFailedCommand):
        metadata = deepcopy(command.metadata or {})
        now = timezone.now()

        with transaction.atomic():
            mailbox_state = command.mailbox_state
            mailbox_state.sync_status = EmailMailboxState.SyncStatus.FAILED
            mailbox_state.last_error = command.safe_error
            mailbox_state.last_sync_completed_at = now
            mailbox_state.last_progress_at = now
            if command.initial_import:
                mailbox_state.initial_import_status = EmailMailboxState.InitialImportStatus.FAILED
            mailbox_state.save()

            EmailMailboxStateService._audit(
                mailbox_state,
                "email.mailbox_sync_failed",
                "Email mailbox sync failed.",
                metadata,
            )
            return mailbox_state

    @staticmethod
    def pause(mailbox_state, actor=None, metadata=None):
        event_metadata = deepcopy(metadata or {})

        with transaction.atomic():
            mailbox_state.sync_status = EmailMailboxState.SyncStatus.PAUSED
            if mailbox_state.initial_import_status == EmailMailboxState.InitialImportStatus.RUNNING:
                mailbox_state.initial_import_status = EmailMailboxState.InitialImportStatus.PAUSED
            mailbox_state.last_progress_at = timezone.now()
            mailbox_state.save()

            EmailMailboxStateService._audit(
                mailbox_state,
                "email.mailbox_sync_paused",
                "Email mailbox sync paused.",
                event_metadata,
                actor=actor,
            )
            return mailbox_state

    @staticmethod
    def _validate_uid_validity(mailbox_state, observed_uid_validity):
        if mailbox_state.uid_validity in {None, observed_uid_validity}:
            return

        # Do not silently overwrite UID cursors when UIDVALIDITY changes.
        observed = dict(mailbox_state.cursor_metadata or {})
        observed["observed_uid_validity"] = observed_uid_validity
        observed["stored_uid_validity"] = mailbox_state.uid_validity
        mailbox_state.cursor_metadata = observed
        mailbox_state.save(update_fields=["cursor_metadata", "updated_at"])
        raise MailboxUIDValidityChangedError(
            "Mailbox UIDVALIDITY changed; stored UID cursors require explicit recovery."
        )

    @staticmethod
    def _validate_increments(command):
        increments = [
            command.discovered_increment,
            command.imported_increment,
            command.processed_increment,
            command.skipped_increment,
            command.failed_increment,
        ]
        if any(value < 0 for value in increments):
            raise ValueError("Mailbox sync progress increments cannot be negative.")

    @staticmethod
    def _audit(mailbox_state, event_type, message, metadata, actor=None):
        AuditService.record(
            event_type=event_type,
            message=message,
            organization=mailbox_state.organization,
            actor=actor,
            object_type="EmailMailboxState",
            object_id=str(mailbox_state.id),
            metadata={
                **metadata,
                "email_account_id": mailbox_state.email_account_id,
                "mailbox_name": mailbox_state.mailbox_name,
                "sync_status": mailbox_state.sync_status,
                "initial_import_status": mailbox_state.initial_import_status,
            },
        )
