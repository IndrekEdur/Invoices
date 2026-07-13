from django.contrib import admin

from .models import (
    AccountingAccountClassification,
    AccountingDimension,
    AccountingGLAllocation,
    AccountingGLBatch,
    AccountingGLEntry,
    AccountingIntegration,
    AccountingSyncRun,
    AccountingSyncState,
    ManagementAllocationEntry,
    ManagementAllocationPeriod,
    ManagementAllocationRule,
    ManagementAllocationVersion,
    ManagementCostPool,
    ManagementCostPoolAccount,
)


@admin.register(AccountingIntegration)
class AccountingIntegrationAdmin(admin.ModelAdmin):
    list_display = ("display_name", "organization", "provider", "is_active", "last_sync_at")
    list_filter = ("provider", "is_active")
    search_fields = ("display_name", "organization__name", "api_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AccountingDimension)
class AccountingDimensionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "organization", "provider", "dimension_type", "is_active", "last_synced_at")
    list_filter = ("provider", "dimension_type", "is_active")
    search_fields = ("code", "name", "external_id", "organization__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AccountingAccountClassification)
class AccountingAccountClassificationAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "integration",
        "account_code",
        "account_name",
        "category",
        "reporting_sign",
        "include_in_project_result",
        "is_active",
    )
    list_filter = ("category", "reporting_sign", "include_in_project_result", "is_active", "integration")
    search_fields = ("account_code", "account_name", "organization__name", "integration__display_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AccountingSyncState)
class AccountingSyncStateAdmin(admin.ModelAdmin):
    list_display = (
        "integration",
        "organization",
        "source_type",
        "cursor_type",
        "sync_status",
        "initial_import_status",
        "last_successful_sync_at",
        "last_progress_at",
        "discovered_count",
        "created_count",
        "updated_count",
        "failed_count",
    )
    list_filter = ("source_type", "cursor_type", "sync_status", "initial_import_status")
    search_fields = ("integration__display_name", "organization__name", "source_type", "cursor_value")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AccountingSyncRun)
class AccountingSyncRunAdmin(admin.ModelAdmin):
    list_display = (
        "integration",
        "organization",
        "source_type",
        "status",
        "mode",
        "started_at",
        "completed_at",
        "discovered_count",
        "created_count",
        "updated_count",
        "failed_count",
    )
    list_filter = ("source_type", "status", "mode")
    search_fields = ("integration__display_name", "organization__name", "source_type", "cursor_before", "cursor_after")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AccountingGLBatch)
class AccountingGLBatchAdmin(admin.ModelAdmin):
    list_display = (
        "integration",
        "external_id",
        "batch_date",
        "batch_code",
        "number",
        "total_amount",
        "currency_code",
        "source_changed_at",
        "last_synced_at",
    )
    list_filter = ("integration", "currency_code", "batch_date")
    search_fields = ("external_id", "batch_code", "number", "source_document_id", "document", "organization__name")
    readonly_fields = ("first_synced_at", "last_synced_at", "created_at", "updated_at")


@admin.register(AccountingGLEntry)
class AccountingGLEntryAdmin(admin.ModelAdmin):
    list_display = (
        "batch",
        "account_code",
        "account_name",
        "debit_amount",
        "credit_amount",
        "tax_percent",
        "last_synced_at",
    )
    list_filter = ("integration", "account_code")
    search_fields = ("external_id", "source_entry_id", "account_code", "account_name", "memo", "batch__external_id")
    readonly_fields = ("first_synced_at", "last_synced_at", "created_at", "updated_at")


@admin.register(AccountingGLAllocation)
class AccountingGLAllocationAdmin(admin.ModelAdmin):
    list_display = (
        "entry",
        "dimension_code",
        "dimension_name",
        "amount",
        "project",
        "accounting_dimension",
        "last_synced_at",
    )
    list_filter = ("integration", "source_type", "dimension_type")
    search_fields = ("external_id", "dimension_code", "dimension_name", "entry__external_id", "project__code")
    readonly_fields = ("first_synced_at", "last_synced_at", "created_at", "updated_at")


@admin.register(ManagementCostPool)
class ManagementCostPoolAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "default_strategy", "is_active", "display_order", "updated_at")
    list_filter = ("default_strategy", "is_active")
    search_fields = ("name", "description", "organization__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ManagementCostPoolAccount)
class ManagementCostPoolAccountAdmin(admin.ModelAdmin):
    list_display = ("account_code", "pool", "is_active", "created_at")
    list_filter = ("is_active", "pool__organization")
    search_fields = ("account_code", "pool__name", "pool__organization__name")
    readonly_fields = ("created_at",)


@admin.register(ManagementAllocationPeriod)
class ManagementAllocationPeriodAdmin(admin.ModelAdmin):
    list_display = ("period_label", "organization", "status")
    list_filter = ("status", "year", "month")
    search_fields = ("organization__name",)


@admin.register(ManagementAllocationVersion)
class ManagementAllocationVersionAdmin(admin.ModelAdmin):
    list_display = (
        "period",
        "source_type",
        "pool",
        "source_project",
        "version_number",
        "status",
        "created_by",
        "approved_by",
        "approved_at",
    )
    list_filter = ("status", "source_type", "pool", "period__year", "period__month")
    search_fields = ("pool__name", "source_project__code", "source_project__name", "period__organization__name", "reason")
    readonly_fields = ("created_at",)


@admin.register(ManagementAllocationRule)
class ManagementAllocationRuleAdmin(admin.ModelAdmin):
    list_display = ("pool", "strategy", "is_active", "updated_at")
    list_filter = ("strategy", "is_active")
    search_fields = ("pool__name", "pool__organization__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ManagementAllocationEntry)
class ManagementAllocationEntryAdmin(admin.ModelAdmin):
    list_display = ("version", "project", "percentage", "amount", "manual_override")
    list_filter = ("manual_override", "version__status", "version__source_type", "version__pool")
    search_fields = ("project__code", "project__name", "version__pool__name", "version__source_project__code", "notes")
