from django.contrib import admin

from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "organization", "status", "project_type", "start_date", "end_date")
    list_filter = ("organization", "status", "project_type")
    search_fields = ("code", "name", "description", "organization__name")
    readonly_fields = ("uuid", "created_at", "updated_at")
