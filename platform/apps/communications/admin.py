from django.contrib import admin

from .models import (
    EmailAccount,
    EmailAnswerDraft,
    EmailAttachment,
    EmailMailboxState,
    EmailMessage,
    EmailProjectLink,
    EmailQuestion,
    EmailThread,
)


@admin.register(EmailAccount)
class EmailAccountAdmin(admin.ModelAdmin):
    list_display = ("display_name", "email_address", "organization", "provider", "is_active", "last_sync_at")
    list_filter = ("provider", "is_active", "use_ssl", "use_tls", "organization")
    search_fields = ("display_name", "email_address", "username", "host", "organization__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmailMailboxState)
class EmailMailboxStateAdmin(admin.ModelAdmin):
    list_display = (
        "email_account",
        "mailbox_name",
        "sync_status",
        "initial_import_status",
        "last_processed_uid",
        "last_successful_sync_at",
        "updated_at",
    )
    list_filter = ("organization", "email_account", "sync_status", "initial_import_status")
    search_fields = ("mailbox_name", "external_mailbox_id", "email_account__email_address")
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


@admin.register(EmailAttachment)
class EmailAttachmentAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "email_message",
        "organization",
        "document",
        "content_type",
        "size_bytes",
        "is_inline",
    )
    list_filter = ("organization", "content_type", "is_inline")
    search_fields = (
        "original_filename",
        "content_id",
        "sha256",
        "email_message__subject",
        "email_message__external_message_id",
        "document__title",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmailProjectLink)
class EmailProjectLinkAdmin(admin.ModelAdmin):
    list_display = (
        "email_message",
        "project",
        "organization",
        "status",
        "source",
        "confidence_band",
        "confidence",
        "is_primary",
        "confirmed_by",
        "confirmed_at",
    )
    list_filter = ("organization", "status", "source", "confidence_band", "is_primary", "project")
    search_fields = ("email_message__subject", "email_message__external_message_id", "project__code", "project__name")
    readonly_fields = ("created_at", "updated_at", "last_evaluated_at")


@admin.register(EmailQuestion)
class EmailQuestionAdmin(admin.ModelAdmin):
    list_display = ("email_message", "organization", "status", "detection_method", "confidence", "created_at")
    list_filter = ("organization", "status", "detection_method")
    search_fields = ("question_text", "email_message__subject", "email_message__external_message_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmailAnswerDraft)
class EmailAnswerDraftAdmin(admin.ModelAdmin):
    list_display = ("email_message", "organization", "question", "status", "generated_by", "approved_at", "sent_at")
    list_filter = ("organization", "status", "generated_by")
    search_fields = ("draft_text", "final_text", "email_message__subject", "email_message__external_message_id")
    readonly_fields = ("created_at", "updated_at")
