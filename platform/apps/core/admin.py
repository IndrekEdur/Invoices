from django.contrib import admin

from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "organization_type", "country", "currency", "is_active", "created_at")
    list_filter = ("organization_type", "is_active", "country", "currency")
    search_fields = ("name", "legal_name", "registration_number", "vat_number")
    readonly_fields = ("uuid", "created_at", "updated_at")
