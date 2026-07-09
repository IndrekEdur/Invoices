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
