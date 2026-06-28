from django.contrib import admin

from .models import AppUserProfile, AuditEvent, Organization, OrganizationConfiguration


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "organization_type", "country", "currency", "is_active", "created_at")
    list_filter = ("organization_type", "is_active", "country", "currency")
    search_fields = ("name", "legal_name", "registration_number", "vat_number")
    readonly_fields = ("uuid", "created_at", "updated_at")


@admin.register(OrganizationConfiguration)
class OrganizationConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "default_currency",
        "default_timezone",
        "language",
        "auto_approval_enabled",
        "auto_approval_threshold",
    )
    list_filter = ("default_currency", "language", "auto_approval_enabled")
    search_fields = ("organization__name", "organization__legal_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AppUserProfile)
class AppUserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "active_organization", "created_at")
    list_filter = ("active_organization",)
    search_fields = ("user__username", "user__email", "active_organization__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "organization", "actor", "object_type", "object_id", "created_at")
    list_filter = ("event_type", "organization", "object_type")
    search_fields = ("event_type", "object_type", "object_id", "message", "actor__username")
    readonly_fields = ("uuid", "created_at")
