from dataclasses import dataclass


@dataclass(frozen=True)
class ConvertEmailAttachmentToDocumentCommand:
    attachment: object
    file: object
    workflow: object = None
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class ConfirmEmailProjectLinkCommand:
    link: object
    actor: object
    metadata: dict | None = None


@dataclass(frozen=True)
class RejectEmailProjectLinkCommand:
    link: object
    actor: object
    reason: str = ""
    metadata: dict | None = None


@dataclass(frozen=True)
class CorrectEmailProjectLinkCommand:
    link: object
    new_project: object
    actor: object
    reason: str = ""
    metadata: dict | None = None
