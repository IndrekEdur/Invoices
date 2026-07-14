from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import Organization
from apps.projects.models import Project


class FinancialAlertType(models.TextChoices):
    PROJECT_LIFETIME_NEGATIVE = "project_lifetime_negative", "Project lifetime negative"
    PROJECT_CURRENT_MONTH_NEGATIVE = "project_current_month_negative", "Project current-month negative"
    PROJECT_CURRENT_MONTH_NO_REVENUE = "project_current_month_no_revenue", "Project current-month no revenue"
    PROJECT_MARGIN_BELOW_THRESHOLD = "project_margin_below_threshold", "Project margin below threshold"


class FinancialAlertBasis(models.TextChoices):
    ACCOUNTING = "accounting", "Accounting"
    MANAGEMENT = "management", "Management"


class FinancialAlertSeverity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    CRITICAL = "critical", "Critical"


class FinancialAlertStatus(models.TextChoices):
    OPEN = "open", "Open"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    RESOLVED = "resolved", "Resolved"
    DISMISSED = "dismissed", "Dismissed"


class FinancialAlertCandidateScope(models.TextChoices):
    ACTIVE_PROJECTS = "active_projects", "Active projects"
    ACTIVE_PROJECTS_WITH_MONTH_ACTIVITY = "active_projects_with_month_activity", "Active projects with month activity"
    ALL_WITH_ACTIVITY = "all_with_activity", "All with activity"
    SELECTED_PROJECTS = "selected_projects", "Selected projects"


class FinancialAlertEvaluationRunStatus(models.TextChoices):
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


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


