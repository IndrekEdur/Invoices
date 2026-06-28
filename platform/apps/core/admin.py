from django.contrib import admin

from .models import AppUserProfile, Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "organization_type", "country", "currency", "is_active", "created_at")
    list_filter = ("organization_type", "is_active", "country", "currency")
    search_fields = ("name", "legal_name", "registration_number", "vat_number")
    readonly_fields = ("uuid", "created_at", "updated_at")


@admin.register(AppUserProfile)
class AppUserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "active_organization", "created_at")
    list_filter = ("active_organization",)
    search_fields = ("user__username", "user__email", "active_organization__name")
    readonly_fields = ("created_at", "updated_at")
