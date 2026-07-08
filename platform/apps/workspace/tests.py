from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.communications.models import EmailAccount, EmailAnswerDraft, EmailMessage, EmailProjectLink, EmailQuestion
from apps.core.models import AuditEvent
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.documents.models import Document
from apps.projects.models import Project
from apps.workflow.models import WorkflowDefinition, WorkflowInstance, WorkflowState


def create_organization(name="Workspace Org"):
    return OrganizationService.create(CreateOrganizationCommand(name=name))


def create_email_account(organization):
    return EmailAccount.objects.create(
        organization=organization,
        provider=EmailAccount.Provider.IMAP,
        display_name="Workspace mailbox",
        email_address="workspace@example.com",
    )


def create_email_message(organization, subject="Workspace email"):
    account = create_email_account(organization)
    return EmailMessage.objects.create(
        organization=organization,
        account=account,
        external_message_id=f"{subject}-id",
        subject=subject,
        sender_email="sender@example.com",
        received_at=timezone.now(),
    )


def create_project(organization, code="26070", name="Workspace Project"):
    return Project.objects.create(organization=organization, code=code, name=name)


class WorkspaceRouteTests(TestCase):
    routes = [
        ("workspace:home", "/workspace/"),
        ("workspace:dashboard", "/workspace/dashboard/"),
        ("workspace:inbox", "/workspace/inbox/"),
        ("workspace:projects", "/workspace/projects/"),
        ("workspace:documents", "/workspace/documents/"),
        ("workspace:reviews", "/workspace/reviews/"),
        ("workspace:search", "/workspace/search/"),
        ("workspace:assistant", "/workspace/assistant/"),
        ("workspace:settings", "/workspace/settings/"),
        ("workspace:design_system", "/workspace/design-system/"),
    ]

    def test_every_workspace_route_returns_http_200(self):
        for route_name, path in self.routes:
            with self.subTest(route_name=route_name):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)

    def test_url_namespace_works(self):
        for route_name, path in self.routes:
            with self.subTest(route_name=route_name):
                self.assertEqual(reverse(route_name), path)

    def test_templates_render_base_layout(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Operations Workspace Platform")
        self.assertContains(response, "Dashboard")
        self.assertContains(response, "workspace-content")

    def test_dashboard_cards_render(self):
        response = self.client.get(reverse("workspace:dashboard"))

        for title in [
            "Total Imported Emails",
            "Emails Needing Project Confirmation",
            "Detected Questions",
            "Answer Drafts Needing Review",
            "Active Projects",
            "Documents",
            "Workflow Instances",
            "Audit Events Today",
        ]:
            with self.subTest(title=title):
                self.assertContains(response, title)

    def test_design_system_page_returns_http_200(self):
        response = self.client.get(reverse("workspace:design_system"))

        self.assertEqual(response.status_code, 200)

    def test_design_system_template_renders_key_component_labels(self):
        response = self.client.get(reverse("workspace:design_system"))

        for label in [
            "Primary Button",
            "Cards",
            "Badges and Status Badges",
            "Design System Table",
            "No items yet",
            "Form Field Wrapper",
        ]:
            with self.subTest(label=label):
                self.assertContains(response, label)

    def test_navigation_contains_design_system_link(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Design System")
        self.assertContains(response, reverse("workspace:design_system"))


class DashboardMVPTests(TestCase):
    def test_dashboard_returns_200_with_empty_db(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No emails yet")
        self.assertContains(response, "No project suggestions yet")

    def test_dashboard_shows_email_count(self):
        organization = create_organization()
        create_email_message(organization, subject="Email count subject")

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Total Imported Emails")
        self.assertContains(response, "Email count subject")
        self.assertContains(response, ">1<", html=False)

    def test_dashboard_shows_project_count(self):
        organization = create_organization()
        create_project(organization, code="26080", name="Active dashboard project")

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Active Projects")
        self.assertContains(response, ">1<", html=False)

    def test_dashboard_shows_document_count(self):
        organization = create_organization()
        Document.objects.create(
            organization=organization,
            title="Dashboard document",
            original_filename="dashboard.pdf",
        )

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Documents")
        self.assertContains(response, "Dashboard document")

    def test_dashboard_shows_question_count(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Question email")
        EmailQuestion.objects.create(
            organization=organization,
            email_message=message,
            question_text="Can you confirm?",
        )

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Detected Questions")
        self.assertContains(response, "Can you confirm?")

    def test_dashboard_shows_project_suggestions(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Suggestion email")
        project = create_project(organization, code="26081", name="Suggested project")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            status=EmailProjectLink.Status.SUGGESTED,
            confidence=90,
        )

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Emails Needing Project Confirmation")
        self.assertContains(response, "Suggestion email")
        self.assertContains(response, "26081")
        self.assertContains(response, "90%")

    def test_dashboard_shows_recent_emails(self):
        organization = create_organization()
        create_email_message(organization, subject="Recent email")

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Latest 5 Emails")
        self.assertContains(response, "Recent email")

    def test_dashboard_uses_empty_states_when_no_data(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "No emails yet")
        self.assertContains(response, "No documents yet")

    def test_dashboard_shows_answer_drafts_workflow_and_audit_counts(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Draft email")
        EmailAnswerDraft.objects.create(
            organization=organization,
            email_message=message,
            status=EmailAnswerDraft.Status.NEEDS_REVIEW,
            draft_text="Draft needs review",
        )
        workflow = WorkflowDefinition.objects.create(code="dashboard", name="Dashboard workflow")
        state = WorkflowState.objects.create(workflow=workflow, code="new", name="New", is_initial=True)
        WorkflowInstance.objects.create(
            organization=organization,
            workflow=workflow,
            current_state=state,
            entity_type="email",
            entity_uuid=message.organization.uuid,
        )
        AuditEvent.objects.create(
            organization=organization,
            event_type="dashboard.test",
            object_type="EmailMessage",
            object_id=str(message.id),
            message="Dashboard audit",
        )

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Answer Drafts Needing Review")
        self.assertContains(response, "Workflow Instances")
        self.assertContains(response, "Audit Events Today")
        self.assertContains(response, "dashboard.test")