class FinancialAlertRule(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="financial_alert_rules")
    alert_type = models.CharField(max_length=64, choices=FinancialAlertType.choices)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    financial_basis = models.CharField(
        max_length=32,
        choices=FinancialAlertBasis.choices,
        default=FinancialAlertBasis.MANAGEMENT,
    )
    severity = models.CharField(
        max_length=32,
        choices=FinancialAlertSeverity.choices,
        default=FinancialAlertSeverity.WARNING,
    )
    threshold_amount = models.DecimalField(max_digits=20, decimal_places=6, blank=True, null=True)
    threshold_percentage = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    grace_day = models.PositiveSmallIntegerField(blank=True, null=True)
    project_status_scope = models.JSONField(default=list, blank=True)
    candidate_scope = models.CharField(
        max_length=64,
        choices=FinancialAlertCandidateScope.choices,
        default=FinancialAlertCandidateScope.ACTIVE_PROJECTS,
    )
    currency = models.CharField(max_length=8, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "alert_type", "name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="unique_financial_alert_rule_name"),
            models.UniqueConstraint(
                fields=["organization", "alert_type"],
                condition=Q(is_active=True),
                name="unique_active_financial_alert_rule_type",
            ),
            models.CheckConstraint(
                check=Q(grace_day__isnull=True) | Q(grace_day__gte=1, grace_day__lte=31),
                name="financial_alert_rule_grace_day_range",
            ),
        ]

    def clean(self):
        super().clean()
        if self.grace_day is not None and not 1 <= self.grace_day <= 31:
            raise ValidationError("Financial alert rule grace_day must be between 1 and 31.")
        if self.threshold_percentage is not None and not Decimal("0") <= self.threshold_percentage <= Decimal("100"):
            raise ValidationError("Financial alert rule threshold_percentage must be between 0 and 100.")
        if self.configuration is None or not isinstance(self.configuration, dict):
            raise ValidationError("Financial alert rule configuration must be an object.")
        if self.project_status_scope is None or not isinstance(self.project_status_scope, list):
            raise ValidationError("Financial alert rule project_status_scope must be a list.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.alert_type})"


class FinancialAlert(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="financial_alerts")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="financial_alerts")
    rule = models.ForeignKey(FinancialAlertRule, on_delete=models.SET_NULL, related_name="alerts", blank=True, null=True)
    alert_type = models.CharField(max_length=64, choices=FinancialAlertType.choices)
    financial_basis = models.CharField(max_length=32, choices=FinancialAlertBasis.choices)
    severity = models.CharField(max_length=32, choices=FinancialAlertSeverity.choices)
    status = models.CharField(max_length=32, choices=FinancialAlertStatus.choices, default=FinancialAlertStatus.OPEN)
    fingerprint = models.CharField(max_length=64)
    fingerprint_version = models.PositiveSmallIntegerField(default=1)
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True, default="")
    period_start = models.DateField(blank=True, null=True)
    period_end = models.DateField(blank=True, null=True)
    currency = models.CharField(max_length=8, blank=True, default="")
    accounting_amount = models.DecimalField(max_digits=20, decimal_places=6, blank=True, null=True)
    management_amount = models.DecimalField(max_digits=20, decimal_places=6, blank=True, null=True)
    evaluated_amount = models.DecimalField(max_digits=20, decimal_places=6, blank=True, null=True)
    threshold_amount = models.DecimalField(max_digits=20, decimal_places=6, blank=True, null=True)
    data_quality_status = models.CharField(max_length=64, blank=True, default="")
    first_detected_at = models.DateTimeField(default=timezone.now)
    last_detected_at = models.DateTimeField(default=timezone.now)
    last_evaluated_at = models.DateTimeField(default=timezone.now)
    acknowledged_at = models.DateTimeField(blank=True, null=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="acknowledged_financial_alerts",
        blank=True,
        null=True,
    )
    resolved_at = models.DateTimeField(blank=True, null=True)
    dismissed_at = models.DateTimeField(blank=True, null=True)
    dismissed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="dismissed_financial_alerts",
        blank=True,
        null=True,
    )
    resolution_reason = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_detected_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "fingerprint"], name="unique_financial_alert_fingerprint"),
        ]
        indexes = [
            models.Index(fields=["organization", "status"], name="idx_fin_alert_org_status"),
            models.Index(fields=["project", "status"], name="idx_fin_alert_project_status"),
            models.Index(fields=["alert_type", "status"], name="idx_fin_alert_type_status"),
            models.Index(fields=["period_start", "period_end"], name="idx_fin_alert_period"),
            models.Index(fields=["severity", "status"], name="idx_fin_alert_severity_status"),
            models.Index(fields=["last_detected_at"], name="idx_fin_alert_last_detected"),
        ]

    @property
    def is_active_status(self) -> bool:
        return self.status in {FinancialAlertStatus.OPEN, FinancialAlertStatus.ACKNOWLEDGED}

    @property
    def lifecycle_label(self) -> str:
        return self.get_status_display()

    def __str__(self) -> str:
        return f"{self.project.code} {self.alert_type} ({self.status})"


class FinancialAlertEvaluationRun(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="financial_alert_evaluation_runs",
    )
    status = models.CharField(
        max_length=32,
        choices=FinancialAlertEvaluationRunStatus.choices,
        default=FinancialAlertEvaluationRunStatus.RUNNING,
    )
    evaluation_date = models.DateField()
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(blank=True, null=True)
    requested_project_count = models.PositiveIntegerField(default=0)
    evaluated_project_count = models.PositiveIntegerField(default=0)
    evaluated_rule_count = models.PositiveIntegerField(default=0)
    opened_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    reopened_count = models.PositiveIntegerField(default=0)
    resolved_count = models.PositiveIntegerField(default=0)
    unchanged_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    safe_error = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self) -> str:
        return f"{self.organization} financial alerts {self.evaluation_date} ({self.status})"


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


class AllocationStrategy(models.TextChoices):
    REVENUE = "revenue", "Revenue"
    EQUAL = "equal", "Equal"
    MANUAL_PERCENT = "manual_percent", "Manual percent"
    MANUAL_AMOUNT = "manual_amount", "Manual amount"
    PROJECT_MANAGER = "project_manager", "Project manager"


class PeriodStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"
    ARCHIVED = "archived", "Archived"


class VersionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"
    SUPERSEDED = "superseded", "Superseded"


class AllocationSourceType(models.TextChoices):
    COST_POOL = "cost_pool", "Cost pool"
    WORKSPACE_PROJECT = "workspace_project", "Workspace Project"


