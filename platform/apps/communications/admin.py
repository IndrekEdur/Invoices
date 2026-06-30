from django.contrib import admin

from .models import EmailAccount


@admin.register(EmailAccount)
class EmailAccountAdmin(admin.ModelAdmin):
    list_display = ("display_name", "email_address", "organization", "provider", "is_active", "last_sync_at")
    list_filter = ("provider", "is_active", "use_ssl", "use_tls", "organization")
    search_fields = ("display_name", "email_address", "username", "host", "organization__name")
    readonly_fields = ("created_at", "updated_at")
