import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class WorkflowDefinition(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    code = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name


class WorkflowState(models.Model):
    workflow = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE, related_name="states")
    code = models.CharField(max_length=128)
    name = models.CharField(max_length=255)
    is_initial = models.BooleanField(default=False)
    is_terminal = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["workflow__code", "code"]
        constraints = [
            models.UniqueConstraint(fields=["workflow", "code"], name="unique_workflow_state_code"),
            models.UniqueConstraint(
                fields=["workflow"],
                condition=Q(is_initial=True),
                name="unique_initial_state_per_workflow",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.workflow.code}:{self.code}"


class WorkflowTransition(models.Model):
    workflow = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE, related_name="transitions")
    from_state = models.ForeignKey(
        WorkflowState,
        on_delete=models.CASCADE,
        related_name="outgoing_transitions",
    )
    to_state = models.ForeignKey(
        WorkflowState,
        on_delete=models.CASCADE,
        related_name="incoming_transitions",
    )
    code = models.CharField(max_length=128)
    name = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["workflow__code", "code"]
        constraints = [
            models.UniqueConstraint(fields=["workflow", "code"], name="unique_workflow_transition_code"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.from_state_id and self.workflow_id and self.from_state.workflow_id != self.workflow_id:
            errors["from_state"] = "Transition from_state must belong to the same workflow."

        if self.to_state_id and self.workflow_id and self.to_state.workflow_id != self.workflow_id:
            errors["to_state"] = "Transition to_state must belong to the same workflow."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.workflow.code}:{self.code}"