class AllocationSourceAmountBasis(models.TextChoices):
    MAPPED_GL_ACCOUNTS = "mapped_gl_accounts", "Mapped GL accounts"
    PROJECT_DIRECT_COST = "project_direct_cost", "Project direct cost"
    PROJECT_SELECTED_COSTS = "project_selected_costs", "Project selected costs"
    MANUAL = "manual", "Manual"


class ManagementCostPool(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="management_cost_pools",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    default_strategy = models.CharField(
        max_length=32,
        choices=AllocationStrategy.choices,
        default=AllocationStrategy.REVENUE,
    )
    display_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "display_order", "name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="unique_management_cost_pool_name"),
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class ManagementCostPoolAccount(models.Model):
    pool = models.ForeignKey(
        ManagementCostPool,
        on_delete=models.CASCADE,
        related_name="accounts",
    )
    account_code = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pool__organization__name", "pool__name", "account_code", "id"]
        constraints = [
            models.UniqueConstraint(fields=["pool", "account_code"], name="unique_management_pool_account_code"),
        ]

    def clean(self):
        super().clean()
        if self.is_active and self.pool_id:
            conflict = ManagementCostPoolAccount.objects.filter(
                is_active=True,
                account_code=self.account_code,
                pool__organization=self.pool.organization,
            ).exclude(pk=self.pk)
            if conflict.exists():
                raise ValidationError("One GL account may belong to only one active management cost pool.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.pool}: {self.account_code}"


class ManagementAllocationPeriod(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="management_allocation_periods",
    )
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=32, choices=PeriodStatus.choices, default=PeriodStatus.DRAFT)

    class Meta:
        ordering = ["organization__name", "-year", "-month", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "year", "month"], name="unique_management_period"),
        ]

    @property
    def period_label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def clean(self):
        super().clean()
        if not 1 <= self.month <= 12:
            raise ValidationError("Management allocation month must be between 1 and 12.")
        if self.year < 2000:
            raise ValidationError("Management allocation year must be 2000 or later.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.period_label


class ManagementAllocationVersion(models.Model):
    period = models.ForeignKey(
        ManagementAllocationPeriod,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    pool = models.ForeignKey(
        ManagementCostPool,
        on_delete=models.CASCADE,
        related_name="allocation_versions",
        blank=True,
        null=True,
    )
    source_type = models.CharField(
        max_length=32,
        choices=AllocationSourceType.choices,
        default=AllocationSourceType.COST_POOL,
    )
    source_project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="sourced_management_allocation_versions",
        blank=True,
        null=True,
    )
    source_amount_basis = models.CharField(
        max_length=32,
        choices=AllocationSourceAmountBasis.choices,
        default=AllocationSourceAmountBasis.MAPPED_GL_ACCOUNTS,
    )
    source_currency = models.CharField(max_length=8, blank=True, default="")
    source_period_start = models.DateField(blank=True, null=True)
    source_period_end = models.DateField(blank=True, null=True)
    version_number = models.PositiveIntegerField()
    status = models.CharField(max_length=32, choices=VersionStatus.choices, default=VersionStatus.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_management_allocation_versions",
        blank=True,
        null=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_management_allocation_versions",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    reason = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = [
            "period",
            "source_type",
            "pool__display_order",
            "pool__name",
            "source_project__code",
            "-version_number",
            "id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["period", "pool", "version_number"],
                condition=Q(pool__isnull=False),
                name="unique_management_pool_version_number",
            ),
            models.UniqueConstraint(
                fields=["period", "source_project", "version_number"],
                condition=Q(source_project__isnull=False),
                name="unique_management_project_version_number",
            ),
            models.UniqueConstraint(
                fields=["period", "pool"],
                condition=Q(status=VersionStatus.APPROVED, pool__isnull=False),
                name="unique_approved_management_pool_version",
            ),
            models.UniqueConstraint(
                fields=["period", "source_project"],
                condition=Q(status=VersionStatus.APPROVED, source_project__isnull=False),
                name="unique_approved_management_project_version",
            ),
            models.CheckConstraint(
                check=(
                    Q(source_type=AllocationSourceType.COST_POOL, pool__isnull=False, source_project__isnull=True)
                    | Q(
                        source_type=AllocationSourceType.WORKSPACE_PROJECT,
                        pool__isnull=True,
                        source_project__isnull=False,
                    )
                ),
                name="management_allocation_valid_source",
            ),
        ]

    def clean(self):
        super().clean()
        if self.version_number < 1:
            raise ValidationError("Management allocation version number must be positive.")
        if self.source_type == AllocationSourceType.COST_POOL:
            if not self.pool_id or self.source_project_id:
                raise ValidationError("Cost pool allocations require a pool and no source Project.")
            if self.period_id and self.pool.organization_id != self.period.organization_id:
                raise ValidationError("Management allocation pool and period must belong to the same organization.")
        elif self.source_type == AllocationSourceType.WORKSPACE_PROJECT:
            if not self.source_project_id or self.pool_id:
                raise ValidationError("Workspace Project allocations require a source Project and no pool.")
            if self.period_id and self.source_project.organization_id != self.period.organization_id:
                raise ValidationError("Management allocation source Project and period must belong to the same organization.")
        else:
            raise ValidationError("Unsupported management allocation source type.")
        if self.status == VersionStatus.APPROVED and self.pool_id and not self.pool.is_active:
            raise ValidationError("Inactive management cost pools cannot be approved.")
        if self.source_period_start and self.source_period_end and self.source_period_end < self.source_period_start:
            raise ValidationError("Management allocation source period end cannot be before source period start.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def source_label(self) -> str:
        if self.source_type == AllocationSourceType.WORKSPACE_PROJECT and self.source_project_id:
            return f"Workspace Project {self.source_project.code}"
        if self.pool_id:
            return f"Cost Pool {self.pool.name}"
        return self.source_type

    @property
    def source_identifier(self) -> str:
        if self.source_type == AllocationSourceType.WORKSPACE_PROJECT and self.source_project_id:
            return f"project:{self.source_project_id}"
        if self.pool_id:
            return f"pool:{self.pool_id}"
        return "unknown"

    @property
    def source_display_name(self) -> str:
        if self.source_type == AllocationSourceType.WORKSPACE_PROJECT and self.source_project_id:
            return f"{self.source_project.code} {self.source_project.name}"
        if self.pool_id:
            return self.pool.name
        return self.get_source_type_display()

    def __str__(self) -> str:
        return f"{self.period.period_label} {self.source_display_name} v{self.version_number} ({self.status})"


class ManagementAllocationRule(models.Model):
    pool = models.ForeignKey(
        ManagementCostPool,
        on_delete=models.CASCADE,
        related_name="allocation_rules",
    )
    strategy = models.CharField(max_length=32, choices=AllocationStrategy.choices)
    is_active = models.BooleanField(default=True)
    configuration = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["pool__organization__name", "pool__display_order", "pool__name", "strategy", "id"]

    def __str__(self) -> str:
        return f"{self.pool.name} {self.strategy}"


class ManagementAllocationEntry(models.Model):
    version = models.ForeignKey(
        ManagementAllocationVersion,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="management_allocation_entries",
    )
    percentage = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    manual_override = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["version", "project__code", "id"]
        constraints = [
            models.UniqueConstraint(fields=["version", "project"], name="unique_management_entry_project"),
        ]

    def clean(self):
        super().clean()
        if self.percentage < Decimal("0") or self.percentage > Decimal("100"):
            raise ValidationError("Management allocation percentage must be between 0 and 100.")
        if self.version_id and self.project_id:
            version_org_id = self.version.period.organization_id
            if self.project.organization_id != version_org_id:
                raise ValidationError("Management allocation entry project must belong to the same organization.")
            if self.version.source_project_id and self.project_id == self.version.source_project_id:
                raise ValidationError("Management allocation source Project cannot also be a target Project.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.version} -> {self.project.code}: {self.amount}"
