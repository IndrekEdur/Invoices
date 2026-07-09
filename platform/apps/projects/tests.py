from django.db import IntegrityError
from django.test import TestCase
from unittest.mock import patch

from apps.accounting.models import AccountingDimension
from apps.accounting.services import ProjectCodeSuggestion
from apps.core.models import AuditEvent
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.projects.services import CreateProjectWithSuggestedCodeCommand, ProjectCreationService

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
