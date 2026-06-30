import uuid

from django.db import models

from apps.core.models import Organization


class Document(models.Model):
    class Source(models.TextChoices):
        MAIL = "mail", "Mail"
        EMAIL_ATTACHMENT = "email_attachment", "Email attachment"
        MANUAL_UPLOAD = "manual_upload", "Manual upload"
        BANK_IMPORT = "bank_import", "Bank import"
        MERIT_IMPORT = "merit_import", "Merit import"
        EMTA_EXPORT = "emta_export", "EMTA export"
        API = "api", "API"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        NEW = "new", "New"
        PROCESSING = "processing", "Processing"
        PARSED = "parsed", "Parsed"
        NEEDS_REVIEW = "needs_review", "Needs review"
        APPROVED = "approved", "Approved"
        ARCHIVED = "archived", "Archived"
        ERROR = "error", "Error"

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255)
    source = models.CharField(max_length=32, choices=Source.choices, default=Source.OTHER)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.NEW)
    file = models.FileField(upload_to="documents/originals/%Y/%m/", blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    mime_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.title or self.original_filename

    @property
    def is_final(self) -> bool:
        return self.status in {self.Status.APPROVED, self.Status.ARCHIVED}

    def mark_status(self, status: str, *, save: bool = True) -> None:
        valid_statuses = {choice for choice, _label in self.Status.choices}
        if status not in valid_statuses:
            raise ValueError(f"Unknown document status: {status}")

        self.status = status
        if save:
            self.save(update_fields=["status", "updated_at"])


class DocumentVersion(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()
    file = models.FileField(upload_to="documents/versions/%Y/%m/", blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    mime_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_id", "version_number"]
        constraints = [
            models.UniqueConstraint(fields=["document", "version_number"], name="unique_document_version_number"),
        ]

    def __str__(self) -> str:
        return f"{self.document} v{self.version_number}"


class DocumentTag(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["document", "name"], name="unique_document_tag_name"),
        ]

    def __str__(self) -> str:
        return self.name
