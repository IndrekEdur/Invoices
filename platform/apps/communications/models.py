from django.db import models

from apps.core.models import Organization
from apps.documents.models import Document


class EmailAccount(models.Model):
    class Provider(models.TextChoices):
        IMAP = "imap", "IMAP"
        MICROSOFT_365 = "microsoft_365", "Microsoft 365"
        PST_IMPORT = "pst_import", "PST import"
        GMAIL = "gmail", "Gmail"
        OTHER = "other", "Other"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="email_accounts")
    provider = models.CharField(max_length=32, choices=Provider.choices)
    display_name = models.CharField(max_length=255)
    email_address = models.EmailField()
    username = models.CharField(max_length=255, blank=True)
    host = models.CharField(max_length=255, blank=True)
    port = models.PositiveIntegerField(blank=True, null=True)
    use_ssl = models.BooleanField(default=True)
    use_tls = models.BooleanField(default=False)
    auth_type = models.CharField(max_length=64, blank=True)
    encrypted_secret_placeholder = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "display_name", "id"]

    def __str__(self) -> str:
        return f"{self.display_name} <{self.email_address}>"


class EmailThread(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="email_threads")
    account = models.ForeignKey(EmailAccount, on_delete=models.CASCADE, related_name="threads")
    external_thread_id = models.CharField(max_length=255)
    subject = models.CharField(max_length=998, blank=True)
    normalized_subject = models.CharField(max_length=998, blank=True)
    message_count = models.PositiveIntegerField(default=0)
    last_message_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["account", "external_thread_id"], name="unique_thread_per_account"),
        ]

    def __str__(self) -> str:
        return self.subject or self.external_thread_id


class EmailMessage(models.Model):
    class Direction(models.TextChoices):
        INBOUND = "inbound", "Inbound"
        OUTBOUND = "outbound", "Outbound"
        INTERNAL = "internal", "Internal"
        UNKNOWN = "unknown", "Unknown"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="email_messages")
    account = models.ForeignKey(EmailAccount, on_delete=models.CASCADE, related_name="messages")
    thread = models.ForeignKey(
        EmailThread,
        on_delete=models.SET_NULL,
        related_name="messages",
        blank=True,
        null=True,
    )
    external_message_id = models.CharField(max_length=255)
    internet_message_id = models.CharField(max_length=998, blank=True)
    subject = models.CharField(max_length=998, blank=True)
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    sender_email = models.EmailField(blank=True)
    sender_name = models.CharField(max_length=255, blank=True)
    recipients = models.JSONField(default=list, blank=True)
    cc = models.JSONField(default=list, blank=True)
    bcc = models.JSONField(default=list, blank=True)
    direction = models.CharField(max_length=32, choices=Direction.choices, default=Direction.UNKNOWN)
    sent_at = models.DateTimeField(blank=True, null=True)
    received_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at", "-sent_at", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["account", "external_message_id"], name="unique_message_per_account"),
        ]

    def __str__(self) -> str:
        return self.subject or self.external_message_id


class EmailAttachment(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="email_attachments")
    email_message = models.ForeignKey(EmailMessage, on_delete=models.CASCADE, related_name="attachments")
    document = models.ForeignKey(
        Document,
        on_delete=models.SET_NULL,
        related_name="email_attachments",
        blank=True,
        null=True,
    )
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    content_id = models.CharField(max_length=255, blank=True)
    is_inline = models.BooleanField(default=False)
    sha256 = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["email_message_id", "original_filename", "id"]

    def __str__(self) -> str:
        return self.original_filename
