from django.conf import settings
from django.db import models

from apps.core.models import Organization
from apps.documents.models import Document
from apps.projects.models import Project


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


class EmailMailboxState(models.Model):
    class SyncStatus(models.TextChoices):
        IDLE = "idle", "Idle"
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused"
        FAILED = "failed", "Failed"

    class InitialImportStatus(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="email_mailbox_states")
    email_account = models.ForeignKey(EmailAccount, on_delete=models.CASCADE, related_name="mailbox_states")
    mailbox_name = models.CharField(max_length=255)
    external_mailbox_id = models.CharField(max_length=255, blank=True, default="")
    uid_validity = models.PositiveBigIntegerField(blank=True, null=True)
    last_discovered_uid = models.PositiveBigIntegerField(blank=True, null=True)
    last_processed_uid = models.PositiveBigIntegerField(blank=True, null=True)
    highest_modseq = models.PositiveBigIntegerField(blank=True, null=True)
    sync_status = models.CharField(max_length=32, choices=SyncStatus.choices, default=SyncStatus.IDLE)
    initial_import_status = models.CharField(
        max_length=32,
        choices=InitialImportStatus.choices,
        default=InitialImportStatus.NOT_STARTED,
    )
    last_sync_started_at = models.DateTimeField(blank=True, null=True)
    last_sync_completed_at = models.DateTimeField(blank=True, null=True)
    last_successful_sync_at = models.DateTimeField(blank=True, null=True)
    last_progress_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True, default="")
    discovered_count = models.PositiveBigIntegerField(default=0)
    imported_count = models.PositiveBigIntegerField(default=0)
    processed_count = models.PositiveBigIntegerField(default=0)
    skipped_count = models.PositiveBigIntegerField(default=0)
    failed_count = models.PositiveBigIntegerField(default=0)
    cursor_metadata = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["email_account__email_address", "mailbox_name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["email_account", "mailbox_name"], name="unique_mailbox_state_per_account"),
        ]

    def __str__(self) -> str:
        return f"{self.email_account.email_address} {self.mailbox_name} ({self.sync_status})"


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


class EmailProjectLink(models.Model):
    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Suggested"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"
        CORRECTED = "corrected", "Corrected"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="email_project_links")
    email_message = models.ForeignKey(EmailMessage, on_delete=models.CASCADE, related_name="project_links")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="email_links")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.SUGGESTED)
    confidence = models.PositiveSmallIntegerField(default=0)
    evidence = models.JSONField(default=dict, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="confirmed_email_project_links",
        blank=True,
        null=True,
    )
    confirmed_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["email_message_id", "project__code", "id"]
        constraints = [
            models.UniqueConstraint(fields=["email_message", "project"], name="unique_email_project_link"),
        ]

    def __str__(self) -> str:
        return f"{self.email_message} -> {self.project.code}"


class EmailQuestion(models.Model):
    class Status(models.TextChoices):
        DETECTED = "detected", "Detected"
        REVIEWED = "reviewed", "Reviewed"
        DISMISSED = "dismissed", "Dismissed"
        ANSWERED = "answered", "Answered"

    class DetectionMethod(models.TextChoices):
        RULE_BASED = "rule_based", "Rule based"
        AI = "ai", "AI"
        MANUAL = "manual", "Manual"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="email_questions")
    email_message = models.ForeignKey(EmailMessage, on_delete=models.CASCADE, related_name="questions")
    question_text = models.TextField()
    detection_method = models.CharField(
        max_length=32,
        choices=DetectionMethod.choices,
        default=DetectionMethod.RULE_BASED,
    )
    confidence = models.PositiveSmallIntegerField(default=0)
    evidence = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DETECTED)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["email_message_id", "-confidence", "id"]

    def __str__(self) -> str:
        return f"{self.email_message}: {self.question_text[:80]}"


class EmailAnswerDraft(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        NEEDS_REVIEW = "needs_review", "Needs review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        SENT = "sent", "Sent"

    class GeneratedBy(models.TextChoices):
        RULE_BASED = "rule_based", "Rule based"
        AI = "ai", "AI"
        MANUAL = "manual", "Manual"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="email_answer_drafts")
    email_message = models.ForeignKey(EmailMessage, on_delete=models.CASCADE, related_name="answer_drafts")
    question = models.ForeignKey(
        EmailQuestion,
        on_delete=models.SET_NULL,
        related_name="answer_drafts",
        blank=True,
        null=True,
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    draft_text = models.TextField(blank=True)
    final_text = models.TextField(blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    context_snapshot = models.JSONField(default=dict, blank=True)
    generated_by = models.CharField(max_length=32, choices=GeneratedBy.choices, default=GeneratedBy.RULE_BASED)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_email_answer_drafts",
        blank=True,
        null=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_email_answer_drafts",
        blank=True,
        null=True,
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Answer draft for {self.email_message}"
