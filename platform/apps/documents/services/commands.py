from dataclasses import dataclass


@dataclass(frozen=True)
class StoreDocumentCommand:
    organization: object
    file: object
    original_filename: str
    title: str = ""
    source: str = "manual_upload"
    metadata: dict | None = None
    actor: object = None
