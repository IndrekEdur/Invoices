from django.test import TestCase

from apps.accounting.models import AccountingIntegration
from apps.core.services import CreateOrganizationCommand, OrganizationService


def create_organization(name="Accounting Org"):
    return OrganizationService.create(CreateOrganizationCommand(name=name))


class AccountingIntegrationTests(TestCase):
    def test_can_create_integration(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Merit Aktiva",
            api_base_url="https://api.merit.ee/",
            api_id="test-api-id",
            encrypted_secret_placeholder="not-a-real-secret",
        )

        self.assertEqual(integration.display_name, "Merit Aktiva")

    def test_default_provider_is_merit(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Default provider",
        )

        self.assertEqual(integration.provider, AccountingIntegration.Provider.MERIT)

    def test_organization_linked(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Linked organization",
        )

        self.assertEqual(integration.organization, organization)

    def test_is_active_defaults_true(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Active integration",
        )

        self.assertTrue(integration.is_active)

    def test_str_works(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Merit production",
        )

        self.assertEqual(str(integration), "Merit production (merit)")

    def test_last_sync_at_can_be_null(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Never synced",
        )

        self.assertIsNone(integration.last_sync_at)
