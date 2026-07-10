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
