from django.contrib import admin

from .models import WorkflowDefinition, WorkflowInstance, WorkflowState, WorkflowTransition


class WorkflowStateInline(admin.TabularInline):
    model = WorkflowState
    extra = 0
    fields = ("code", "name", "is_initial", "is_terminal")


class WorkflowTransitionInline(admin.TabularInline):
    model = WorkflowTransition
    extra = 0
    fields = ("code", "name", "from_state", "to_state")


@admin.register(WorkflowDefinition)
class WorkflowDefinitionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "description")
    readonly_fields = ("uuid", "created_at", "updated_at")
    inlines = (WorkflowStateInline, WorkflowTransitionInline)


@admin.register(WorkflowState)
class WorkflowStateAdmin(admin.ModelAdmin):
    list_display = ("workflow", "code", "name", "is_initial", "is_terminal", "created_at")
    list_filter = ("workflow", "is_initial", "is_terminal")
    search_fields = ("workflow__code", "code", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WorkflowTransition)
class WorkflowTransitionAdmin(admin.ModelAdmin):
    list_display = ("workflow", "code", "name", "from_state", "to_state", "created_at")
    list_filter = ("workflow",)
    search_fields = ("workflow__code", "code", "name", "from_state__code", "to_state__code")
    readonly_fields = ("created_at",)


@admin.register(WorkflowInstance)
class WorkflowInstanceAdmin(admin.ModelAdmin):
    list_display = ("workflow", "current_state", "entity_type", "entity_uuid", "organization", "started_at")
    list_filter = ("workflow", "current_state", "entity_type", "organization")
    search_fields = ("workflow__code", "entity_type", "entity_uuid", "organization__name")
    readonly_fields = ("uuid", "created_at", "updated_at")
