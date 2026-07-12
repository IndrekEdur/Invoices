from copy import deepcopy

from django.db import transaction
from django.utils import timezone

from apps.accounting.models import AccountingSyncRun, AccountingSyncState
from apps.core.services import AuditService

from .commands import (
    CompleteAccountingSyncRunCommand,
    FailAccountingSyncRunCommand,
    GetOrCreateAccountingSyncStateCommand,
    StartAccountingSyncRunCommand,
    UpdateAccountingSyncProgressCommand,
)


class AccountingSyncStateService:
    """Persist accounting sync cursors and run progress.

    This service performs local state mutations only. Future Merit/network calls
    must remain outside these transactions, and cursors should advance only
    after source records have been persisted successfully.
    """

    COUNTER_FIELDS = (
        "discovered_count",
        "created_count",
        "updated_count",
        "unchanged_count",
        "skipped_count",
        "failed_count",
    )

    @staticmethod
    def get_or_create(command: GetOrCreateAccountingSyncStateCommand):
        metadata = deepcopy(command.metadata or {})
        integration = command.integration
        AccountingSyncStateService._validate_source_type(command.source_type)
        AccountingSyncStateService._validate_cursor_type(command.cursor_type)

        with transaction.atomic():
            sync_state, created = AccountingSyncState.objects.get_or_create(
                integration=integration,
                source_type=command.source_type,
                defaults={
                    "organization": integration.organization,
                    "cursor_type": command.cursor_type,
                    "metadata": metadata,
                },
            )

            if sync_state.organization_id != integration.organization_id:
                raise ValueError("AccountingSyncState organization must match AccountingIntegration organization.")

            return sync_state

    @staticmethod
    def start_run(command: StartAccountingSyncRunCommand):
        metadata = deepcopy(command.metadata or {})
        sync_state = command.sync_state
        AccountingSyncStateService._validate_state_matches_integration(sync_state)
        AccountingSyncStateService._validate_run_mode(command.mode)
        AccountingSyncStateService._validate_period_pair(command.requested_period_start, command.requested_period_end)
        now = timezone.now()

        with transaction.atomic():
            sync_state.sync_status = AccountingSyncState.SyncStatus.RUNNING
            sync_state.last_sync_started_at = now
            sync_state.last_progress_at = now
            sync_state.last_error = ""
            if command.initial_import:
                sync_state.initial_import_status = AccountingSyncState.InitialImportStatus.RUNNING
            sync_state.save()

            sync_run = AccountingSyncRun.objects.create(
                organization=sync_state.organization,
                integration=sync_state.integration,
                sync_state=sync_state,
                source_type=sync_state.source_type,
                status=AccountingSyncRun.Status.RUNNING,
                mode=command.mode,
                requested_period_start=command.requested_period_start,
                requested_period_end=command.requested_period_end,
                cursor_before=sync_state.cursor_value,
                metadata=metadata,
            )

            AccountingSyncStateService._audit(
                sync_state,
                "accounting.sync_started",
                "Accounting sync started.",
                metadata,
                sync_run=sync_run,
            )
            return sync_run

    @staticmethod
    def update_progress(command: UpdateAccountingSyncProgressCommand):
        metadata = deepcopy(command.metadata or {})
        cursor_metadata = deepcopy(command.cursor_metadata or {})
        AccountingSyncStateService._validate_command_objects(command.sync_state, command.sync_run)
        AccountingSyncStateService._validate_increments(command)
        AccountingSyncStateService._validate_period_pair(command.completed_period_start, command.completed_period_end)

        with transaction.atomic():
            sync_state = command.sync_state
            sync_run = command.sync_run

            AccountingSyncStateService._apply_optional_cursor_fields(sync_state, command)
            AccountingSyncStateService._apply_completed_period(sync_state, sync_run, command)
            AccountingSyncStateService._increment_counts(sync_state, command)
            AccountingSyncStateService._increment_counts(sync_run, command)
            sync_state.last_progress_at = timezone.now()

            if cursor_metadata:
                existing_cursor_metadata = dict(sync_state.cursor_metadata or {})
                existing_cursor_metadata.update(cursor_metadata)
                sync_state.cursor_metadata = existing_cursor_metadata
            if metadata:
                existing_state_metadata = dict(sync_state.metadata or {})
                existing_state_metadata.update(metadata)
                sync_state.metadata = existing_state_metadata
                existing_run_metadata = dict(sync_run.metadata or {})
                existing_run_metadata.update(metadata)
                sync_run.metadata = existing_run_metadata

            sync_state.save()
            sync_run.save()
            return sync_state, sync_run

    @staticmethod
    def complete_run(command: CompleteAccountingSyncRunCommand):
        metadata = deepcopy(command.metadata or {})
        AccountingSyncStateService._validate_command_objects(command.sync_state, command.sync_run)
        AccountingSyncStateService._validate_period_pair(command.completed_period_start, command.completed_period_end)
        now = timezone.now()

        with transaction.atomic():
            sync_state = command.sync_state
            sync_run = command.sync_run
            AccountingSyncStateService._apply_optional_cursor_fields(sync_state, command)
            AccountingSyncStateService._apply_completed_period(sync_state, sync_run, command)

            sync_state.sync_status = AccountingSyncState.SyncStatus.IDLE
            sync_state.last_sync_completed_at = now
            sync_state.last_successful_sync_at = now
            sync_state.last_progress_at = now
            sync_state.last_error = ""
            if command.initial_import:
                sync_state.initial_import_status = AccountingSyncState.InitialImportStatus.COMPLETED
            sync_state.save()

            sync_run.status = AccountingSyncRun.Status.COMPLETED
            sync_run.completed_at = now
            sync_run.cursor_after = sync_state.cursor_value
            if metadata:
                existing_metadata = dict(sync_run.metadata or {})
                existing_metadata.update(metadata)
                sync_run.metadata = existing_metadata
            sync_run.save()

            AccountingSyncStateService._audit(
                sync_state,
                "accounting.sync_completed",
                "Accounting sync completed.",
                metadata,
                sync_run=sync_run,
            )
            return sync_run

    @staticmethod
    def fail_run(command: FailAccountingSyncRunCommand):
        metadata = deepcopy(command.metadata or {})
        AccountingSyncStateService._validate_command_objects(command.sync_state, command.sync_run)
        now = timezone.now()

        with transaction.atomic():
            sync_state = command.sync_state
            sync_run = command.sync_run
            safe_error = AccountingSyncStateService._sanitize_error(sync_state.integration, command.safe_error)

            sync_state.sync_status = AccountingSyncState.SyncStatus.FAILED
            sync_state.last_error = safe_error
            sync_state.last_sync_completed_at = now
            sync_state.last_progress_at = now
            if command.initial_import:
                sync_state.initial_import_status = AccountingSyncState.InitialImportStatus.FAILED
            sync_state.save()

            sync_run.status = AccountingSyncRun.Status.PARTIAL if command.partial else AccountingSyncRun.Status.FAILED
            sync_run.completed_at = now
            sync_run.safe_error = safe_error
            if metadata:
                existing_metadata = dict(sync_run.metadata or {})
                existing_metadata.update(metadata)
                sync_run.metadata = existing_metadata
            sync_run.save()

            AccountingSyncStateService._audit(
                sync_state,
                "accounting.sync_failed",
                "Accounting sync failed.",
                metadata,
                sync_run=sync_run,
            )
            return sync_run

    @staticmethod
    def pause(sync_state, actor=None, metadata=None):
        event_metadata = deepcopy(metadata or {})
        AccountingSyncStateService._validate_state_matches_integration(sync_state)

        with transaction.atomic():
            sync_state.sync_status = AccountingSyncState.SyncStatus.PAUSED
            if sync_state.initial_import_status == AccountingSyncState.InitialImportStatus.RUNNING:
                sync_state.initial_import_status = AccountingSyncState.InitialImportStatus.PAUSED
            sync_state.last_progress_at = timezone.now()
            sync_state.save()

            AccountingSyncStateService._audit(
                sync_state,
                "accounting.sync_paused",
                "Accounting sync paused.",
                event_metadata,
                actor=actor,
            )
            return sync_state

    @staticmethod
    def _validate_source_type(source_type):
        valid_values = {choice.value for choice in AccountingSyncState.SourceType}
        if source_type not in valid_values:
            raise ValueError(f"Unsupported accounting sync source_type: {source_type}")

    @staticmethod
    def _validate_cursor_type(cursor_type):
        valid_values = {choice.value for choice in AccountingSyncState.CursorType}
        if cursor_type not in valid_values:
            raise ValueError(f"Unsupported accounting sync cursor_type: {cursor_type}")

    @staticmethod
    def _validate_run_mode(mode):
        valid_values = {choice.value for choice in AccountingSyncRun.Mode}
        if mode not in valid_values:
            raise ValueError(f"Unsupported accounting sync mode: {mode}")

    @staticmethod
    def _validate_state_matches_integration(sync_state):
        if sync_state.organization_id != sync_state.integration.organization_id:
            raise ValueError("Accounting sync state organization must match integration organization.")

    @staticmethod
    def _validate_command_objects(sync_state, sync_run):
        AccountingSyncStateService._validate_state_matches_integration(sync_state)
        if sync_run.sync_state_id != sync_state.id:
            raise ValueError("Accounting sync run must belong to the provided sync state.")
        if sync_run.integration_id != sync_state.integration_id or sync_run.organization_id != sync_state.organization_id:
            raise ValueError("Accounting sync run organization and integration must match sync state.")

    @staticmethod
    def _validate_period_pair(period_start, period_end):
        if period_start and period_end and period_end < period_start:
            raise ValueError("Accounting sync period end cannot be before period start.")

    @staticmethod
    def _validate_completed_period_does_not_move_backwards(sync_state, sync_run, period_start, period_end):
        if sync_run.mode == AccountingSyncRun.Mode.PERIOD_RESYNC:
            return
        if period_start and sync_state.last_completed_period_start and period_start < sync_state.last_completed_period_start:
            raise ValueError("Accounting completed period start cannot move backwards outside period_resync mode.")
        if period_end and sync_state.last_completed_period_end and period_end < sync_state.last_completed_period_end:
            raise ValueError("Accounting completed period end cannot move backwards outside period_resync mode.")

    @staticmethod
    def _validate_increments(command):
        increments = [
            command.discovered_increment,
            command.created_increment,
            command.updated_increment,
            command.unchanged_increment,
            command.skipped_increment,
            command.failed_increment,
        ]
        if any(value < 0 for value in increments):
            raise ValueError("Accounting sync progress increments cannot be negative.")

    @staticmethod
    def _apply_optional_cursor_fields(sync_state, command):
        if command.cursor_value is not None:
            sync_state.cursor_value = str(command.cursor_value)
        if command.cursor_datetime is not None:
            sync_state.cursor_datetime = command.cursor_datetime

    @staticmethod
    def _apply_completed_period(sync_state, sync_run, command):
        period_start = getattr(command, "completed_period_start", None)
        period_end = getattr(command, "completed_period_end", None)
        AccountingSyncStateService._validate_completed_period_does_not_move_backwards(
            sync_state,
            sync_run,
            period_start,
            period_end,
        )
        if period_start is not None:
            sync_state.last_completed_period_start = period_start
        if period_end is not None:
            sync_state.last_completed_period_end = period_end

    @staticmethod
    def _increment_counts(target, command):
        target.discovered_count += command.discovered_increment
        target.created_count += command.created_increment
        target.updated_count += command.updated_increment
        target.unchanged_count += command.unchanged_increment
        target.skipped_count += command.skipped_increment
        target.failed_count += command.failed_increment

    @staticmethod
    def _sanitize_error(integration, safe_error):
        value = str(safe_error or "")
        for secret_value in [integration.api_id, integration.encrypted_secret_placeholder]:
            if secret_value:
                value = value.replace(secret_value, "[redacted]")
        for marker in ["signature=", "apiId=", "api_id="]:
            if marker in value:
                prefix, _, suffix = value.partition(marker)
                separator = "&" if "&" in suffix else " "
                remainder = suffix.split(separator, 1)
                tail = f"{separator}{remainder[1]}" if len(remainder) > 1 else ""
                value = f"{prefix}{marker}[redacted]{tail}"
        return value

    @staticmethod
    def _audit(sync_state, event_type, message, metadata, actor=None, sync_run=None):
        AuditService.record(
            event_type=event_type,
            message=message,
            organization=sync_state.organization,
            actor=actor,
            object_type="AccountingSyncState",
            object_id=str(sync_state.id),
            metadata={
                **metadata,
                "integration_id": sync_state.integration_id,
                "source_type": sync_state.source_type,
                "sync_status": sync_state.sync_status,
                "initial_import_status": sync_state.initial_import_status,
                "sync_run_id": sync_run.id if sync_run else None,
            },
        )
