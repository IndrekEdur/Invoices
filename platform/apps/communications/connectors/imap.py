from django.core.exceptions import ValidationError

from apps.communications.dto import RawEmailMessage
from apps.communications.models import EmailAccount

from .base import BaseEmailConnector


class IMAPEmailConnector(BaseEmailConnector):
    """IMAP connector skeleton with validation but no network login yet."""

    def __init__(self, email_account):
        self.email_account = email_account
        self.connected = False

    def connect(self):
        self._validate_configuration()
        self.connected = True
        return self

    def fetch_messages(self, limit=50):
        return []

    def map_imap_message(self, raw_data):
        metadata = dict(raw_data.get("metadata") or {})

        return RawEmailMessage(
            external_message_id=raw_data.get("external_message_id", ""),
            internet_message_id=raw_data.get("internet_message_id", ""),
            external_thread_id=raw_data.get("external_thread_id", ""),
            subject=raw_data.get("subject", ""),
            body_text=raw_data.get("body_text", ""),
            body_html=raw_data.get("body_html", ""),
            sender_email=raw_data.get("sender_email", ""),
            sender_name=raw_data.get("sender_name", ""),
            recipients=list(raw_data.get("recipients") or []),
            cc=list(raw_data.get("cc") or []),
            bcc=list(raw_data.get("bcc") or []),
            direction=raw_data.get("direction") or "inbound",
            sent_at=raw_data.get("sent_at"),
            received_at=raw_data.get("received_at"),
            metadata=metadata,
        )

    def disconnect(self):
        self.connected = False

    def _validate_configuration(self):
        if self.email_account.provider != EmailAccount.Provider.IMAP:
            raise ValidationError("IMAP connector requires an IMAP email account.")
        if not self.email_account.host:
            raise ValidationError("IMAP host is required.")
        if self.email_account.port is None:
            raise ValidationError("IMAP port is required.")
        if not self.email_account.username:
            raise ValidationError("IMAP username is required.")
        if not self.email_account.encrypted_secret_placeholder:
            raise ValidationError("IMAP encrypted secret placeholder is required.")
