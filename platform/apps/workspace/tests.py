from unittest.mock import patch

from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.communications.models import (
    EmailAccount,
    EmailAnswerDraft,
    EmailAttachment,
    EmailMessage,
    EmailProjectLink,
    EmailQuestion,
)
from apps.accounting.models import AccountingDimension
from apps.core.models import AuditEvent
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.documents.models import Document
from apps.knowledge.services import ProjectKnowledgeBuilder
from apps.projects.models import Project, ProjectAddress, ProjectParty
from apps.projects.services import CreateProjectWithSuggestedCodeResult
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
        body_text="Workspace body text",
        sender_email="sender@example.com",
        sender_name="Sender Name",
        recipients=["receiver@example.com"],
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


class InboxMVPTests(TestCase):
    def test_inbox_returns_200_with_empty_db(self):
        response = self.client.get(reverse("workspace:inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No emails found")

    def test_inbox_ux_polish_renders_search_and_review_columns(self):
        organization = create_organization()
        create_email_message(organization, subject="UX polish email")

        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "Search subject, sender, body")
        self.assertContains(response, "Project Status")
        self.assertContains(response, "Review")

    def test_inbox_lists_imported_email(self):
        organization = create_organization()
        create_email_message(organization, subject="Imported inbox email")

        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "Imported inbox email")
        self.assertContains(response, "Sender Name")

    def test_inbox_shows_project_suggestion(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Project suggestion email")
        project = create_project(organization, code="26100", name="Inbox Project")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            status=EmailProjectLink.Status.SUGGESTED,
            confidence=90,
        )

        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "26100")
        self.assertContains(response, "suggested")

    def test_inbox_shows_confidence(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Confidence email")
        project = create_project(organization, code="26101", name="Confidence Project")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            confidence=75,
        )

        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "75%")

    def test_inbox_shows_question_count(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Question count email")
        EmailQuestion.objects.create(
            organization=organization,
            email_message=message,
            question_text="Kas saaks kinnitada?",
        )

        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "Question count email")
        self.assertContains(response, ">1<", html=False)

    def test_filter_has_questions_works(self):
        organization = create_organization()
        message_with_question = create_email_message(organization, subject="Has question")
        create_email_message(organization, subject="No question")
        EmailQuestion.objects.create(
            organization=organization,
            email_message=message_with_question,
            question_text="Can you confirm?",
        )

        response = self.client.get(reverse("workspace:inbox"), {"filter": "has_questions"})

        self.assertContains(response, "Has question")
        self.assertNotContains(response, "No question")

    def test_filter_no_project_works(self):
        organization = create_organization()
        no_project_message = create_email_message(organization, subject="No project email")
        project_message = create_email_message(organization, subject="With project email")
        project = create_project(organization, code="26102", name="Linked Project")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=project_message,
            project=project,
        )

        response = self.client.get(reverse("workspace:inbox"), {"filter": "no_project"})

        self.assertContains(response, no_project_message.subject)
        self.assertNotContains(response, project_message.subject)

    def test_search_by_subject_works(self):
        organization = create_organization()
        create_email_message(organization, subject="Kanarbiku search email")
        create_email_message(organization, subject="Unrelated email")

        response = self.client.get(reverse("workspace:inbox"), {"q": "Kanarbiku"})

        self.assertContains(response, "Kanarbiku search email")
        self.assertNotContains(response, "Unrelated email")

    def test_email_detail_route_returns_200(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Detail route email")

        response = self.client.get(reverse("workspace:inbox_detail", kwargs={"email_id": message.id}))

        self.assertEqual(response.status_code, 200)

    def test_email_detail_shows_subject_body_and_evidence(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Evidence detail email")
        message.body_text = "Detail body content"
        message.save(update_fields=["body_text"])
        project = create_project(organization, code="26103", name="Evidence Project")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            confidence=90,
            evidence={"matched": "subject"},
        )
        EmailQuestion.objects.create(
            organization=organization,
            email_message=message,
            question_text="Please confirm?",
            evidence={"keyword": "please"},
        )
        EmailAttachment.objects.create(
            organization=organization,
            email_message=message,
            original_filename="evidence.pdf",
        )

        response = self.client.get(reverse("workspace:inbox_detail", kwargs={"email_id": message.id}))

        self.assertContains(response, "Evidence detail email")
        self.assertContains(response, "Detail body content")
        self.assertContains(response, "matched")
        self.assertContains(response, "Please confirm?")
        self.assertContains(response, "evidence.pdf")


class ManualEmailSyncTests(TestCase):
    def test_sync_endpoint_requires_post(self):
        response = self.client.get(reverse("workspace:inbox_sync"))

        self.assertEqual(response.status_code, 405)

    @patch("apps.workspace.views.EmailSyncService.sync")
    def test_sync_endpoint_calls_email_sync_service(self, sync_mock):
        sync_mock.return_value = {
            "fetched_count": 2,
            "imported_count": 1,
            "processed_count": 1,
        }
        organization = create_organization()
        account = create_email_account(organization)

        self.client.post(reverse("workspace:inbox_sync"))

        sync_mock.assert_called_once()
        command = sync_mock.call_args.args[0]
        self.assertEqual(command.email_account, account)
        self.assertEqual(command.limit, 10)
        self.assertTrue(command.process_imported)

    @patch("apps.workspace.views.EmailSyncService.sync")
    def test_sync_success_redirects_and_message_contains_counts(self, sync_mock):
        sync_mock.return_value = {
            "fetched_count": 3,
            "imported_count": 2,
            "processed_count": 1,
        }
        organization = create_organization()
        create_email_account(organization)

        response = self.client.post(reverse("workspace:inbox_sync"), follow=True)

        self.assertRedirects(response, reverse("workspace:inbox"))
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("fetched 3" in message for message in messages))
        self.assertTrue(any("imported 2" in message for message in messages))
        self.assertTrue(any("processed 1" in message for message in messages))

    def test_sync_no_active_account_handled(self):
        response = self.client.post(reverse("workspace:inbox_sync"), follow=True)

        self.assertRedirects(response, reverse("workspace:inbox"))
        self.assertContains(response, "No active email account is configured yet")

    @patch("apps.workspace.views.EmailSyncService.sync")
    def test_sync_error_handled(self, sync_mock):
        sync_mock.side_effect = RuntimeError("secret connection detail")
        organization = create_organization()
        create_email_account(organization)

        response = self.client.post(reverse("workspace:inbox_sync"), follow=True)

        self.assertRedirects(response, reverse("workspace:inbox"))
        self.assertContains(response, "Email sync failed")
        self.assertNotContains(response, "secret connection detail")

    def test_dashboard_renders_sync_button(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Sync now")
        self.assertContains(response, reverse("workspace:inbox_sync"))
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_inbox_renders_sync_button(self):
        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "Sync now")
        self.assertContains(response, reverse("workspace:inbox_sync"))
        self.assertContains(response, "csrfmiddlewaretoken")


