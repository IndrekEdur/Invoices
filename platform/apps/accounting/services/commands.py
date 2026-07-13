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
class SaveAccountingAccountClassificationCommand:
    organization: object
    integration: object
    account_code: str
    account_name: str
    category: str
    reporting_sign: object
    include_in_project_result: bool
    is_active: bool
    notes: str = ""
    actor: object = None
    metadata: dict | None = None


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


@dataclass(frozen=True)
class VerifyGeneralLedgerCommand:
    integration: object
    period_start: object
    period_end: object
    sample_size: int = 10
    metadata: dict | None = None


@dataclass(frozen=True)
class GeneralLedgerVerificationResult:
    integration: object
    period_start: object
    period_end: object
    sync_state: object
    sync_run: object
    batch_count: int
    entry_count: int
    allocation_count: int
    linked_project_count: int
    unlinked_allocation_count: int
    distinct_unlinked_codes: list[str]
    total_debit: object
    total_credit: object
    balance_difference: object
    warnings: list[str]
    critical_errors: list[str]
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectFinancialCategoryTotal:
    category: str
    amount: object
    allocation_count: int
    entry_count: int
    source_account_codes: list[str]
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectFinancialMonth:
    year: int
    month: int
    period_start: object
    period_end: object
    revenue: object
    material_cost: object
    subcontractor_cost: object
    labor_cost: object
    equipment_cost: object
    transport_cost: object
    other_direct_cost: object
    overhead: object
    total_cost: object
    result: object
    margin: object
    classified_amount: object
    unclassified_amount: object
    excluded_amount: object
    allocation_count: int
    unclassified_allocation_count: int
    warnings: list[str]
    category_totals: dict
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectFinancialAggregationResult:
    project: object
    period_start: object
    period_end: object
    currency: str
    months: list
    revenue: object
    total_cost: object
    result: object
    margin: object
    classified_amount: object
    unclassified_amount: object
    excluded_amount: object
    allocation_count: int
    unclassified_allocation_count: int
    source_batch_count: int
    source_entry_count: int
    source_sync_run_ids: list[int]
    warnings: list[str]
    data_quality_status: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ManagementAllocationBreakdownItem:
    pool: object
    version: object
    period: object
    amount: object
    percentage_of_total: object
    source_version: str
    approved_at: object
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ManagementFinancialMonth:
    year: int
    month: int
    period_start: object
    period_end: object
    direct_revenue: object
    direct_cost: object
    allocated_management_cost: object
    management_total_cost: object
    accounting_result: object
    management_result: object
    accounting_margin: object
    management_margin: object
    warnings: list[str]
    allocation_breakdown: list
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ManagementFinancialResult:
    project: object
    period_start: object
    period_end: object
    currency: str
    months: list
    direct_revenue: object
    direct_cost: object
    allocated_management_cost: object
    management_total_cost: object
    accounting_result: object
    management_result: object
    accounting_margin: object
    management_margin: object
    allocation_breakdown: list
    warnings: list[str]
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BuildManagementFinancialsCommand:
    accounting_result: object
    metadata: dict | None = None


@dataclass(frozen=True)
class AggregateProjectFinancialsCommand:
    project: object
    period_start: object
    period_end: object
    currency: str | None = None
    include_overhead: bool = True
    metadata: dict | None = None


@dataclass(frozen=True)
class CreateManagementCostPoolCommand:
    organization: object
    name: str
    description: str = ""
    default_strategy: str = "revenue"
    display_order: int = 0
    is_active: bool = True
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class CreateManagementAllocationRuleCommand:
    pool: object
    strategy: str
    is_active: bool = True
    configuration: dict | None = None
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class CreateManagementAllocationVersionCommand:
    period: object
    pool: object
    version_number: int | None = None
    created_by: object = None
    reason: str = ""
    version_metadata: dict | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class ApproveManagementAllocationVersionCommand:
    version: object
    actor: object = None
    reason: str = ""
    metadata: dict | None = None


@dataclass(frozen=True)
class GenerateManagementAllocationProposalCommand:
    pool: object
    year: int
    month: int
    project_ids: list
    strategy: str | None = None
    source_amount: object = None
    project_manager_id: object = None
    manual_percentages: dict | None = None
    manual_amounts: dict | None = None
    reason: str = ""
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class GenerateManagementAllocationProposalResult:
    period: object
    pool: object
    version: object
    entries: list
    strategy: str
    source_amount: object
    allocated_amount: object
    unallocated_amount: object
    total_percentage: object
    project_count: int
    warnings: list
    created: bool
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class UpdateManagementAllocationDraftCommand:
    version: object
    entries: list
    edit_mode: str
    reason: str = ""
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class CreateManagementAllocationRevisionCommand:
    source_version: object
    reason: str = ""
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class CreateManagementAllocationRevisionResult:
    source_version: object
    version: object
    entries: list
    metadata: dict = field(default_factory=dict)
