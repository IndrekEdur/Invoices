import imaplib

from django.core.exceptions import ValidationError

from apps.communications.dto import RawEmailMessage
from apps.communications.models import EmailAccount

from .base import BaseEmailConnector


class IMAPEmailConnector(BaseEmailConnector):
    """IMAP connector with real connection hooks but no message fetching yet."""

    def __init__(self, email_account):
        self.email_account = email_account
        self.connected = False
        self.client = None

    def connect(self):
        self._validate_configuration()
        try:
            if self.email_account.use_ssl:
                self.client = imaplib.IMAP4_SSL(self.email_account.host, self.email_account.port)
            else:
                self.client = imaplib.IMAP4(self.email_account.host, self.email_account.port)
        except imaplib.IMAP4.error as exc:
            raise RuntimeError(f"IMAP connection failed: {exc}") from exc
        except OSError as exc:
            raise RuntimeError(f"IMAP connection failed: {exc}") from exc

        # TODO: Replace encrypted_secret_placeholder with real encrypted secret storage.
        try:
            status, _response = self.client.login(
                self.email_account.username,
                self.email_account.encrypted_secret_placeholder,
            )
        except imaplib.IMAP4.error as exc:
            self.client = None
            raise RuntimeError(f"IMAP login failed: {exc}") from exc

        if status != "OK":
            self.client = None
            raise RuntimeError(f"IMAP login failed with status: {status}")

        self.connected = True
        return self

    def fetch_messages(self, limit=50):
        return []

    def list_mailboxes(self):
        if self.client is None:
            raise RuntimeError("IMAP connection is not open.")

        status, response = self.client.list()
        if status != "OK":
            raise RuntimeError(f"IMAP LIST failed with status: {status}")

        return [self._parse_mailbox_name(item) for item in response or []]

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
        if self.client is not None:
            try:
                self.client.logout()
            except imaplib.IMAP4.error:
                pass
            finally:
                self.client = None
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

    @staticmethod
    def _parse_mailbox_name(item):
        if isinstance(item, bytes):
            item = item.decode("utf-8", errors="replace")

        item = str(item)
        if '"' in item:
            parts = item.rsplit('"', 2)
            if len(parts) >= 2:
                return parts[-2]

        return item.split()[-1]
