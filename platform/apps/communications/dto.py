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
