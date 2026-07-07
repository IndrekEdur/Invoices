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


@dataclass(frozen=True)
class SuggestEmailProjectLinksCommand:
    email_message: object
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class DetectEmailQuestionsCommand:
    email_message: object
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class ProcessEmailCommand:
    email_message: object
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class SyncEmailAccountCommand:
    email_account: object
    limit: int = 50
    actor: object = None
    metadata: dict | None = None
    process_imported: bool = False


@dataclass(frozen=True)
class BuildConversationContextCommand:
    email_message: object
    include_thread: bool = True
    include_projects: bool = True
    include_questions: bool = True
    include_attachments: bool = True
    metadata: dict | None = None


@dataclass(frozen=True)
class CreateEmailAnswerDraftCommand:
    email_message: object
    question: object = None
    draft_text: str = ""
    evidence: dict | None = None
    context_snapshot: dict | None = None
    generated_by: str = "rule_based"
    actor: object = None
    metadata: dict | None = None
