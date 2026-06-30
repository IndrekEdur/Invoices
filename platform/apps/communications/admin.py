from django.contrib import admin

from .models import EmailAccount, EmailMessage, EmailThread


@admin.register(EmailAccount)
class EmailAccountAdmin(admin.ModelAdmin):
    list_display = ("display_name", "email_address", "organization", "provider", "is_active", "last_sync_at")
    list_filter = ("provider", "is_active", "use_ssl", "use_tls", "organization")
    search_fields = ("display_name", "email_address", "username", "host", "organization__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmailThread)
class EmailThreadAdmin(admin.ModelAdmin):
    list_display = ("subject", "account", "organization", "external_thread_id", "message_count", "last_message_at")
    list_filter = ("organization", "account")
    search_fields = ("subject", "normalized_subject", "external_thread_id", "account__email_address")
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmailMessage)
class EmailMessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "sender_email", "account", "organization", "direction", "received_at", "sent_at")
    list_filter = ("organization", "account", "direction")
    search_fields = (
        "subject",
        "external_message_id",
        "internet_message_id",
        "sender_email",
        "sender_name",
        "account__email_address",
    )
    readonly_fields = ("created_at", "updated_at")
