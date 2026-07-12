from django.db import transaction

from apps.core.services import AuditService

from ..connectors import IMAPEmailConnector
from ..models import EmailAccount, EmailMailboxState
from .imports import EmailImportService
from .mailbox_state import EmailMailboxStateService, MailboxUIDValidityChangedError
from .processing import EmailProcessingService
from .commands import (
    GetOrCreateMailboxStateCommand,
    MarkMailboxSyncCompletedCommand,
    MarkMailboxSyncFailedCommand,
    MarkMailboxSyncStartedCommand,
    ProcessEmailCommand,
    UpdateMailboxSyncProgressCommand,
)


class EmailSyncService:
    """Coordinates provider-specific e-mail sync connectors."""

    @staticmethod
    def sync(command):
        email_account = command.email_account
        metadata = dict(command.metadata or {})
        connector = EmailSyncService._connector_for(email_account)

        EmailSyncService._audit_sync_started(command, metadata)

        if email_account.provider == EmailAccount.Provider.IMAP and command.incremental:
            return EmailSyncService._sync_incremental_imap(command, connector, metadata)

        return EmailSyncService._sync_bounded_latest(command, connector, metadata)

    @staticmethod
    def _sync_bounded_latest(command, connector, metadata):
        email_account = command.email_account
        raw_messages = []
        try:
            connector.connect()
            raw_messages = connector.fetch_messages(
                limit=command.limit,
                mailbox=command.mailbox_name,
                after_uid=None,
            )
        finally:
            connector.disconnect()

        imported_messages, processing_results = EmailSyncService._import_and_process_batch(
            command,
            raw_messages,
            metadata,
        )
        EmailSyncService._audit_sync_completed(command, metadata, raw_messages, imported_messages, processing_results)

        return EmailSyncService._result(
            command,
            raw_messages,
            imported_messages,
            processing_results,
            mailbox_state=None,
            uid_validity=None,
            cursor_before=None,
            cursor_after=None,
            incremental=False,
        )

    @staticmethod
    def _sync_incremental_imap(command, connector, metadata):
        email_account = command.email_account
        mailbox_state = None
        raw_messages = []
        imported_messages = []
        processing_results = []
        cursor_before = None
        uid_validity = None

        try:
            connector.connect()
            snapshot = connector.get_mailbox_snapshot(command.mailbox_name)
            uid_validity = EmailSyncService._optional_int(getattr(snapshot, "uid_validity", None))
            try:
                mailbox_state = EmailMailboxStateService.get_or_create(
                    GetOrCreateMailboxStateCommand(
                        email_account=email_account,
                        mailbox_name=command.mailbox_name,
                        uid_validity=uid_validity,
                        metadata=metadata,
                    )
                )
            except MailboxUIDValidityChangedError:
                mailbox_state = EmailMailboxState.objects.filter(
                    email_account=email_account,
                    mailbox_name=command.mailbox_name,
                ).first()
                if mailbox_state is not None:
                    EmailMailboxStateService.mark_failed(
                        MarkMailboxSyncFailedCommand(
                            mailbox_state=mailbox_state,
                            safe_error="Mailbox UIDVALIDITY changed; stored cursor requires manual recovery.",
                            metadata={
                                "observed_uid_validity": uid_validity,
                                "sync_metadata": metadata,
                            },
                        )
                    )
                raise

            EmailMailboxStateService.mark_started(
                MarkMailboxSyncStartedCommand(
                    mailbox_state=mailbox_state,
                    metadata={"sync_metadata": metadata},
                )
            )

            cursor_before = mailbox_state.last_processed_uid
            try:
                raw_messages = connector.fetch_messages(
                    limit=command.limit,
                    mailbox=command.mailbox_name,
                    after_uid=cursor_before,
                )
            except Exception as exc:
                EmailMailboxStateService.mark_failed(
                    MarkMailboxSyncFailedCommand(
                        mailbox_state=mailbox_state,
                        safe_error=EmailSyncService._safe_error(exc),
                        metadata={"sync_metadata": metadata},
                    )
                )
                raise

            batch_uids = [uid for uid in (EmailSyncService._message_uid(message) for message in raw_messages) if uid]
            if batch_uids:
                EmailMailboxStateService.update_progress(
                    UpdateMailboxSyncProgressCommand(
                        mailbox_state=mailbox_state,
                        last_discovered_uid=max(batch_uids),
                        discovered_increment=len(batch_uids),
                        cursor_metadata={
                            "snapshot_highest_uid": EmailSyncService._optional_int(
                                getattr(snapshot, "highest_uid", None)
                            ),
                            "snapshot_message_count": EmailSyncService._optional_int(
                                getattr(snapshot, "message_count", None)
                            ),
                            "uid_validity": uid_validity,
                        },
                        metadata={"sync_metadata": metadata},
                    )
                )

            for raw_message in raw_messages:
                uid = EmailSyncService._message_uid(raw_message)
                try:
                    imported_message = EmailImportService.import_message(
                        email_account,
                        raw_message,
                        actor=command.actor,
                        metadata=metadata,
                    )
                    processing_result = None
                    if command.process_imported:
                        processing_result = EmailProcessingService.process(
                            ProcessEmailCommand(
                                email_message=imported_message,
                                actor=command.actor,
                                metadata=metadata,
                            )
                        )
                    imported_messages.append(imported_message)
                    if command.process_imported:
                        processing_results.append(processing_result)

                    EmailMailboxStateService.update_progress(
                        UpdateMailboxSyncProgressCommand(
                            mailbox_state=mailbox_state,
                            last_processed_uid=uid,
                            imported_increment=1,
                            processed_increment=1 if command.process_imported else 0,
                            metadata={"sync_metadata": metadata},
                        )
                    )
                except Exception as exc:
                    EmailMailboxStateService.mark_failed(
                        MarkMailboxSyncFailedCommand(
                            mailbox_state=mailbox_state,
                            safe_error=EmailSyncService._safe_error(exc),
                            metadata={
                                "failed_uid": uid,
                                "sync_metadata": metadata,
                            },
                        )
                    )
                    raise

            EmailMailboxStateService.mark_completed(
                MarkMailboxSyncCompletedCommand(
                    mailbox_state=mailbox_state,
                    metadata={"sync_metadata": metadata},
                )
            )
        finally:
            connector.disconnect()

        mailbox_state.refresh_from_db()
        EmailSyncService._audit_sync_completed(command, metadata, raw_messages, imported_messages, processing_results)
        return EmailSyncService._result(
            command,
            raw_messages,
            imported_messages,
            processing_results,
            mailbox_state=mailbox_state,
            uid_validity=uid_validity,
            cursor_before=cursor_before,
            cursor_after=mailbox_state.last_processed_uid,
            incremental=True,
        )

    @staticmethod
    def _import_and_process_batch(command, raw_messages, metadata):
        imported_messages = []
        processing_results = []
        for raw_message in raw_messages:
            imported_message = EmailImportService.import_message(
                command.email_account,
                raw_message,
                actor=command.actor,
                metadata=metadata,
            )
            imported_messages.append(imported_message)
            if command.process_imported:
                processing_results.append(
                    EmailProcessingService.process(
                        ProcessEmailCommand(
                            email_message=imported_message,
                            actor=command.actor,
                            metadata=metadata,
                        )
                    )
                )
        return imported_messages, processing_results

    @staticmethod
    def _audit_sync_started(command, metadata):
        email_account = command.email_account
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
                    "mailbox_name": command.mailbox_name,
                    "incremental": command.incremental,
                    "sync_metadata": metadata,
                },
            )

    @staticmethod
    def _audit_sync_completed(command, metadata, raw_messages, imported_messages, processing_results):
        email_account = command.email_account
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
                    "mailbox_name": command.mailbox_name,
                    "incremental": command.incremental,
                    "fetched_count": len(raw_messages),
                    "imported_count": len(imported_messages),
                    "processed_count": len(processing_results),
                    "sync_metadata": metadata,
                },
            )

    @staticmethod
    def _result(
        command,
        raw_messages,
        imported_messages,
        processing_results,
        *,
        mailbox_state,
        uid_validity,
        cursor_before,
        cursor_after,
        incremental,
    ):
        return {
            "email_account": command.email_account,
            "fetched_count": len(raw_messages),
            "imported_count": len(imported_messages),
            "raw_messages": raw_messages,
            "imported_messages": imported_messages,
            "processed_count": len(processing_results),
            "processing_results": processing_results,
            "synced": True,
            "mailbox_state": mailbox_state,
            "mailbox_name": command.mailbox_name,
            "uid_validity": uid_validity,
            "cursor_before": cursor_before,
            "cursor_after": cursor_after,
            "incremental": incremental,
        }

    @staticmethod
    def _message_uid(raw_message):
        metadata = dict(raw_message.metadata or {})
        uid = metadata.get("imap_uid")
        if uid is None:
            external_message_id = str(raw_message.external_message_id or "")
            if external_message_id.isdigit():
                uid = external_message_id
            elif external_message_id.rsplit(":", 1)[-1].isdigit():
                uid = external_message_id.rsplit(":", 1)[-1]

        return int(uid) if uid is not None else None

    @staticmethod
    def _optional_int(value):
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_error(exc):
        return f"Email sync failed while processing mailbox message: {exc.__class__.__name__}"

    @staticmethod
    def _connector_for(email_account):
        if email_account.provider == EmailAccount.Provider.IMAP:
            return IMAPEmailConnector(email_account)

        raise ValueError(f"Unsupported email provider: {email_account.provider}")