class ProjectListManagementUITests(TestCase):
    def test_projects_page_returns_200(self):
        response = self.client.get(reverse("workspace:projects"))

        self.assertEqual(response.status_code, 200)

    def test_project_list_shows_existing_project(self):
        organization = create_organization()
        create_project(organization, code="26124", name="Kanarbiku")

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "26124")
        self.assertContains(response, "Kanarbiku")

    def test_accounting_dimension_cache_appears(self):
        organization = create_organization()
        AccountingDimension.objects.create(
            organization=organization,
            code="26125",
            name="Merit cached project",
        )

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "26125")
        self.assertContains(response, "Merit cached project")
        self.assertContains(response, "Merit cache")

    def test_dimension_with_matching_project_shows_linked(self):
        organization = create_organization()
        create_project(organization, code="26126", name="Linked project")
        AccountingDimension.objects.create(
            organization=organization,
            code="26126",
            name="Linked project",
        )

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "linked")

    def test_dimension_without_project_shows_missing_in_workspace(self):
        organization = create_organization()
        AccountingDimension.objects.create(
            organization=organization,
            code="26127",
            name="Missing Workspace project",
        )

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "missing_in_workspace")

    def test_workspace_project_without_dimension_shows_workspace_only(self):
        organization = create_organization()
        create_project(organization, code="26128", name="Workspace only project")

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "workspace_only")

    def test_create_page_returns_200(self):
        create_organization()

        response = self.client.get(reverse("workspace:project_create"))

        self.assertEqual(response.status_code, 200)

    def test_suggested_code_is_shown(self):
        organization = create_organization()
        create_project(organization, code="26129", name="Existing project")

        response = self.client.get(reverse("workspace:project_create"))

        self.assertContains(response, "Suggested next code")
        self.assertContains(response, "26130")

    @patch("apps.workspace.views.ProjectCreationService.create_with_suggested_code")
    def test_submit_creates_project_through_service(self, create_mock):
        organization = create_organization()
        project = Project(
            id=1,
            organization=organization,
            code="26131",
            name="Created through service",
        )
        create_mock.return_value = CreateProjectWithSuggestedCodeResult(
            project=project,
            suggested_code="26131",
            allocation_summary={},
        )

        response = self.client.post(
            reverse("workspace:project_create"),
            {
                "name": "Created through service",
                "description": "Created from UI",
                "project_type": Project.Type.ELECTRICAL,
                "status": Project.Status.PLANNED,
                "min_code": "26131",
                "prefix": "26",
            },
        )

        self.assertRedirects(response, reverse("workspace:projects"))
        create_mock.assert_called_once()
        command = create_mock.call_args.args[0]
        self.assertEqual(command.organization, organization)
        self.assertEqual(command.name, "Created through service")
        self.assertEqual(command.description, "Created from UI")
        self.assertEqual(command.project_type, Project.Type.ELECTRICAL)
        self.assertEqual(command.status, Project.Status.PLANNED)
        self.assertEqual(command.min_code, "26131")
        self.assertEqual(command.prefix, "26")

    def test_project_detail_page_returns_200(self):
        organization = create_organization()
        project = create_project(organization, code="26132", name="Detail project")

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Detail project")
        self.assertContains(response, "Parties")
        self.assertContains(response, "Communications")

    def test_filter_active_works(self):
        organization = create_organization()
        create_project(organization, code="26133", name="Active project")
        Project.objects.create(
            organization=organization,
            code="26134",
            name="Planned project",
            status=Project.Status.PLANNED,
        )

        response = self.client.get(reverse("workspace:projects"), {"filter": "active"})

        self.assertContains(response, "Active project")
        self.assertNotContains(response, "Planned project")

    def test_filter_missing_in_workspace_works(self):
        organization = create_organization()
        create_project(organization, code="26135", name="Workspace project")
        AccountingDimension.objects.create(
            organization=organization,
            code="26136",
            name="Missing project dimension",
        )

        response = self.client.get(reverse("workspace:projects"), {"filter": "missing_in_workspace"})

        self.assertContains(response, "Missing project dimension")
        self.assertNotContains(response, "26135")

    def test_search_works(self):
        organization = create_organization()
        create_project(organization, code="26137", name="Searchable Workspace")
        AccountingDimension.objects.create(
            organization=organization,
            code="26138",
            name="Searchable Dimension",
        )
        create_project(organization, code="26139", name="Other project")

        response = self.client.get(reverse("workspace:projects"), {"q": "Dimension"})

        self.assertContains(response, "Searchable Dimension")
        self.assertNotContains(response, "Searchable Workspace")
        self.assertNotContains(response, "Other project")


