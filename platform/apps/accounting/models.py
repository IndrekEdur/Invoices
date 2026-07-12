from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import Organization
from apps.projects.models import Project


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


class AccountingAccountClassification(models.Model):
    class Category(models.TextChoices):
        REVENUE = "revenue", "Revenue"
        MATERIAL_COST = "material_cost", "Material cost"
        SUBCONTRACTOR_COST = "subcontractor_cost", "Subcontractor cost"
        LABOR_COST = "labor_cost", "Labor cost"
        EQUIPMENT_COST = "equipment_cost", "Equipment cost"
        TRANSPORT_COST = "transport_cost", "Transport cost"
        OTHER_DIRECT_COST = "other_direct_cost", "Other direct cost"
        OVERHEAD = "overhead", "Overhead"
        FINANCIAL_INCOME = "financial_income", "Financial income"
        FINANCIAL_COST = "financial_cost", "Financial cost"
        DEPRECIATION = "depreciation", "Depreciation"
        TAX = "tax", "Tax"
        EXCLUDED = "excluded", "Excluded"
        UNCLASSIFIED = "unclassified", "Unclassified"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="accounting_account_classifications",
    )
    integration = models.ForeignKey(
        AccountingIntegration,
        on_delete=models.CASCADE,
        related_name="account_classifications",
        blank=True,
        null=True,
    )
    account_code = models.CharField(max_length=64)
    account_name = models.CharField(max_length=255, blank=True, default="")
    category = models.CharField(max_length=32, choices=Category.choices, default=Category.UNCLASSIFIED)
    reporting_sign = models.DecimalField(max_digits=2, decimal_places=0, default=1)
    include_in_project_result = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "integration__display_name", "account_code", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "integration", "account_code"],
                name="unique_account_classification_integration_code",
            ),
            models.UniqueConstraint(
                fields=["organization", "account_code"],
                condition=Q(integration__isnull=True),
                name="unique_account_classification_org_fallback_code",
            ),
        ]

    def clean(self):
        super().clean()
        if self.integration and self.integration.organization_id != self.organization_id:
            raise ValidationError("Accounting classification integration must belong to the same organization.")
        if self.reporting_sign not in {Decimal("1"), Decimal("-1"), 1, -1}:
            raise ValidationError("Accounting classification reporting_sign must be 1 or -1.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.account_code} {self.category}"


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


class AccountingGLBatch(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="accounting_gl_batches",
    )
    integration = models.ForeignKey(
        AccountingIntegration,
        on_delete=models.CASCADE,
        related_name="gl_batches",
    )
    external_id = models.CharField(max_length=255)
    batch_code = models.CharField(max_length=64, blank=True, default="")
    number = models.CharField(max_length=64, blank=True, default="")
    source_document_id = models.CharField(max_length=255, blank=True, default="")
    document = models.CharField(max_length=255, blank=True, default="")
    batch_date = models.DateField(blank=True, null=True)
    currency_code = models.CharField(max_length=8, blank=True, default="")
    currency_rate = models.DecimalField(max_digits=20, decimal_places=8, blank=True, null=True)
    total_amount = models.DecimalField(max_digits=20, decimal_places=6, blank=True, null=True)
    price_includes_vat = models.BooleanField(blank=True, null=True)
    source_changed_at = models.DateTimeField(blank=True, null=True)
    raw_data = models.JSONField(default=dict, blank=True)
    source_created_at = models.DateTimeField(blank=True, null=True)
    first_synced_at = models.DateTimeField(default=timezone.now)
    last_synced_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-batch_date", "batch_code", "number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["integration", "external_id"], name="unique_gl_batch_external_id"),
        ]
        indexes = [
            models.Index(fields=["organization", "batch_date"], name="idx_gl_batch_org_date"),
            models.Index(fields=["integration", "source_changed_at"], name="idx_gl_batch_changed"),
            models.Index(fields=["integration", "source_document_id"], name="idx_gl_batch_doc"),
        ]

    def __str__(self) -> str:
        label = self.batch_code or self.number or "GL batch"
        return f"{self.batch_date} {label} ({self.external_id})"


