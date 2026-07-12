from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import Organization


class AccountingIntegration(models.Model):
    class Provider(models.TextChoices):
        MERIT = "merit", "Merit"
        STANDARD_BOOKS = "standard_books", "Standard Books"
        XERO = "xero", "Xero"
        EXACT = "exact", "Exact"
        OTHER = "other", "Other"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="accounting_integrations",
    )
    provider = models.CharField(max_length=32, choices=Provider.choices, default=Provider.MERIT)
    display_name = models.CharField(max_length=255)
    api_base_url = models.URLField(blank=True)
    api_id = models.CharField(max_length=255, blank=True)
    encrypted_secret_placeholder = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "display_name", "id"]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.provider})"


class AccountingDimension(models.Model):
    class Provider(models.TextChoices):
        MERIT = "merit", "Merit"
        OTHER = "other", "Other"

    class DimensionType(models.TextChoices):
        PROJECT = "project", "Project"
        DEPARTMENT = "department", "Department"
        COST_CENTER = "cost_center", "Cost center"
        OTHER = "other", "Other"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="accounting_dimensions",
    )
    integration = models.ForeignKey(
        AccountingIntegration,
        on_delete=models.SET_NULL,
        related_name="dimensions",
        blank=True,
        null=True,
    )
    provider = models.CharField(max_length=32, choices=Provider.choices, default=Provider.MERIT)
    external_id = models.CharField(max_length=255, blank=True, null=True)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    dimension_type = models.CharField(
        max_length=32,
        choices=DimensionType.choices,
        default=DimensionType.PROJECT,
    )
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(blank=True, null=True)
    raw_data = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "provider", "dimension_type", "code", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider", "dimension_type", "code"],
                name="unique_accounting_dimension_code",
            ),
            models.UniqueConstraint(
                fields=["integration", "external_id"],
                condition=Q(external_id__isnull=False),
                name="unique_accounting_dimension_external_id",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class AccountingSyncState(models.Model):
    class SourceType(models.TextChoices):
        GL = "gl", "General ledger"
        SALES_INVOICES = "sales_invoices", "Sales invoices"
        PURCHASE_INVOICES = "purchase_invoices", "Purchase invoices"
        PAYMENTS = "payments", "Payments"
        ACCOUNTS = "accounts", "Accounts"
        OTHER = "other", "Other"

    class CursorType(models.TextChoices):
        NONE = "none", "None"
        CHANGED_DATETIME = "changed_datetime", "Changed datetime"
        PERIOD = "period", "Period"
        EXTERNAL_CURSOR = "external_cursor", "External cursor"
        OTHER = "other", "Other"

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

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="accounting_sync_states",
    )
    integration = models.ForeignKey(
        AccountingIntegration,
        on_delete=models.CASCADE,
        related_name="sync_states",
    )
    source_type = models.CharField(max_length=32, choices=SourceType.choices)
    cursor_type = models.CharField(max_length=32, choices=CursorType.choices, default=CursorType.NONE)
    cursor_value = models.CharField(max_length=255, blank=True, default="")
    cursor_datetime = models.DateTimeField(blank=True, null=True)
    last_completed_period_start = models.DateField(blank=True, null=True)
    last_completed_period_end = models.DateField(blank=True, null=True)
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
    created_count = models.PositiveBigIntegerField(default=0)
    updated_count = models.PositiveBigIntegerField(default=0)
    unchanged_count = models.PositiveBigIntegerField(default=0)
    skipped_count = models.PositiveBigIntegerField(default=0)
    failed_count = models.PositiveBigIntegerField(default=0)
    cursor_metadata = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "integration__display_name", "source_type", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["integration", "source_type"],
                name="unique_accounting_sync_state_per_source",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.integration} {self.source_type} ({self.sync_status})"


class AccountingSyncRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class Mode(models.TextChoices):
        INCREMENTAL = "incremental", "Incremental"
        INITIAL_BACKFILL = "initial_backfill", "Initial backfill"
        PERIOD_RESYNC = "period_resync", "Period resync"
        MANUAL = "manual", "Manual"
        OTHER = "other", "Other"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="accounting_sync_runs",
    )
    integration = models.ForeignKey(
        AccountingIntegration,
        on_delete=models.CASCADE,
        related_name="sync_runs",
    )
    sync_state = models.ForeignKey(
        AccountingSyncState,
        on_delete=models.SET_NULL,
        related_name="runs",
        blank=True,
        null=True,
    )
    source_type = models.CharField(max_length=32, choices=AccountingSyncState.SourceType.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.RUNNING)
    mode = models.CharField(max_length=32, choices=Mode.choices, default=Mode.INCREMENTAL)
    requested_period_start = models.DateField(blank=True, null=True)
    requested_period_end = models.DateField(blank=True, null=True)
    cursor_before = models.CharField(max_length=255, blank=True, default="")
    cursor_after = models.CharField(max_length=255, blank=True, default="")
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(blank=True, null=True)
    discovered_count = models.PositiveBigIntegerField(default=0)
    created_count = models.PositiveBigIntegerField(default=0)
    updated_count = models.PositiveBigIntegerField(default=0)
    unchanged_count = models.PositiveBigIntegerField(default=0)
    skipped_count = models.PositiveBigIntegerField(default=0)
    failed_count = models.PositiveBigIntegerField(default=0)
    safe_error = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self) -> str:
        return f"{self.integration} {self.source_type} {self.status} {self.started_at}"