class ProjectWorkspaceTests(TestCase):
    def test_project_workspace_returns_200(self):
        organization = create_organization()
        project = create_project(organization, code="26200", name="Workspace detail")

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertEqual(response.status_code, 200)

    def test_overview_shows_project_code_and_name(self):
        organization = create_organization()
        project = create_project(organization, code="26201", name="Overview project")

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "26201")
        self.assertContains(response, "Overview project")
        self.assertContains(response, "Overview")

    def test_shows_parties(self):
        organization = create_organization()
        project = create_project(organization, code="26202", name="People project")
        ProjectParty.objects.create(
            organization=organization,
            project=project,
            role=ProjectParty.Role.SUPPLIER,
            name="Project Supplier",
            company_name="Supplier OÜ",
            email="supplier@example.com",
            phone="+372 5555",
        )

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "Project Supplier")
        self.assertContains(response, "supplier")
        self.assertContains(response, "Supplier OÜ")

    def test_shows_addresses(self):
        organization = create_organization()
        project = create_project(organization, code="26203", name="Address project")
        ProjectAddress.objects.create(
            organization=organization,
            project=project,
            address_type=ProjectAddress.Type.SITE,
            label="Main site",
            city="Tallinn",
            street="Example 1",
            is_primary=True,
        )

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "Main site")
        self.assertContains(response, "Tallinn")
        self.assertContains(response, "primary")

    def test_shows_related_emails(self):
        organization = create_organization()
        project = create_project(organization, code="26204", name="Email project")
        message = create_email_message(organization, subject="Project communication")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            confidence=88,
            status=EmailProjectLink.Status.SUGGESTED,
        )

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "Project communication")
        self.assertContains(response, "88%")
        self.assertContains(response, "suggested")

    def test_shows_questions(self):
        organization = create_organization()
        project = create_project(organization, code="26205", name="Question project")
        message = create_email_message(organization, subject="Question communication")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
        )
        EmailQuestion.objects.create(
            organization=organization,
            email_message=message,
            question_text="Kas saab kinnitada?",
            evidence={"keyword": "kas"},
        )

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "Questions")
        self.assertContains(response, ">1<", html=False)

    def test_shows_evidence(self):
        organization = create_organization()
        project = create_project(organization, code="26206", name="Evidence project")
        message = create_email_message(organization, subject="Evidence communication")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            confidence=90,
            evidence={"matched_project_code": "26206"},
        )

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "Evidence")
        self.assertContains(response, "email_project_link")
        self.assertContains(response, "matched_project_code")

    def test_shows_documents_when_attachments_linked_to_documents(self):
        organization = create_organization()
        project = create_project(organization, code="26207", name="Document project")
        message = create_email_message(organization, subject="Document communication")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
        )
        document = Document.objects.create(
            organization=organization,
            title="Project contract",
            original_filename="contract.pdf",
            source=Document.Source.MANUAL_UPLOAD,
            status=Document.Status.PARSED,
        )
        EmailAttachment.objects.create(
            organization=organization,
            email_message=message,
            document=document,
            original_filename="contract.pdf",
        )

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "Project contract")
        self.assertContains(response, "contract.pdf")
        self.assertContains(response, "parsed")

    def test_empty_project_renders_empty_states(self):
        organization = create_organization()
        project = create_project(organization, code="26208", name="Empty project")

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "No timeline yet")
        self.assertContains(response, "No related emails")
        self.assertContains(response, "No related documents")
        self.assertContains(response, "No people yet")
        self.assertContains(response, "No addresses yet")
        self.assertContains(response, "No evidence yet")

    def test_project_knowledge_builder_is_used(self):
        organization = create_organization()
        project = create_project(organization, code="26209", name="Knowledge builder project")

        with patch(
            "apps.workspace.services.projects.ProjectKnowledgeBuilder.build",
            wraps=ProjectKnowledgeBuilder.build,
        ) as build_mock:
            response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertEqual(response.status_code, 200)
        build_mock.assert_called_once()


