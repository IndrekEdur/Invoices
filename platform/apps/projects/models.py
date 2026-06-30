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


class ProjectParty(models.Model):
    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        SUPPLIER = "supplier", "Supplier"
        SUBCONTRACTOR = "subcontractor", "Subcontractor"
        PROJECT_MANAGER = "project_manager", "Project manager"
        SITE_MANAGER = "site_manager", "Site manager"
        ELECTRICIAN = "electrician", "Electrician"
        DESIGNER = "designer", "Designer"
        ARCHITECT = "architect", "Architect"
        OWNER_SUPERVISOR = "owner_supervisor", "Owner supervisor"
        AUTHORITY = "authority", "Authority"
        ACCOUNTANT = "accountant", "Accountant"
        OTHER = "other", "Other"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="project_parties")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="parties")
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.OTHER)
    company_name = models.CharField(max_length=255, blank=True)
    external_reference = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project__code", "role", "name", "id"]

    def __str__(self) -> str:
        return f"{self.name} ({self.role})"


class ProjectAddress(models.Model):
    class Type(models.TextChoices):
        SITE = "site", "Site"
        BILLING = "billing", "Billing"
        POSTAL = "postal", "Postal"
        WAREHOUSE = "warehouse", "Warehouse"
        TEMPORARY = "temporary", "Temporary"
        OTHER = "other", "Other"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="project_addresses")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="addresses")
    address_type = models.CharField(max_length=32, choices=Type.choices, default=Type.SITE)
    label = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=2, default="EE")
    city = models.CharField(max_length=255, blank=True)
    street = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=32, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    is_primary = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project__code", "address_type", "id"]

    def __str__(self) -> str:
        return f"{self.project.code} {self.address_type}: {self.label or self.street}"
