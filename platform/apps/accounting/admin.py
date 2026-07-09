from django.contrib import admin

from .models import AccountingDimension, AccountingIntegration


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
