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
class EvaluateEmailProjectLinksCommand:
    organization: object
    email_message_ids: tuple | list | None = None
    account_ids: tuple | list | None = None
    mailbox: str | None = None
    date_from: object = None
    date_to: object = None
    project_ids: tuple | list | None = None
    rule_sources: tuple | list | None = None
    dry_run: bool = False
    force_reprocess: bool = False
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class ConfirmCommunicationProjectLinkCommand:
    link: object
    make_primary: bool = True
    actor: object = None
    reason: str = ""
    metadata: dict | None = None


@dataclass(frozen=True)
class RejectCommunicationProjectLinkCommand:
    link: object
    reason: str
    actor: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class CorrectCommunicationProjectLinkCommand:
    email_message: object
    project: object
    actor: object = None
    reason: str = ""
    make_primary: bool = True
    metadata: dict | None = None


@dataclass(frozen=True)
class ExtractCommunicationCandidatesCommand:
    organization: object
    email_message_ids: tuple | list | None = None
    project_ids: tuple | list | None = None
    date_from: object = None
    date_to: object = None
    candidate_types: tuple | list | None = None
    include_thread_context: bool = True
    dry_run: bool = False
    force_reprocess: bool = False
    provider: object = None
    limit: int = 100
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
    mailbox_name: str = "INBOX"
    incremental: bool = True


@dataclass(frozen=True)
class GetOrCreateMailboxStateCommand:
    email_account: object
    mailbox_name: str = "INBOX"
    external_mailbox_id: str = ""
    uid_validity: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class MarkMailboxSyncStartedCommand:
    mailbox_state: object
    initial_import: bool = False
    metadata: dict | None = None


@dataclass(frozen=True)
class UpdateMailboxSyncProgressCommand:
    mailbox_state: object
    last_discovered_uid: object = None
    last_processed_uid: object = None
    highest_modseq: object = None
    discovered_increment: int = 0
    imported_increment: int = 0
    processed_increment: int = 0
    skipped_increment: int = 0
    failed_increment: int = 0
    cursor_metadata: dict | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class MarkMailboxSyncCompletedCommand:
    mailbox_state: object
    initial_import: bool = False
    metadata: dict | None = None


@dataclass(frozen=True)
class MarkMailboxSyncFailedCommand:
    mailbox_state: object
    safe_error: str
    initial_import: bool = False
    metadata: dict | None = None


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


@dataclass(frozen=True)
class MarkEmailAnswerDraftNeedsReviewCommand:
    draft: object
    actor: object
    metadata: dict | None = None


@dataclass(frozen=True)
class ApproveEmailAnswerDraftCommand:
    draft: object
    actor: object
    final_text: str | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class RejectEmailAnswerDraftCommand:
    draft: object
    actor: object
    reason: str = ""
    metadata: dict | None = None
