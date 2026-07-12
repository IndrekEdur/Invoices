from dataclasses import dataclass, field


@dataclass(frozen=True)
class SuggestNextProjectCodeCommand:
    organization: object
    prefix: str = ""
    min_code: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class ProjectCodeSuggestion:
    suggested_code: str
    used_codes: list[str]
    source_summary: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SyncAccountingDimensionsCommand:
    integration: object
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class SyncAccountingDimensionsResult:
    integration: object
    created_count: int
    updated_count: int
    unchanged_count: int
    archived_count: int
    conflict_count: int
    dimensions: list
    conflicts: list[dict]
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CreateAccountingDimensionValueCommand:
    integration: object
    code: str
    name: str
    dimension_type: str = "project"
    dimension_id: object = None
    external_id: object = None
    end_date: object = None
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class CreateAccountingDimensionValueResult:
    dimension: object
    dto: object
    created: bool
    updated: bool
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ResolveDimensionConflictCommand:
    organization: object
    conflict: dict
    resolution_type: str
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class IgnoreDimensionConflictCommand:
    organization: object
    conflict: dict
    reason: str = ""
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class DimensionConflictResolutionResult:
    resolution_type: str
    affected_dimension: object
    resolved: bool
    message: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GetOrCreateAccountingSyncStateCommand:
    integration: object
    source_type: str
    cursor_type: str = "none"
    metadata: dict | None = None


@dataclass(frozen=True)
class StartAccountingSyncRunCommand:
    sync_state: object
    mode: str = "incremental"
    requested_period_start: object = None
    requested_period_end: object = None
    initial_import: bool = False
    metadata: dict | None = None


@dataclass(frozen=True)
class UpdateAccountingSyncProgressCommand:
    sync_state: object
    sync_run: object
    cursor_value: object = None
    cursor_datetime: object = None
    completed_period_start: object = None
    completed_period_end: object = None
    discovered_increment: int = 0
    created_increment: int = 0
    updated_increment: int = 0
    unchanged_increment: int = 0
    skipped_increment: int = 0
    failed_increment: int = 0
    cursor_metadata: dict | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class CompleteAccountingSyncRunCommand:
    sync_state: object
    sync_run: object
    cursor_value: object = None
    cursor_datetime: object = None
    completed_period_start: object = None
    completed_period_end: object = None
    initial_import: bool = False
    metadata: dict | None = None


@dataclass(frozen=True)
class FailAccountingSyncRunCommand:
    sync_state: object
    sync_run: object
    safe_error: str
    partial: bool = False
    initial_import: bool = False
    metadata: dict | None = None


@dataclass(frozen=True)
class UpsertGLBatchCommand:
    integration: object
    dto: object
    sync_run: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class UpsertGLEntryCommand:
    batch: object
    dto: object
    sequence: int | None = None
    sync_run: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class UpsertGLAllocationCommand:
    entry: object
    dto: object
    sequence: int | None = None
    sync_run: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class GLCacheUpsertResult:
    object: object
    created: bool
    updated: bool
    unchanged: bool
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SyncGeneralLedgerCommand:
    integration: object
    period_start: object
    period_end: object
    mode: str = "manual"
    date_type: str = "document_date"
    with_lines: bool = True
    with_cost_allocations: bool = True
    initial_import: bool = False
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class SyncGeneralLedgerResult:
    integration: object
    sync_state: object
    sync_run: object
    period_start: object
    period_end: object
    requested_chunk_count: int
    completed_chunk_count: int
    discovered_batch_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    failed_count: int
    batches: list
    partial: bool
    synced: bool
    metadata: dict = field(default_factory=dict)
