from dataclasses import dataclass, field


@dataclass(frozen=True)
class CreateProjectWithSuggestedCodeCommand:
    organization: object
    name: str
    description: str = ""
    project_type: str = "other"
    status: str = "active"
    start_date: object = None
    end_date: object = None
    min_code: object = None
    prefix: str = ""
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class CreateProjectWithSuggestedCodeResult:
    project: object
    suggested_code: str
    allocation_summary: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ChangeProjectStatusCommand:
    project: object
    new_status: str
    reason: str = ""
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class ChangeProjectStatusResult:
    project: object
    previous_status: str
    new_status: str
    changed: bool
    message: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class UpdateProjectDetailsCommand:
    project: object
    name: str
    description: str = ""
    project_type: str = "other"
    start_date: object = None
    end_date: object = None
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class CreateProjectFromAccountingDimensionCommand:
    accounting_dimension: object
    project_name: str | None = None
    project_type: str = "electrical"
    status: str = "active"
    description: str = ""
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class CreateProjectFromAccountingDimensionResult:
    project: object
    accounting_dimension: object
    created: bool
    linked_allocation_count: int
    message: str
    metadata: dict = field(default_factory=dict)
