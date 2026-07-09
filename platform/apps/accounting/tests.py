from django.db import IntegrityError
from django.test import TestCase

from apps.accounting.models import AccountingDimension, AccountingIntegration
from apps.accounting.services import ProjectCodeAllocationService, SuggestNextProjectCodeCommand
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.projects.models import Project


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


class ProjectCodeAllocationServiceTests(TestCase):
    def test_suggests_next_code_from_projects(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Existing 1")
        Project.objects.create(organization=organization, code="26125", name="Existing 2")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26126")

    def test_suggests_next_code_from_accounting_dimensions(self):
        organization = create_organization()
        AccountingDimension.objects.create(organization=organization, code="26124", name="Existing 1")
        AccountingDimension.objects.create(organization=organization, code="26125", name="Existing 2")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26126")

    def test_merges_project_and_accounting_dimension_codes(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Workspace project")
        AccountingDimension.objects.create(organization=organization, code="26125", name="Merit dimension")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26126")
        self.assertEqual(suggestion.used_codes, ["26124", "26125"])

    def test_ignores_non_numeric_codes(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="ABC", name="Non numeric")
        AccountingDimension.objects.create(organization=organization, code="26125", name="Numeric")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26126")
        self.assertIn("ABC", suggestion.used_codes)

    def test_respects_min_code(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Existing")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization, min_code=27000)
        )

        self.assertEqual(suggestion.suggested_code, "27000")

    def test_prefix_considers_matching_codes_and_preserves_suffix_width(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26001", name="Matching 1")
        Project.objects.create(organization=organization, code="26002", name="Matching 2")
        Project.objects.create(organization=organization, code="27099", name="Other prefix")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization, prefix="26")
        )

        self.assertEqual(suggestion.suggested_code, "26003")

    def test_organization_isolation(self):
        organization = create_organization()
        other_organization = create_organization("Other Org")
        Project.objects.create(organization=other_organization, code="99999", name="Other")
        Project.objects.create(organization=organization, code="26124", name="Own")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26125")
        self.assertNotIn("99999", suggestion.used_codes)

    def test_inactive_dimensions_are_ignored_for_allocation(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Workspace project")
        AccountingDimension.objects.create(
            organization=organization,
            code="26125",
            name="Inactive dimension",
            is_active=False,
        )

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26125")
        self.assertNotIn("26125", suggestion.used_codes)

    def test_metadata_is_not_mutated(self):
        organization = create_organization()
        metadata = {"source": {"requested_by": "test"}}
        original_metadata = {"source": {"requested_by": "test"}}

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization, metadata=metadata)
        )

        suggestion.metadata["source"] = "changed"
        self.assertEqual(metadata, original_metadata)

    def test_returns_source_summary(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Workspace project")
        AccountingDimension.objects.create(organization=organization, code="26125", name="Merit dimension")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.source_summary["project_codes_count"], 1)
        self.assertEqual(suggestion.source_summary["accounting_dimension_codes_count"], 1)
        self.assertEqual(suggestion.source_summary["used_numeric_codes_count"], 2)

    def test_no_database_writes_except_test_setup(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Workspace project")
        project_count = Project.objects.count()
        dimension_count = AccountingDimension.objects.count()

        ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(Project.objects.count(), project_count)
        self.assertEqual(AccountingDimension.objects.count(), dimension_count)
