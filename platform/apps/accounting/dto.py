from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class MeritDimensionDTO:
    external_id: str
    code: str
    name: str
    dimension_type: str
    active: bool
    raw: dict


@dataclass(frozen=True)
class MeritDimensionValueDTO:
    external_id: str
    code: str
    name: str
    dimension_type: str
    active: bool
    raw: dict


class MeritGLDateType:
    DOCUMENT_DATE = "document_date"
    CHANGED_DATE = "changed_date"

    MERIT_VALUES = {
        DOCUMENT_DATE: 0,
        CHANGED_DATE: 1,
    }


@dataclass(frozen=True)
class MeritGLCostAllocationDTO:
    source_type: str
    code: str
    name: str
    multiplier: Decimal | None
    amount: Decimal | None
    batch_id: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class MeritGLEntryDTO:
    account_code: str
    account_name: str
    memo: str
    department_code: str
    debit_amount: Decimal | None
    debit_currency: str
    credit_amount: Decimal | None
    credit_currency: str
    type_id: str
    batch_id: str
    entry_id: str
    tax_id: str
    tax_percent: Decimal | None
    cost_allocations: tuple[MeritGLCostAllocationDTO, ...]
    raw: dict


@dataclass(frozen=True)
class MeritGLBatchDTO:
    external_id: str
    batch_code: str
    number: str
    source_document_id: str
    document: str
    batch_date: object
    currency_code: str
    currency_rate: Decimal | None
    total_amount: Decimal | None
    price_includes_vat: bool | None
    changed_at: object
    entries: tuple[MeritGLEntryDTO, ...]
    raw: dict
