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
