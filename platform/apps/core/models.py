import uuid

from django.conf import settings
from django.db import models


class Organization(models.Model):
    class Type(models.TextChoices):
        COMPANY = "company", "Company"
        SOLE_PROPRIETOR = "sole_proprietor", "Sole proprietor"
        NON_PROFIT = "non_profit", "Non-profit"
        GOVERNMENT = "government", "Government"
        OTHER = "other", "Other"

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    legal_name = models.CharField(max_length=255, blank=True)
    organization_type = models.CharField(max_length=32, choices=Type.choices, default=Type.COMPANY)
    registration_number = models.CharField(max_length=64, blank=True)
    vat_number = models.CharField(max_length=64, blank=True)
    country = models.CharField(max_length=2, default="EE")
    timezone = models.CharField(max_length=64, default="Europe/Tallinn")
    currency = models.CharField(max_length=3, default="EUR")
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name


class OrganizationConfiguration(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="configuration")
    default_currency = models.CharField(max_length=3, default="EUR")
    default_timezone = models.CharField(max_length=64, default="Europe/Tallinn")
    language = models.CharField(max_length=16, default="et")
    date_format = models.CharField(max_length=32, default="YYYY-MM-DD")
    number_format = models.CharField(max_length=32, default="1 234,56")
    auto_approval_enabled = models.BooleanField(default=False)
    auto_approval_threshold = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "id"]

    def __str__(self) -> str:
        return f"Configuration for {self.organization}"


class AppUserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="app_profile")
    active_organization = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        related_name="active_user_profiles",
        blank=True,
        null=True,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username", "id"]

    def __str__(self) -> str:
        return f"Profile for {self.user.username}"


class AuditEvent(models.Model):
    """Append-only audit record for compliance and traceability."""

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        blank=True,
        null=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        blank=True,
        null=True,
    )
    event_type = models.CharField(max_length=128)
    object_type = models.CharField(max_length=128)
    object_id = models.CharField(max_length=128)
    message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.event_type} {self.object_type}:{self.object_id}"
