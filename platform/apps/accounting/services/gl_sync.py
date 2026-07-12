from copy import deepcopy
from datetime import date, datetime, timedelta

from apps.accounting.connectors import MeritAPIClient
from apps.accounting.dto import MeritGLDateType
from apps.accounting.models import AccountingIntegration, AccountingSyncRun, AccountingSyncState

from .commands import (
    CompleteAccountingSyncRunCommand,
    FailAccountingSyncRunCommand,
    GetOrCreateAccountingSyncStateCommand,
    StartAccountingSyncRunCommand,
    SyncGeneralLedgerCommand,
    SyncGeneralLedgerResult,
    UpdateAccountingSyncProgressCommand,
)
from .general_ledger import GeneralLedgerCacheService
from .sync_state import AccountingSyncStateService


class GeneralLedgerSyncService:
    """Synchronize bounded Merit GL periods into the normalized GL cache.

    Counter semantics for sync state/run are object-level cache counts:
    discovered_count is provider GL batches returned; created/updated/
    unchanged_count are normalized cache objects across batches, entries and
    allocations. failed_count is failed batch or chunk count.
    """

    def __init__(self, api_client_factory=None, sync_state_service=None, cache_service=None):
        self.api_client_factory = api_client_factory or MeritAPIClient
        self.sync_state_service = sync_state_service or AccountingSyncStateService
        self.cache_service = cache_service or GeneralLedgerCacheService

    def sync(self, command: SyncGeneralLedgerCommand) -> SyncGeneralLedgerResult:
        metadata = deepcopy(command.metadata or {})
        period_start = self._coerce_date(command.period_start, "period_start")
        period_end = self._coerce_date(command.period_end, "period_end")
        self._validate_command(command, period_start, period_end)
        chunks = self.split_period(period_start, period_end)

        sync_state = self.sync_state_service.get_or_create(
            GetOrCreateAccountingSyncStateCommand(
                integration=command.integration,
                source_type=AccountingSyncState.SourceType.GL,
                cursor_type=AccountingSyncState.CursorType.PERIOD,
                metadata=metadata,
            )
        )
        sync_run = self.sync_state_service.start_run(
            StartAccountingSyncRunCommand(
                sync_state=sync_state,
                mode=command.mode,
                requested_period_start=period_start,
                requested_period_end=period_end,
                initial_import=command.initial_import,
                metadata=metadata,
            )
        )

        client = self.api_client_factory(command.integration)
        totals = {
            "completed_chunk_count": 0,
            "discovered_batch_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "unchanged_count": 0,
            "failed_count": 0,
        }
        persisted_batches = []

        try:
            for chunk_start, chunk_end in chunks:
                # Network call intentionally happens before cache persistence.
                batch_dtos = client.get_gl_batches_full(
                    chunk_start,
                    chunk_end,
                    with_lines=command.with_lines,
                    with_cost_allocations=command.with_cost_allocations,
                    date_type=command.date_type,
                )
                batch_dtos = self._sort_batches(batch_dtos)
                totals["discovered_batch_count"] += len(batch_dtos)
                self.sync_state_service.update_progress(
                    UpdateAccountingSyncProgressCommand(
                        sync_state=sync_state,
                        sync_run=sync_run,
                        discovered_increment=len(batch_dtos),
                        metadata=metadata,
                    )
                )

                for batch_dto in batch_dtos:
                    try:
                        batch_result = self.cache_service.persist_batch_tree(
                            command.integration,
                            batch_dto,
                            sync_run=sync_run,
                            metadata=metadata,
                        )
                    except Exception:
                        totals["failed_count"] += 1
                        self.sync_state_service.update_progress(
                            UpdateAccountingSyncProgressCommand(
                                sync_state=sync_state,
                                sync_run=sync_run,
                                failed_increment=1,
                                metadata=metadata,
                            )
                        )
                        raise

                    persisted_batches.append(batch_result["batch_result"].object)
                    totals["created_count"] += batch_result["created_count"]
                    totals["updated_count"] += batch_result["updated_count"]
                    totals["unchanged_count"] += batch_result["unchanged_count"]
                    self.sync_state_service.update_progress(
                        UpdateAccountingSyncProgressCommand(
                            sync_state=sync_state,
                            sync_run=sync_run,
                            created_increment=batch_result["created_count"],
                            updated_increment=batch_result["updated_count"],
                            unchanged_increment=batch_result["unchanged_count"],
                            metadata=metadata,
                        )
                    )

                totals["completed_chunk_count"] += 1
                progress_start = None if command.mode == AccountingSyncRun.Mode.PERIOD_RESYNC else period_start
                progress_end = None if command.mode == AccountingSyncRun.Mode.PERIOD_RESYNC else chunk_end
                progress_cursor = None if command.mode == AccountingSyncRun.Mode.PERIOD_RESYNC else chunk_end.isoformat()
                self.sync_state_service.update_progress(
                    UpdateAccountingSyncProgressCommand(
                        sync_state=sync_state,
                        sync_run=sync_run,
                        completed_period_start=progress_start,
                        completed_period_end=progress_end,
                        cursor_value=progress_cursor,
                        cursor_metadata={
                            "last_completed_gl_chunk_start": chunk_start.isoformat(),
                            "last_completed_gl_chunk_end": chunk_end.isoformat(),
                            "date_type": command.date_type,
                        },
                        metadata=metadata,
                    )
                )

            complete_start = None if command.mode == AccountingSyncRun.Mode.PERIOD_RESYNC else period_start
            complete_end = None if command.mode == AccountingSyncRun.Mode.PERIOD_RESYNC else period_end
            complete_cursor = None if command.mode == AccountingSyncRun.Mode.PERIOD_RESYNC else period_end.isoformat()
            sync_run = self.sync_state_service.complete_run(
                CompleteAccountingSyncRunCommand(
                    sync_state=sync_state,
                    sync_run=sync_run,
                    cursor_value=complete_cursor,
                    completed_period_start=complete_start,
                    completed_period_end=complete_end,
                    initial_import=command.initial_import,
                    metadata=metadata,
                )
            )
            sync_state.refresh_from_db()
            return SyncGeneralLedgerResult(
                integration=command.integration,
                sync_state=sync_state,
                sync_run=sync_run,
                period_start=period_start,
                period_end=period_end,
                requested_chunk_count=len(chunks),
                completed_chunk_count=totals["completed_chunk_count"],
                discovered_batch_count=totals["discovered_batch_count"],
                created_count=totals["created_count"],
                updated_count=totals["updated_count"],
                unchanged_count=totals["unchanged_count"],
                failed_count=0,
                batches=persisted_batches,
                partial=False,
                synced=True,
                metadata=metadata,
            )
        except Exception as exc:
            partial = bool(totals["completed_chunk_count"] or persisted_batches)
            sync_run = self.sync_state_service.fail_run(
                FailAccountingSyncRunCommand(
                    sync_state=sync_state,
                    sync_run=sync_run,
                    safe_error=str(exc),
                    partial=partial,
                    initial_import=command.initial_import,
                    metadata=metadata,
                )
            )
            raise

    @staticmethod
    def split_period(period_start, period_end):
        start = GeneralLedgerSyncService._coerce_date(period_start, "period_start")
        end = GeneralLedgerSyncService._coerce_date(period_end, "period_end")
        if end < start:
            raise ValueError("GL sync period_end cannot be before period_start.")

        chunks = []
        current = start
        while current <= end:
            chunk_end = min(current + timedelta(days=30), end)
            chunks.append((current, chunk_end))
            current = chunk_end + timedelta(days=1)
        return chunks

    @staticmethod
    def _validate_command(command, period_start, period_end):
        integration = command.integration
        if not integration.is_active:
            raise ValueError("GL sync requires an active accounting integration.")
        if integration.provider != AccountingIntegration.Provider.MERIT:
            raise ValueError("GL sync currently supports only Merit integrations.")
        if period_end < period_start:
            raise ValueError("GL sync period_end cannot be before period_start.")
        valid_modes = {choice.value for choice in AccountingSyncRun.Mode}
        if command.mode not in valid_modes:
            raise ValueError(f"Unsupported GL sync mode: {command.mode}")
        if command.date_type not in MeritGLDateType.MERIT_VALUES:
            raise ValueError(f"Unsupported GL sync date_type: {command.date_type}")

    @staticmethod
    def _sort_batches(batch_dtos):
        return sorted(
            batch_dtos,
            key=lambda batch: (
                batch.batch_date or date.min,
                str(batch.external_id or ""),
            ),
        )

    @staticmethod
    def _coerce_date(value, field_name):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value.strip()[:10])
            except ValueError as exc:
                raise ValueError(f"{field_name} must be a date or ISO date string.") from exc
        raise ValueError(f"{field_name} must be a date or ISO date string.")
