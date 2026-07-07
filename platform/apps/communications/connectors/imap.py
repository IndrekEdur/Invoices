import imaplib
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

from django.core.exceptions import ValidationError
from django.utils import timezone

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

    def fetch_messages(self, limit=50, mailbox="INBOX"):
        if self.client is None:
            raise RuntimeError("IMAP connection is not open.")

        status, _response = self.client.select(mailbox)
        if status != "OK":
            raise RuntimeError(f"IMAP SELECT failed with status: {status}")

        status, response = self.client.search(None, "ALL")
        if status != "OK":
            raise RuntimeError(f"IMAP SEARCH failed with status: {status}")

        message_ids = (response[0] or b"").split()
        latest_message_ids = message_ids[-limit:] if limit else []
        messages = []

        for message_id in latest_message_ids:
            status, fetch_response = self.client.fetch(message_id, "(RFC822)")
            if status != "OK":
                raise RuntimeError(f"IMAP FETCH failed with status: {status}")

            raw_bytes = self._extract_rfc822_payload(fetch_response)
            if raw_bytes:
                messages.append(self.parse_email_message(raw_bytes, external_message_id=message_id.decode()))

        return messages

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

    def parse_email_message(self, raw_bytes, external_message_id=""):
        parsed_message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
        subject = str(parsed_message.get("Subject", ""))
        sent_at = self._parse_date(parsed_message.get("Date"))
        body_text, body_html = self.extract_body_parts(parsed_message)
        sender = self.extract_addresses(parsed_message.get("From", ""))
        references = str(parsed_message.get("References", "") or "")
        in_reply_to = str(parsed_message.get("In-Reply-To", "") or "")

        raw_data = {
            "external_message_id": external_message_id or str(parsed_message.get("Message-ID", "")),
            "internet_message_id": str(parsed_message.get("Message-ID", "")),
            "external_thread_id": references or in_reply_to or self.normalize_subject(subject),
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "sender_email": sender[0]["email"] if sender else "",
            "sender_name": sender[0]["name"] if sender else "",
            "recipients": self.extract_addresses(parsed_message.get("To", "")),
            "cc": self.extract_addresses(parsed_message.get("Cc", "")),
            "bcc": self.extract_addresses(parsed_message.get("Bcc", "")),
            "direction": "inbound",
            "sent_at": sent_at,
            "received_at": sent_at or timezone.now(),
            "metadata": {
                "headers": {
                    "Message-ID": str(parsed_message.get("Message-ID", "")),
                    "References": references,
                    "In-Reply-To": in_reply_to,
                    "Date": str(parsed_message.get("Date", "")),
                    "From": str(parsed_message.get("From", "")),
                    "To": str(parsed_message.get("To", "")),
                    "Cc": str(parsed_message.get("Cc", "")),
                    "Bcc": str(parsed_message.get("Bcc", "")),
                }
            },
        }

        return self.map_imap_message(raw_data)

    @staticmethod
    def extract_addresses(header_value):
        return [{"name": name, "email": email} for name, email in getaddresses([header_value or ""]) if email]

    @staticmethod
    def extract_body_parts(parsed_message):
        body_text = ""
        body_html = ""

        if parsed_message.is_multipart():
            parts = parsed_message.walk()
        else:
            parts = [parsed_message]

        for part in parts:
            if part.is_multipart():
                continue
            if part.get_content_disposition() == "attachment":
                continue

            content_type = part.get_content_type()
            if content_type == "text/plain" and not body_text:
                body_text = part.get_content()
            elif content_type == "text/html" and not body_html:
                body_html = part.get_content()

        return body_text, body_html

    @staticmethod
    def normalize_subject(subject):
        normalized = (subject or "").strip()
        while True:
            lowered = normalized.lower()
            if lowered.startswith("re:"):
                normalized = normalized[3:].strip()
            elif lowered.startswith("fwd:"):
                normalized = normalized[4:].strip()
            elif lowered.startswith("fw:"):
                normalized = normalized[3:].strip()
            else:
                break

        return normalized.casefold()

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

    @staticmethod
    def _extract_rfc822_payload(fetch_response):
        for item in fetch_response or []:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                return item[1]
        return b""

    @staticmethod
    def _parse_date(value):
        if not value:
            return None

        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None

        if parsed.tzinfo is None:
            return timezone.make_aware(parsed)

        return parsed
