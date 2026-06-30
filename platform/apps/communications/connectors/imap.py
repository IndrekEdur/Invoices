from django.core.exceptions import ValidationError

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
