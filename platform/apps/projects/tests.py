from django.db import IntegrityError
from django.test import TestCase

from apps.core.services import CreateOrganizationCommand, OrganizationService

from .models import Project, ProjectParty


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
