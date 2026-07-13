from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch

from apps.accounting.models import AccountingDimension, AccountingGLAllocation, AccountingGLBatch, AccountingGLEntry, AccountingIntegration
from apps.accounting.services import ProjectCodeSuggestion
from apps.core.models import AuditEvent
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.projects.services import (
    ChangeProjectStatusCommand,
    CreateProjectFromAccountingDimensionCommand,
    CreateProjectWithSuggestedCodeCommand,
    ProjectDimensionImportService,
    ProjectCreationService,
    ProjectStatusService,
)

from .models import Project, ProjectAddress, ProjectParty


def create_organization(name="Projects Org"):
    return OrganizationService.create(CreateOrganizationCommand(name=name))


def create_project(organization=None, code="26070", name="Kanarbiku"):
    organization = organization or create_organization()
    return Project.objects.create(
        organization=organization,
        code=code,
        name=name,
    )


def create_integration(organization):
    return AccountingIntegration.objects.create(
        organization=organization,
        provider=AccountingIntegration.Provider.MERIT,
        display_name="Merit",
        api_base_url="https://merit.example.test",
    )


def create_gl_allocation(organization, code, dimension=None, project=None, amount="100.000000"):
    integration = dimension.integration if dimension and dimension.integration else create_integration(organization)
    batch = AccountingGLBatch.objects.create(
        organization=organization,
        integration=integration,
        external_id=f"batch-{code}-{AccountingGLBatch.objects.count()}",
        batch_date=timezone.datetime(2026, 6, 1).date(),
        currency_code="EUR",
    )
    entry = AccountingGLEntry.objects.create(
        organization=organization,
        integration=integration,
        batch=batch,
        external_id=f"entry-{code}-{AccountingGLEntry.objects.count()}",
        account_code="4000",
        account_name="Materials",
    )
    return AccountingGLAllocation.objects.create(
        organization=organization,
        integration=integration,
        entry=entry,
        external_id=f"allocation-{code}-{AccountingGLAllocation.objects.count()}",
        dimension_code=code,
        dimension_name=dimension.name if dimension else "",
        amount=amount,
        accounting_dimension=dimension,
        project=project,
    )