class AccountingGLEntry(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="accounting_gl_entries",
    )
    integration = models.ForeignKey(
        AccountingIntegration,
        on_delete=models.CASCADE,
        related_name="gl_entries",
    )
    batch = models.ForeignKey(AccountingGLBatch, on_delete=models.CASCADE, related_name="entries")
    external_id = models.CharField(max_length=255)
    source_entry_id = models.CharField(max_length=255, blank=True, default="")
    sequence = models.IntegerField(blank=True, null=True)
    account_code = models.CharField(max_length=64, blank=True, default="")
    account_name = models.CharField(max_length=255, blank=True, default="")
    memo = models.TextField(blank=True, default="")
    department_code = models.CharField(max_length=64, blank=True, default="")
    debit_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    debit_currency = models.CharField(max_length=8, blank=True, default="")
    credit_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    credit_currency = models.CharField(max_length=8, blank=True, default="")
    type_id = models.CharField(max_length=64, blank=True, default="")
    tax_id = models.CharField(max_length=64, blank=True, default="")
    tax_percent = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    raw_data = models.JSONField(default=dict, blank=True)
    first_synced_at = models.DateTimeField(default=timezone.now)
    last_synced_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["batch_id", "sequence", "id"]
        constraints = [
            models.UniqueConstraint(fields=["integration", "batch", "external_id"], name="unique_gl_entry_external_id"),
        ]
        indexes = [
            models.Index(fields=["organization", "account_code"], name="idx_gl_entry_org_account"),
            models.Index(fields=["integration", "external_id"], name="idx_gl_entry_external"),
        ]

    @property
    def net_amount(self):
        return self.debit_amount - self.credit_amount

    def __str__(self) -> str:
        label = self.memo or f"debit {self.debit_amount} credit {self.credit_amount}"
        return f"{self.account_code} {label} ({self.batch.external_id})"


class AccountingGLAllocation(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="accounting_gl_allocations",
    )
    integration = models.ForeignKey(
        AccountingIntegration,
        on_delete=models.CASCADE,
        related_name="gl_allocations",
    )
    entry = models.ForeignKey(AccountingGLEntry, on_delete=models.CASCADE, related_name="allocations")
    external_id = models.CharField(max_length=255)
    source_type = models.CharField(max_length=64, blank=True, default="")
    dimension_code = models.CharField(max_length=64, blank=True, default="")
    dimension_name = models.CharField(max_length=255, blank=True, default="")
    dimension_type = models.CharField(max_length=64, blank=True, default="")
    multiplier = models.DecimalField(max_digits=20, decimal_places=8, blank=True, null=True)
    amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    accounting_dimension = models.ForeignKey(
        AccountingDimension,
        on_delete=models.SET_NULL,
        related_name="gl_allocations",
        blank=True,
        null=True,
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        related_name="gl_allocations",
        blank=True,
        null=True,
    )
    raw_data = models.JSONField(default=dict, blank=True)
    first_synced_at = models.DateTimeField(default=timezone.now)
    last_synced_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entry_id", "dimension_code", "id"]
        constraints = [
            models.UniqueConstraint(fields=["entry", "external_id"], name="unique_gl_allocation_external_id"),
        ]
        indexes = [
            models.Index(fields=["organization", "dimension_code"], name="idx_gl_alloc_org_dim"),
            models.Index(fields=["project"], name="idx_gl_alloc_project"),
            models.Index(fields=["integration", "external_id"], name="idx_gl_alloc_external"),
        ]

    def __str__(self) -> str:
        label = self.dimension_name or self.dimension_code or self.source_type
        return f"{self.dimension_code} {label} {self.amount}"
