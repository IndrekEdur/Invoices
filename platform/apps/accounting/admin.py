from django.contrib import admin

from .models import AccountingDimension, AccountingIntegration, AccountingSyncRun, AccountingSyncState


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