class ProjectLinkReviewUITests(TestCase):
    def _suggested_link(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Review suggestion email")
        suggested_project = create_project(organization, code="26300", name="Suggested Project")
        other_project = create_project(organization, code="26301", name="Correct Project")
        link = EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=suggested_project,
            status=EmailProjectLink.Status.SUGGESTED,
            confidence=91,
            evidence={"matched_project_code": "26300"},
        )
        return link, other_project

    def test_confirm_endpoint_requires_post(self):
        link, _other_project = self._suggested_link()

        response = self.client.get(reverse("workspace:project_link_confirm", kwargs={"link_id": link.id}))

        self.assertEqual(response.status_code, 405)

    def test_reject_endpoint_requires_post(self):
        link, _other_project = self._suggested_link()

        response = self.client.get(reverse("workspace:project_link_reject", kwargs={"link_id": link.id}))

        self.assertEqual(response.status_code, 405)

    def test_correct_endpoint_requires_post(self):
        link, _other_project = self._suggested_link()

        response = self.client.get(reverse("workspace:project_link_correct", kwargs={"link_id": link.id}))

        self.assertEqual(response.status_code, 405)

    def test_confirm_changes_link_status(self):
        link, _other_project = self._suggested_link()

        response = self.client.post(
            reverse("workspace:project_link_confirm", kwargs={"link_id": link.id}),
            {"next": reverse("workspace:reviews")},
            follow=True,
        )

        link.refresh_from_db()
        self.assertRedirects(response, reverse("workspace:reviews"))
        self.assertEqual(link.status, EmailProjectLink.Status.CONFIRMED)
        self.assertIsNotNone(link.confirmed_at)

    def test_reject_changes_link_status(self):
        link, _other_project = self._suggested_link()

        response = self.client.post(
            reverse("workspace:project_link_reject", kwargs={"link_id": link.id}),
            {"reason": "Wrong project", "next": reverse("workspace:reviews")},
            follow=True,
        )

        link.refresh_from_db()
        self.assertRedirects(response, reverse("workspace:reviews"))
        self.assertEqual(link.status, EmailProjectLink.Status.REJECTED)
        self.assertEqual(link.metadata["rejection_reason"], "Wrong project")

    def test_correct_creates_confirmed_link_for_new_project(self):
        link, other_project = self._suggested_link()

        response = self.client.post(
            reverse("workspace:project_link_correct", kwargs={"link_id": link.id}),
            {
                "new_project_id": other_project.id,
                "reason": "Better match",
                "next": reverse("workspace:reviews"),
            },
            follow=True,
        )

        link.refresh_from_db()
        confirmed_link = EmailProjectLink.objects.get(email_message=link.email_message, project=other_project)
        self.assertRedirects(response, reverse("workspace:reviews"))
        self.assertEqual(link.status, EmailProjectLink.Status.CORRECTED)
        self.assertEqual(confirmed_link.status, EmailProjectLink.Status.CONFIRMED)

    def test_inbox_renders_confirm_action_for_suggested_link(self):
        self._suggested_link()

        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "Confirm")
        self.assertContains(response, "Reject")
        self.assertContains(response, "Change project")

    def test_email_detail_renders_project_link_actions(self):
        link, other_project = self._suggested_link()

        response = self.client.get(reverse("workspace:inbox_detail", kwargs={"email_id": link.email_message_id}))

        self.assertContains(response, "matched_project_code")
        self.assertContains(response, "Confirm")
        self.assertContains(response, "Reject")
        self.assertContains(response, f"{other_project.code} {other_project.name}")

    def test_reviews_page_lists_pending_project_links(self):
        link, _other_project = self._suggested_link()

        response = self.client.get(reverse("workspace:reviews"))

        self.assertContains(response, "Pending Project Link Suggestions")
        self.assertContains(response, link.email_message.subject)
        self.assertContains(response, "Suggested Project")
        self.assertContains(response, "matched_project_code")

    def test_messages_are_created(self):
        link, _other_project = self._suggested_link()

        response = self.client.post(
            reverse("workspace:project_link_confirm", kwargs={"link_id": link.id}),
            {"next": reverse("workspace:reviews")},
            follow=True,
        )

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Project link confirmed" in message for message in messages))

    def test_invalid_project_id_handled_safely(self):
        link, _other_project = self._suggested_link()

        response = self.client.post(
            reverse("workspace:project_link_correct", kwargs={"link_id": link.id}),
            {"new_project_id": "999999", "next": reverse("workspace:reviews")},
            follow=True,
        )

        link.refresh_from_db()
        self.assertEqual(link.status, EmailProjectLink.Status.SUGGESTED)
        self.assertContains(response, "choose a valid project")

    def test_no_get_mutation(self):
        link, _other_project = self._suggested_link()

        self.client.get(reverse("workspace:project_link_confirm", kwargs={"link_id": link.id}))

        link.refresh_from_db()
        self.assertEqual(link.status, EmailProjectLink.Status.SUGGESTED)


