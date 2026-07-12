from dataclasses import dataclass, field


@dataclass(frozen=True)
class RawEmailMessage:
    """Provider-neutral raw e-mail shape returned by connector implementations."""

    external_message_id: str
    internet_message_id: str = ""
    external_thread_id: str = ""
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    sender_email: str = ""
    sender_name: str = ""
    recipients: list = field(default_factory=list)
    cc: list = field(default_factory=list)
    bcc: list = field(default_factory=list)
    direction: str = "unknown"
    sent_at: object = None
    received_at: object = None
    metadata: dict | None = None


@dataclass(frozen=True)
class IMAPMailboxSnapshot:
    """Current provider-side mailbox cursor facts returned by an IMAP connector."""

    mailbox_name: str
    uid_validity: object = None
    highest_uid: object = None
    message_count: int = 0
    metadata: dict | None = None


@dataclass(frozen=True)
class ConversationContext:
    """Structured context for future project reasoning and reply drafting."""

    email_message: object
    thread_messages: list = field(default_factory=list)
    project_links: list = field(default_factory=list)
    confirmed_projects: list = field(default_factory=list)
    suggested_projects: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    attachments: list = field(default_factory=list)
    documents: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    metadata: dict | None = None
