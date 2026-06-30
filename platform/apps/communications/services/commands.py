from dataclasses import dataclass


@dataclass(frozen=True)
class ConvertEmailAttachmentToDocumentCommand:
    attachment: object
    file: object
    workflow: object = None
    actor: object = None
    metadata: dict | None = None