class EmailReplyDraftUITests(TestCase):
    def _email_with_question(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Reply draft email")
        question = EmailQuestion.objects.create(
            organization=organization,
            email_message=message,
            question_text="Can you confirm the schedule?",
            evidence={"keyword": "confirm"},
        )
        return message, question

    def _draft(self, status=EmailAnswerDraft.Status.DRAFT):
        message, question = self._email_with_question()
        draft = EmailAnswerDraft.objects.create(
            organization=message.organization,
            email_message=message,
            question=question,
            status=status,
            draft_text="Initial draft reply",
        )
        return draft

    def test_email_detail_shows_detected_questions(self):
        message, _question = self._email_with_question()

        response = self.client.get(reverse("workspace:inbox_detail", kwargs={"email_id": message.id}))

        self.assertContains(response, "Can you confirm the schedule?")
        self.assertContains(response, "Questions")

    def test_email_detail_shows_create_draft_form(self):
        message, _question = self._email_with_question()

        response = self.client.get(reverse("workspace:inbox_detail", kwargs={"email_id": message.id}))

        self.assertContains(response, "Create Draft Reply")
        self.assertContains(response, reverse("workspace:email_draft_create", kwargs={"email_id": message.id}))
        self.assertContains(response, 'name="draft_text"', html=False)

    def test_create_draft_endpoint_requires_post(self):
        message, _question = self._email_with_question()

        response = self.client.get(reverse("workspace:email_draft_create", kwargs={"email_id": message.id}))

        self.assertEqual(response.status_code, 405)

    def test_create_draft_creates_email_answer_draft(self):
        message, _question = self._email_with_question()

        response = self.client.post(
            reverse("workspace:email_draft_create", kwargs={"email_id": message.id}),
            {"draft_text": "Please find my reply below."},
            follow=True,
        )

        self.assertRedirects(response, reverse("workspace:inbox_detail", kwargs={"email_id": message.id}))
        draft = EmailAnswerDraft.objects.get(email_message=message)
        self.assertEqual(draft.draft_text, "Please find my reply below.")
        self.assertEqual(draft.generated_by, EmailAnswerDraft.GeneratedBy.RULE_BASED)

    def test_create_draft_includes_selected_question(self):
        message, question = self._email_with_question()

        self.client.post(
            reverse("workspace:email_draft_create", kwargs={"email_id": message.id}),
            {
                "question_id": question.id,
                "draft_text": "Question-specific reply.",
            },
        )

        draft = EmailAnswerDraft.objects.get(email_message=message)
        self.assertEqual(draft.question, question)

    def test_create_draft_stores_context_snapshot(self):
        message, question = self._email_with_question()
        project = create_project(message.organization, code="26400", name="Context Project")
        EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
            evidence={"matched_project_code": "26400"},
        )

        self.client.post(
            reverse("workspace:email_draft_create", kwargs={"email_id": message.id}),
            {"question_id": question.id, "draft_text": "Context-aware reply."},
        )

        draft = EmailAnswerDraft.objects.get(email_message=message)
        self.assertEqual(draft.context_snapshot["email_message_id"], message.id)
        self.assertEqual(draft.context_snapshot["question_ids"], [question.id])
        self.assertEqual(draft.context_snapshot["evidence_count"], 2)

    def test_needs_review_endpoint_requires_post(self):
        draft = self._draft()

        response = self.client.get(reverse("workspace:draft_needs_review", kwargs={"draft_id": draft.id}))

        self.assertEqual(response.status_code, 405)

    def test_approve_endpoint_requires_post(self):
        draft = self._draft()

        response = self.client.get(reverse("workspace:draft_approve", kwargs={"draft_id": draft.id}))

        self.assertEqual(response.status_code, 405)

    def test_reject_endpoint_requires_post(self):
        draft = self._draft()

        response = self.client.get(reverse("workspace:draft_reject", kwargs={"draft_id": draft.id}))

        self.assertEqual(response.status_code, 405)

    def test_needs_review_changes_status(self):
        draft = self._draft()

        response = self.client.post(
            reverse("workspace:draft_needs_review", kwargs={"draft_id": draft.id}),
            follow=True,
        )

        draft.refresh_from_db()
        self.assertRedirects(response, reverse("workspace:inbox_detail", kwargs={"email_id": draft.email_message_id}))
        self.assertEqual(draft.status, EmailAnswerDraft.Status.NEEDS_REVIEW)

    def test_approve_changes_status(self):
        draft = self._draft(status=EmailAnswerDraft.Status.NEEDS_REVIEW)

        response = self.client.post(
            reverse("workspace:draft_approve", kwargs={"draft_id": draft.id}),
            {"final_text": "Approved final reply"},
            follow=True,
        )

        draft.refresh_from_db()
        self.assertRedirects(response, reverse("workspace:inbox_detail", kwargs={"email_id": draft.email_message_id}))
        self.assertEqual(draft.status, EmailAnswerDraft.Status.APPROVED)
        self.assertEqual(draft.final_text, "Approved final reply")
        self.assertIsNotNone(draft.approved_at)

    def test_reject_changes_status(self):
        draft = self._draft(status=EmailAnswerDraft.Status.NEEDS_REVIEW)

        response = self.client.post(
            reverse("workspace:draft_reject", kwargs={"draft_id": draft.id}),
            {"reason": "Needs a better answer"},
            follow=True,
        )

        draft.refresh_from_db()
        self.assertRedirects(response, reverse("workspace:inbox_detail", kwargs={"email_id": draft.email_message_id}))
        self.assertEqual(draft.status, EmailAnswerDraft.Status.REJECTED)
        self.assertEqual(draft.metadata["rejection_reason"], "Needs a better answer")

    def test_reviews_page_lists_drafts_needing_review(self):
        draft = self._draft(status=EmailAnswerDraft.Status.NEEDS_REVIEW)

        response = self.client.get(reverse("workspace:reviews"))

        self.assertContains(response, "Answer Drafts Needing Review")
        self.assertContains(response, draft.email_message.subject)
        self.assertContains(response, "Initial draft reply")
        self.assertContains(response, reverse("workspace:draft_approve", kwargs={"draft_id": draft.id}))

    def test_no_get_mutation(self):
        draft = self._draft()

        self.client.get(reverse("workspace:draft_approve", kwargs={"draft_id": draft.id}))
        self.client.get(reverse("workspace:draft_reject", kwargs={"draft_id": draft.id}))
        self.client.get(reverse("workspace:draft_needs_review", kwargs={"draft_id": draft.id}))

        draft.refresh_from_db()
        self.assertEqual(draft.status, EmailAnswerDraft.Status.DRAFT)
