from dataclasses import dataclass


@dataclass(frozen=True)
class MeritDimensionDTO:
    external_id: str
    code: str
    name: str
    dimension_type: str
    active: bool
    raw: dict
