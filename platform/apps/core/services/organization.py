from django.db import transaction

from ..models import Organization, OrganizationConfiguration
from .audit import AuditService
from .commands import CreateOrganizationCommand


class OrganizationService:
    @staticmethod
    def create(command: CreateOrganizationCommand) -> Organization:
        """Create an organization through the platform business workflow."""

        with transaction.atomic():
            organization = Organization.objects.create(
                name=command.name,
                legal_name=command.legal_name,
                organization_type=command.organization_type,
                registration_number=command.registration_number,
                vat_number=command.vat_number,
                country=command.country,
                timezone=command.timezone,
                currency=command.currency,
            )

            OrganizationConfiguration.objects.create(
                organization=organization,
                default_currency=command.currency,
                default_timezone=command.timezone,
            )

            AuditService.record(
                event_type="organization.created",
                message=f"Organization created: {organization.name}",
                organization=organization,
                object_type="Organization",
                object_id=str(organization.id),
                metadata={"organization_uuid": str(organization.uuid)},
            )

            return organization
