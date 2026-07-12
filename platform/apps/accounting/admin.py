from django.contrib import admin

from .models import (
    AccountingDimension,
    AccountingGLAllocation,
    AccountingGLBatch,
    AccountingGLEntry,
    AccountingIntegration,
    AccountingSyncRun,
    AccountingSyncState,
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
