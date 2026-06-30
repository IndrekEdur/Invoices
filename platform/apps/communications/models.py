from django.db import models

from apps.core.models import Organization


class EmailAccount(models.Model):
    class Provider(models.TextChoices):
        IMAP = "imap", "IMAP"
        MICROSOFT_365 = "microsoft_365", "Microsoft 365"
        PST_IMPORT = "pst_import", "PST import"
        GMAIL = "gmail", "Gmail"
        OTHER = "other", "Other"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="email_accounts")
    provider = models.CharField(max_length=32, choices=Provider.choices)
    display_name = models.CharField(max_length=255)
    email_address = models.EmailField()
    username = models.CharField(max_length=255, blank=True)
    host = models.CharField(max_length=255, blank=True)
    port = models.PositiveIntegerField(blank=True, null=True)
    use_ssl = models.BooleanField(default=True)
    use_tls = models.BooleanField(default=False)
    auth_type = models.CharField(max_length=64, blank=True)
    encrypted_secret_placeholder = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "display_name", "id"]

    def __str__(self) -> str:
        return f"{self.display_name} <{self.email_address}>"
