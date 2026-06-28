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
