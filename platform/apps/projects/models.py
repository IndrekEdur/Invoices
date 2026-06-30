import uuid

from django.db import models

from apps.core.models import Organization


class Project(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        ACTIVE = "active", "Active"
        ON_HOLD = "on_hold", "On hold"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        ARCHIVED = "archived", "Archived"

    class Type(models.TextChoices):
        CONSTRUCTION = "construction", "Construction"
        ELECTRICAL = "electrical", "Electrical"
        SERVICE = "service", "Service"
        INTERNAL = "internal", "Internal"
        SALES = "sales", "Sales"
        OTHER = "other", "Other"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="projects")
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    project_type = models.CharField(max_length=32, choices=Type.choices, default=Type.OTHER)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "code", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="unique_project_code_per_organization"),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"
