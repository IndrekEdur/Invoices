from django.contrib import admin

from .models import Document, DocumentTag, DocumentVersion


class DocumentVersionInline(admin.TabularInline):
    model = DocumentVersion
    extra = 0
    readonly_fields = ["created_at"]


class DocumentTagInline(admin.TabularInline):
    model = DocumentTag
    extra = 0
    readonly_fields = ["created_at"]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["title", "source", "status", "original_filename", "mime_type", "size_bytes", "created_at"]
    list_filter = ["source", "status", "mime_type", "created_at"]
    search_fields = ["title", "original_filename", "sha256", "uuid"]
    readonly_fields = ["uuid", "created_at", "updated_at"]
    inlines = [DocumentVersionInline, DocumentTagInline]


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ["document", "version_number", "mime_type", "size_bytes", "created_at"]
    list_filter = ["mime_type", "created_at"]
    search_fields = ["document__title", "document__original_filename", "sha256"]
    readonly_fields = ["created_at"]


@admin.register(DocumentTag)
class DocumentTagAdmin(admin.ModelAdmin):
    list_display = ["document", "name", "created_at"]
    search_fields = ["document__title", "document__original_filename", "name"]
    readonly_fields = ["created_at"]
