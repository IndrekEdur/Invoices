from django.db import models
from django.db.models import Q

from apps.core.models import Organization


class AccountingIntegration(models.Model):
    class Provider(models.TextChoices):
        MERIT = "merit", "Merit"
        STANDARD_BOOKS = "standard_books", "Standard Books"
        XERO = "xero", "Xero"
        EXACT = "exact", "Exact"
        OTHER = "other", "Other"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="accounting_integrations",
    )
    provider = models.CharField(max_length=32, choices=Provider.choices, default=Provider.MERIT)
    display_name = models.CharField(max_length=255)
    api_base_url = models.URLField(blank=True)
    api_id = models.CharField(max_length=255, blank=True)
    encrypted_secret_placeholder = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "display_name", "id"]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.provider})"


class AccountingDimension(models.Model):
    class Provider(models.TextChoices):
        MERIT = "merit", "Merit"
        OTHER = "other", "Other"

    class DimensionType(models.TextChoices):
        PROJECT = "project", "Project"
        DEPARTMENT = "department", "Department"
        COST_CENTER = "cost_center", "Cost center"
        OTHER = "other", "Other"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="accounting_dimensions",
    )
    integration = models.ForeignKey(
        AccountingIntegration,
        on_delete=models.SET_NULL,
        related_name="dimensions",
        blank=True,
        null=True,
    )
    provider = models.CharField(max_length=32, choices=Provider.choices, default=Provider.MERIT)
    external_id = models.CharField(max_length=255, blank=True, null=True)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    dimension_type = models.CharField(
        max_length=32,
        choices=DimensionType.choices,
        default=DimensionType.PROJECT,
    )
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(blank=True, null=True)
    raw_data = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "provider", "dimension_type", "code", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider", "dimension_type", "code"],
                name="unique_accounting_dimension_code",
            ),
            models.UniqueConstraint(
                fields=["integration", "external_id"],
                condition=Q(external_id__isnull=False),
                name="unique_accounting_dimension_external_id",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"
