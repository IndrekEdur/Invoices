from django.contrib import admin

from .models import Project, ProjectAddress, ProjectParty


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "organization", "status", "project_type", "start_date", "end_date")
    list_filter = ("organization", "status", "project_type")
    search_fields = ("code", "name", "description", "organization__name")
    readonly_fields = ("uuid", "created_at", "updated_at")


@admin.register(ProjectParty)
class ProjectPartyAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "project", "organization", "company_name", "email", "is_active")
    list_filter = ("organization", "role", "is_active")
    search_fields = ("name", "company_name", "email", "phone", "external_reference", "project__code", "project__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ProjectAddress)
class ProjectAddressAdmin(admin.ModelAdmin):
    list_display = ("project", "address_type", "label", "city", "street", "country", "is_primary")
    list_filter = ("organization", "address_type", "country", "is_primary")
    search_fields = ("label", "city", "street", "postal_code", "project__code", "project__name")
    readonly_fields = ("created_at", "updated_at")
