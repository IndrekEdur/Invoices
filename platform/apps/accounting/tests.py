from django.db import IntegrityError
from django.test import TestCase

from apps.accounting.models import AccountingDimension, AccountingIntegration
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


class AccountingDimensionTests(TestCase):
    def test_can_create_accounting_dimension(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26124",
            name="Kanarbiku",
        )

        self.assertEqual(dimension.code, "26124")
        self.assertEqual(dimension.name, "Kanarbiku")

    def test_default_provider_is_merit(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26125",
            name="Default provider",
        )

        self.assertEqual(dimension.provider, AccountingDimension.Provider.MERIT)

    def test_default_dimension_type_is_project(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26126",
            name="Default type",
        )

        self.assertEqual(dimension.dimension_type, AccountingDimension.DimensionType.PROJECT)

    def test_is_active_defaults_true(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26127",
            name="Active dimension",
        )

        self.assertTrue(dimension.is_active)

    def test_organization_code_uniqueness_works(self):
        organization = create_organization()
        AccountingDimension.objects.create(
            organization=organization,
            code="26128",
            name="First dimension",
        )

        with self.assertRaises(IntegrityError):
            AccountingDimension.objects.create(
                organization=organization,
                code="26128",
                name="Duplicate dimension",
            )

    def test_external_id_can_be_null(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26129",
            name="No external id",
        )

        self.assertIsNone(dimension.external_id)

    def test_last_synced_at_can_be_null(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26130",
            name="Never synced",
        )

        self.assertIsNone(dimension.last_synced_at)

    def test_str_includes_code_and_name(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26131",
            name="Display name",
        )

        self.assertEqual(str(dimension), "26131 Display name")