class ProjectModelTests(TestCase):
    def test_can_create_project(self):
        organization = create_organization()

        project = Project.objects.create(
            organization=organization,
            code="26070",
            name="Kanarbiku",
            description="Shared business context for project work.",
            status=Project.Status.ACTIVE,
            project_type=Project.Type.ELECTRICAL,
            metadata={"source": "test"},
        )

        self.assertIsNotNone(project.id)
        self.assertIsNotNone(project.uuid)
        self.assertEqual(project.organization, organization)
        self.assertEqual(project.metadata, {"source": "test"})

    def test_default_status_is_active(self):
        organization = create_organization()

        project = Project.objects.create(
            organization=organization,
            code="26071",
            name="Default status",
        )

        self.assertEqual(project.status, Project.Status.ACTIVE)

    def test_default_project_type_is_other(self):
        organization = create_organization()

        project = Project.objects.create(
            organization=organization,
            code="26072",
            name="Default type",
        )

        self.assertEqual(project.project_type, Project.Type.OTHER)

    def test_organization_code_uniqueness(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26073", name="First")

        with self.assertRaises(IntegrityError):
            Project.objects.create(organization=organization, code="26073", name="Duplicate")

    def test_same_code_allowed_for_different_organizations(self):
        organization = create_organization(name="Projects Org A")
        other_organization = create_organization(name="Projects Org B")
        Project.objects.create(organization=organization, code="26074", name="First")

        project = Project.objects.create(organization=other_organization, code="26074", name="Second")

        self.assertIsNotNone(project.id)

    def test_str_includes_code_and_name(self):
        organization = create_organization()

        project = Project.objects.create(
            organization=organization,
            code="26075",
            name="Readable project",
        )

        self.assertEqual(str(project), "26075 - Readable project")

    def test_start_date_and_end_date_can_be_null(self):
        organization = create_organization()

        project = Project.objects.create(
            organization=organization,
            code="26076",
            name="No dates",
        )

        self.assertIsNone(project.start_date)
        self.assertIsNone(project.end_date)


class ProjectPartyModelTests(TestCase):
    def test_can_create_project_party(self):
        project = create_project()

        party = ProjectParty.objects.create(
            organization=project.organization,
            project=project,
            name="Supplier Contact",
            email="supplier@example.com",
            phone="+372 5555 0000",
            role=ProjectParty.Role.SUPPLIER,
            company_name="Supplier OÜ",
            external_reference="supplier-123",
            metadata={"source": "test"},
        )

        self.assertIsNotNone(party.id)
        self.assertEqual(party.project, project)
        self.assertEqual(party.organization, project.organization)
        self.assertEqual(party.company_name, "Supplier OÜ")
        self.assertEqual(party.metadata, {"source": "test"})

    def test_default_role_is_other(self):
        project = create_project()

        party = ProjectParty.objects.create(
            organization=project.organization,
            project=project,
            name="Unknown Role",
        )

        self.assertEqual(party.role, ProjectParty.Role.OTHER)

    def test_default_is_active_is_true(self):
        project = create_project()

        party = ProjectParty.objects.create(
            organization=project.organization,
            project=project,
            name="Active Person",
        )

        self.assertTrue(party.is_active)

    def test_links_to_project(self):
        project = create_project()

        party = ProjectParty.objects.create(
            organization=project.organization,
            project=project,
            name="Project Manager",
            role=ProjectParty.Role.PROJECT_MANAGER,
        )

        self.assertEqual(party.project, project)
        self.assertEqual(project.parties.get(), party)

    def test_links_to_organization(self):
        project = create_project()

        party = ProjectParty.objects.create(
            organization=project.organization,
            project=project,
            name="Electrician",
            role=ProjectParty.Role.ELECTRICIAN,
        )

        self.assertEqual(party.organization, project.organization)
        self.assertEqual(project.organization.project_parties.get(), party)

    def test_str_includes_name_and_role(self):
        project = create_project()

        party = ProjectParty.objects.create(
            organization=project.organization,
            project=project,
            name="Owner Supervisor",
            role=ProjectParty.Role.OWNER_SUPERVISOR,
        )

        self.assertEqual(str(party), "Owner Supervisor (owner_supervisor)")


class ProjectAddressModelTests(TestCase):
    def test_can_create_project_address(self):
        project = create_project()

        address = ProjectAddress.objects.create(
            organization=project.organization,
            project=project,
            address_type=ProjectAddress.Type.SITE,
            label="Main site",
            country="EE",
            city="Tallinn",
            street="Example street 1",
            postal_code="10111",
            latitude=59.437000,
            longitude=24.753600,
            is_primary=True,
            metadata={"source": "test"},
        )

        self.assertIsNotNone(address.id)
        self.assertEqual(address.project, project)
        self.assertEqual(address.organization, project.organization)
        self.assertEqual(address.city, "Tallinn")
        self.assertEqual(address.metadata, {"source": "test"})

    def test_default_address_type_is_site(self):
        project = create_project()

        address = ProjectAddress.objects.create(
            organization=project.organization,
            project=project,
        )

        self.assertEqual(address.address_type, ProjectAddress.Type.SITE)

    def test_default_country_is_ee(self):
        project = create_project()

        address = ProjectAddress.objects.create(
            organization=project.organization,
            project=project,
        )

        self.assertEqual(address.country, "EE")

    def test_default_is_primary_is_false(self):
        project = create_project()

        address = ProjectAddress.objects.create(
            organization=project.organization,
            project=project,
        )

        self.assertFalse(address.is_primary)

    def test_links_to_project(self):
        project = create_project()

        address = ProjectAddress.objects.create(
            organization=project.organization,
            project=project,
            street="Project street 1",
        )

        self.assertEqual(address.project, project)
        self.assertEqual(project.addresses.get(), address)

    def test_links_to_organization(self):
        project = create_project()

        address = ProjectAddress.objects.create(
            organization=project.organization,
            project=project,
            street="Organization street 1",
        )

        self.assertEqual(address.organization, project.organization)
        self.assertEqual(project.organization.project_addresses.get(), address)

    def test_latitude_and_longitude_can_be_null(self):
        project = create_project()

        address = ProjectAddress.objects.create(
            organization=project.organization,
            project=project,
        )

        self.assertIsNone(address.latitude)
        self.assertIsNone(address.longitude)

    def test_str_includes_project_code_and_address_type(self):
        project = create_project(code="26080")

        address = ProjectAddress.objects.create(
            organization=project.organization,
            project=project,
            address_type=ProjectAddress.Type.BILLING,
            label="Billing address",
        )

        self.assertEqual(str(address), "26080 billing: Billing address")


class ProjectCreationServiceTests(TestCase):
    def test_creates_project_with_next_suggested_code(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Existing")

        result = ProjectCreationService.create_with_suggested_code(
            CreateProjectWithSuggestedCodeCommand(
                organization=organization,
                name="New project",
            )
        )

        self.assertEqual(result.suggested_code, "26125")
        self.assertEqual(result.project.code, "26125")
        self.assertEqual(result.project.name, "New project")

    def test_uses_project_code_allocation_service_result(self):
        organization = create_organization()
        allocation = ProjectCodeSuggestion(
            suggested_code="27001",
            used_codes=["27000"],
            source_summary={"source": "mocked"},
        )

        with patch(
            "apps.projects.services.project_creation.ProjectCodeAllocationService.suggest_next_code",
            return_value=allocation,
        ) as suggest_next_code:
            result = ProjectCreationService.create_with_suggested_code(
                CreateProjectWithSuggestedCodeCommand(
                    organization=organization,
                    name="Mocked allocation",
                    min_code=27000,
                    prefix="27",
                )
            )

        suggest_next_code.assert_called_once()
        self.assertEqual(result.project.code, "27001")
        self.assertEqual(result.allocation_summary, {"source": "mocked"})

    def test_respects_min_code(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Existing")

        result = ProjectCreationService.create_with_suggested_code(
            CreateProjectWithSuggestedCodeCommand(
                organization=organization,
                name="Minimum code project",
                min_code=27000,
            )
        )

        self.assertEqual(result.project.code, "27000")

    def test_respects_prefix_if_supported_by_allocator(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26001", name="Existing 1")
        Project.objects.create(organization=organization, code="26002", name="Existing 2")
        Project.objects.create(organization=organization, code="27099", name="Other prefix")

        result = ProjectCreationService.create_with_suggested_code(
            CreateProjectWithSuggestedCodeCommand(
                organization=organization,
                name="Prefixed project",
                prefix="26",
            )
        )

        self.assertEqual(result.project.code, "26003")

    def test_stores_project_fields(self):
        organization = create_organization()

        result = ProjectCreationService.create_with_suggested_code(
            CreateProjectWithSuggestedCodeCommand(
                organization=organization,
                name="Detailed project",
                description="Project description",
                project_type=Project.Type.ELECTRICAL,
                status=Project.Status.PLANNED,
            )
        )

        project = result.project
        self.assertEqual(project.name, "Detailed project")
        self.assertEqual(project.description, "Project description")
        self.assertEqual(project.project_type, Project.Type.ELECTRICAL)
        self.assertEqual(project.status, Project.Status.PLANNED)

    def test_creates_audit_event(self):
        organization = create_organization()

        result = ProjectCreationService.create_with_suggested_code(
            CreateProjectWithSuggestedCodeCommand(
                organization=organization,
                name="Audited project",
            )
        )

        audit_event = AuditEvent.objects.get(
            event_type="project.created_with_suggested_code",
            object_type="Project",
            object_id=str(result.project.id),
        )
        self.assertEqual(audit_event.organization, organization)
        self.assertEqual(audit_event.metadata["suggested_code"], result.suggested_code)

    def test_metadata_is_not_mutated(self):
        organization = create_organization()
        metadata = {"source": {"requested_by": "test"}}
        original_metadata = {"source": {"requested_by": "test"}}

        result = ProjectCreationService.create_with_suggested_code(
            CreateProjectWithSuggestedCodeCommand(
                organization=organization,
                name="Metadata project",
                metadata=metadata,
            )
        )

        result.metadata["source"] = "changed"
        self.assertEqual(metadata, original_metadata)

    def test_transaction_rollback(self):
        organization = create_organization()

        with patch(
            "apps.projects.services.project_creation.AuditService.record",
            side_effect=RuntimeError("audit failed"),
        ):
            with self.assertRaises(RuntimeError):
                ProjectCreationService.create_with_suggested_code(
                    CreateProjectWithSuggestedCodeCommand(
                        organization=organization,
                        name="Rolled back project",
                    )
                )

        self.assertFalse(Project.objects.filter(name="Rolled back project").exists())

    def test_does_not_create_accounting_dimension(self):
        organization = create_organization()
        dimension_count = AccountingDimension.objects.count()

        ProjectCreationService.create_with_suggested_code(
            CreateProjectWithSuggestedCodeCommand(
                organization=organization,
                name="No dimension project",
            )
        )

        self.assertEqual(AccountingDimension.objects.count(), dimension_count)


class ProjectStatusServiceTests(TestCase):
    def test_active_project_can_be_completed(self):
        project = create_project()

        result = ProjectStatusService.change_status(
            ChangeProjectStatusCommand(
                project=project,
                new_status=Project.Status.COMPLETED,
                reason="Work finished",
            )
        )

        project.refresh_from_db()
        self.assertTrue(result.changed)
        self.assertEqual(result.previous_status, Project.Status.ACTIVE)
        self.assertEqual(project.status, Project.Status.COMPLETED)

    def test_completed_project_can_be_reopened(self):
        project = create_project()
        project.status = Project.Status.COMPLETED
        project.save(update_fields=["status", "updated_at"])

        ProjectStatusService.change_status(
            ChangeProjectStatusCommand(project=project, new_status=Project.Status.ACTIVE)
        )

        project.refresh_from_db()
        self.assertEqual(project.status, Project.Status.ACTIVE)

    def test_archived_project_can_be_reopened(self):
        project = create_project()
        project.status = Project.Status.ARCHIVED
        project.save(update_fields=["status", "updated_at"])

        ProjectStatusService.change_status(
            ChangeProjectStatusCommand(project=project, new_status=Project.Status.ACTIVE)
        )

        project.refresh_from_db()
        self.assertEqual(project.status, Project.Status.ACTIVE)

    def test_same_status_is_idempotent_and_not_audited(self):
        project = create_project()
        audit_count = AuditEvent.objects.count()

        result = ProjectStatusService.change_status(
            ChangeProjectStatusCommand(project=project, new_status=Project.Status.ACTIVE)
        )

        project.refresh_from_db()
        self.assertFalse(result.changed)
        self.assertEqual(project.status, Project.Status.ACTIVE)
        self.assertEqual(AuditEvent.objects.count(), audit_count)

    def test_invalid_transition_raises_clear_error(self):
        project = create_project()

        with self.assertRaises(ValueError):
            ProjectStatusService.change_status(
                ChangeProjectStatusCommand(project=project, new_status=Project.Status.PLANNED)
            )

    def test_status_change_creates_audit_event_with_reason(self):
        project = create_project()

        ProjectStatusService.change_status(
            ChangeProjectStatusCommand(
                project=project,
                new_status=Project.Status.ARCHIVED,
                reason="No longer in daily work",
            )
        )

        audit_event = AuditEvent.objects.get(event_type="project.status_changed")
        self.assertEqual(audit_event.object_id, str(project.id))
        self.assertEqual(audit_event.metadata["project_code"], project.code)
        self.assertEqual(audit_event.metadata["previous_status"], Project.Status.ACTIVE)
        self.assertEqual(audit_event.metadata["new_status"], Project.Status.ARCHIVED)
        self.assertEqual(audit_event.metadata["reason"], "No longer in daily work")

    def test_status_change_does_not_deactivate_accounting_dimension(self):
        project = create_project()
        dimension = AccountingDimension.objects.create(
            organization=project.organization,
            code=project.code,
            name=project.name,
            is_active=True,
        )

        ProjectStatusService.change_status(
            ChangeProjectStatusCommand(project=project, new_status=Project.Status.COMPLETED)
        )

        dimension.refresh_from_db()
        self.assertTrue(dimension.is_active)


class ProjectDimensionImportServiceTests(TestCase):
    def test_creates_project_from_accounting_dimension(self):
        organization = create_organization()
        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="27001",
            name="Merit project",
        )

        result = ProjectDimensionImportService.create_project(
            CreateProjectFromAccountingDimensionCommand(accounting_dimension=dimension)
        )

        self.assertTrue(result.created)
        self.assertEqual(result.project.organization, organization)
        self.assertEqual(result.project.code, "27001")
        self.assertEqual(result.project.name, "Merit project")
        self.assertEqual(result.project.status, Project.Status.ACTIVE)
        self.assertEqual(result.project.project_type, Project.Type.ELECTRICAL)

    def test_existing_project_is_not_duplicated(self):
        organization = create_organization()
        existing = create_project(organization, code="27002", name="Existing")
        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="27002",
            name="Merit project",
        )

        result = ProjectDimensionImportService.create_project(
            CreateProjectFromAccountingDimensionCommand(accounting_dimension=dimension)
        )

        self.assertFalse(result.created)
        self.assertEqual(result.project, existing)
        self.assertEqual(Project.objects.filter(organization=organization, code="27002").count(), 1)

    def test_non_project_dimension_is_rejected(self):
        organization = create_organization()
        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="D001",
            name="Department",
            dimension_type=AccountingDimension.DimensionType.DEPARTMENT,
        )

        with self.assertRaises(ValueError):
            ProjectDimensionImportService.create_project(
                CreateProjectFromAccountingDimensionCommand(accounting_dimension=dimension)
            )

        self.assertFalse(Project.objects.filter(code="D001").exists())

    def test_creates_audit_event(self):
        organization = create_organization()
        dimension = AccountingDimension.objects.create(organization=organization, code="27003", name="Audited")

        result = ProjectDimensionImportService.create_project(
            CreateProjectFromAccountingDimensionCommand(accounting_dimension=dimension)
        )

        audit = AuditEvent.objects.get(event_type="project.created_from_accounting_dimension")
        self.assertEqual(audit.object_id, str(result.project.id))
        self.assertEqual(audit.metadata["accounting_dimension_id"], dimension.id)
        self.assertEqual(audit.metadata["created"], True)

    def test_metadata_is_not_mutated(self):
        organization = create_organization()
        dimension = AccountingDimension.objects.create(organization=organization, code="27004", name="Metadata")
        metadata = {"source": {"nested": "value"}}
        original = {"source": {"nested": "value"}}

        result = ProjectDimensionImportService.create_project(
            CreateProjectFromAccountingDimensionCommand(accounting_dimension=dimension, metadata=metadata)
        )
        result.metadata["source"] = "changed"

        self.assertEqual(metadata, original)

    def test_matching_gl_allocations_are_linked(self):
        organization = create_organization()
        integration = create_integration(organization)
        dimension = AccountingDimension.objects.create(
            organization=organization,
            integration=integration,
            code="27005",
            name="Allocation project",
        )
        matching = create_gl_allocation(organization, "27005", dimension=dimension)
        no_dimension_match = create_gl_allocation(organization, "27005")
        non_matching = create_gl_allocation(organization, "99999")

        result = ProjectDimensionImportService.create_project(
            CreateProjectFromAccountingDimensionCommand(accounting_dimension=dimension)
        )

        matching.refresh_from_db()
        no_dimension_match.refresh_from_db()
        non_matching.refresh_from_db()
        self.assertEqual(result.linked_allocation_count, 2)
        self.assertEqual(matching.project, result.project)
        self.assertEqual(no_dimension_match.project, result.project)
        self.assertIsNone(non_matching.project)

    def test_cross_organization_allocations_are_not_linked(self):
        organization = create_organization("Visible")
        other = create_organization("Other")
        dimension = AccountingDimension.objects.create(organization=organization, code="27006", name="Visible")
        other_allocation = create_gl_allocation(other, "27006")

        result = ProjectDimensionImportService.create_project(
            CreateProjectFromAccountingDimensionCommand(accounting_dimension=dimension)
        )

        other_allocation.refresh_from_db()
        self.assertEqual(result.linked_allocation_count, 0)
        self.assertIsNone(other_allocation.project)

    def test_api_is_not_called(self):
        organization = create_organization()
        dimension = AccountingDimension.objects.create(organization=organization, code="27007", name="No API")

        with patch("apps.accounting.connectors.MeritAPIClient.request") as request_mock:
            ProjectDimensionImportService.create_project(
                CreateProjectFromAccountingDimensionCommand(accounting_dimension=dimension)
            )

        request_mock.assert_not_called()

    def test_transaction_rollback(self):
        organization = create_organization()
        dimension = AccountingDimension.objects.create(organization=organization, code="27008", name="Rollback")

        with patch("apps.projects.services.dimension_import.AuditService.record", side_effect=RuntimeError("audit")):
            with self.assertRaises(RuntimeError):
                ProjectDimensionImportService.create_project(
                    CreateProjectFromAccountingDimensionCommand(accounting_dimension=dimension)
                )

        self.assertFalse(Project.objects.filter(code="27008").exists())
