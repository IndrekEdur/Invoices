from django.test import TestCase
from django.utils import timezone

from apps.communications.models import (
    EmailAccount,
    EmailAnswerDraft,
    EmailAttachment,
    EmailMessage,
    EmailProjectLink,
    EmailQuestion,
    EmailThread,
)
from apps.core.models import AuditEvent
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.documents.models import Document
from apps.knowledge.dto import ProjectKnowledge
from apps.knowledge.services import BuildProjectKnowledgeCommand, ProjectKnowledgeBuilder
from apps.projects.models import Project, ProjectAddress, ProjectParty
from apps.workflow.models import WorkflowDefinition, WorkflowEvent, WorkflowInstance, WorkflowState


def create_organization(name="Knowledge Org"):
    return OrganizationService.create(CreateOrganizationCommand(name=name))


def create_project(organization=None, code="26070", name="Knowledge Project"):
    organization = organization or create_organization()
    return Project.objects.create(organization=organization, code=code, name=name)


def create_email_account(organization):
    return EmailAccount.objects.create(
        organization=organization,
        provider=EmailAccount.Provider.IMAP,
        display_name="Knowledge mailbox",
        email_address="knowledge@example.com",
    )


def create_email_message(project, subject="Project message", body_text="Body"):
    account = create_email_account(project.organization)
    thread = EmailThread.objects.create(
        organization=project.organization,
        account=account,
        external_thread_id=f"thread-{project.code}",
        subject=subject,
        normalized_subject=subject.lower(),
        message_count=1,
        last_message_at=timezone.now(),
    )
    message = EmailMessage.objects.create(
        organization=project.organization,
        account=account,
        thread=thread,
        external_message_id=f"message-{project.code}",
        subject=subject,
        body_text=body_text,
        received_at=timezone.now(),
    )
    EmailProjectLink.objects.create(
        organization=project.organization,
        email_message=message,
        project=project,
        confidence=90,
        evidence={"matches": [{"matched_field": "subject", "matched_project_code": project.code}]},
    )
    return message


def create_document(organization, title="Knowledge document"):
    return Document.objects.create(
        organization=organization,
        title=title,
        original_filename="document.txt",
        mime_type="text/plain",
        metadata={"source": "test"},
    )


def create_workflow_for_project(project):
    workflow = WorkflowDefinition.objects.create(code=f"project-{project.code}", name="Project workflow")
    state = WorkflowState.objects.create(workflow=workflow, code="received", name="Received", is_initial=True)
    instance = WorkflowInstance.objects.create(
        organization=project.organization,
        workflow=workflow,
        current_state=state,
        entity_type="project",
        entity_uuid=project.uuid,
    )
    event = WorkflowEvent.objects.create(
        workflow_instance=instance,
        state=state,
        event_type=WorkflowEvent.Type.WORKFLOW_STARTED,
        message="Started",
    )
    return instance, event


class ProjectKnowledgeBuilderTests(TestCase):
    def test_empty_project(self):
        project = create_project()

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        self.assertIsInstance(knowledge, ProjectKnowledge)
        self.assertEqual(knowledge.project, project)
        self.assertEqual(knowledge.parties, ())
        self.assertEqual(knowledge.addresses, ())
        self.assertEqual(knowledge.emails, ())
        self.assertEqual(knowledge.timeline, ())

    def test_project_with_addresses(self):
        project = create_project()
        address = ProjectAddress.objects.create(
            organization=project.organization,
            project=project,
            street="Knowledge street 1",
        )

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        self.assertEqual(knowledge.addresses, (address,))

    def test_project_with_parties(self):
        project = create_project()
        party = ProjectParty.objects.create(
            organization=project.organization,
            project=project,
            name="Project supplier",
            role=ProjectParty.Role.SUPPLIER,
        )

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        self.assertEqual(knowledge.parties, (party,))

    def test_project_with_emails(self):
        project = create_project()
        message = create_email_message(project)

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        self.assertEqual(knowledge.emails, (message,))
        self.assertEqual(knowledge.threads, (message.thread,))

    def test_project_with_conversation_contexts(self):
        project = create_project()
        message = create_email_message(project)

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        self.assertEqual(len(knowledge.conversation_contexts), 1)
        self.assertEqual(knowledge.conversation_contexts[0].email_message, message)

    def test_project_with_questions(self):
        project = create_project()
        message = create_email_message(project)
        question = EmailQuestion.objects.create(
            organization=project.organization,
            email_message=message,
            question_text="Kas saate kinnitada?",
            confidence=70,
            evidence={"matches": [{"rule": "question_mark"}]},
        )

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        self.assertEqual(knowledge.questions, (question,))

    def test_project_with_answer_drafts(self):
        project = create_project()
        message = create_email_message(project)
        draft = EmailAnswerDraft.objects.create(
            organization=project.organization,
            email_message=message,
            draft_text="Draft answer",
            evidence={"source": "manual"},
        )

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        self.assertEqual(knowledge.answer_drafts, (draft,))

    def test_project_with_attachments(self):
        project = create_project()
        message = create_email_message(project)
        attachment = EmailAttachment.objects.create(
            organization=project.organization,
            email_message=message,
            original_filename="invoice.pdf",
        )

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        self.assertEqual(knowledge.attachments, (attachment,))

    def test_project_with_documents(self):
        project = create_project()
        message = create_email_message(project)
        document = create_document(project.organization)
        attachment = EmailAttachment.objects.create(
            organization=project.organization,
            email_message=message,
            document=document,
            original_filename="invoice.pdf",
        )

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        self.assertEqual(knowledge.attachments, (attachment,))
        self.assertEqual(knowledge.documents, (document,))

    def test_project_with_workflow_and_audit(self):
        project = create_project()
        instance, event = create_workflow_for_project(project)
        audit = AuditEvent.objects.create(
            organization=project.organization,
            event_type="project.created",
            object_type="Project",
            object_id=str(project.id),
            message="Project audit",
        )

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        self.assertEqual(knowledge.workflow_instances, (instance,))
        self.assertEqual(knowledge.workflow_events, (event,))
        self.assertEqual(knowledge.audit_events, (audit,))

    def test_project_with_evidence(self):
        project = create_project()
        message = create_email_message(project)
        question = EmailQuestion.objects.create(
            organization=project.organization,
            email_message=message,
            question_text="Please confirm?",
            confidence=70,
            evidence={"matches": [{"rule": "question_mark"}]},
        )
        draft = EmailAnswerDraft.objects.create(
            organization=project.organization,
            email_message=message,
            evidence={"answer": "drafted"},
        )

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        sources = [item["source"] for item in knowledge.evidence]
        self.assertEqual(sources, ["email_project_link", "email_question", "email_answer_draft"])
        self.assertEqual(knowledge.evidence[1]["source_id"], question.id)
        self.assertEqual(knowledge.evidence[2]["source_id"], draft.id)

    def test_project_with_timeline(self):
        project = create_project()
        message = create_email_message(project)
        question = EmailQuestion.objects.create(
            organization=project.organization,
            email_message=message,
            question_text="When?",
        )
        draft = EmailAnswerDraft.objects.create(
            organization=project.organization,
            email_message=message,
            draft_text="Soon",
        )
        create_workflow_for_project(project)

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        timeline_types = {entry["type"] for entry in knowledge.timeline}
        self.assertIn("email", timeline_types)
        self.assertIn("question", timeline_types)
        self.assertIn("answer_draft", timeline_types)
        self.assertIn("workflow_event", timeline_types)
        self.assertIn(question, [entry["object"] for entry in knowledge.timeline])
        self.assertIn(draft, [entry["object"] for entry in knowledge.timeline])

    def test_metadata_not_mutated(self):
        project = create_project()
        metadata = {"source": "caller"}

        knowledge = ProjectKnowledgeBuilder.build(
            BuildProjectKnowledgeCommand(
                project=project,
                metadata=metadata,
            )
        )
        metadata["source"] = "changed"

        self.assertEqual(knowledge.metadata, {"source": "caller"})

    def test_organization_isolation(self):
        project = create_project(code="26071")
        other_project = create_project(organization=create_organization("Other Org"), code="26071")
        create_email_message(other_project)

        knowledge = ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        self.assertEqual(knowledge.emails, ())
        self.assertEqual(knowledge.evidence, ())

    def test_builder_is_read_only(self):
        project = create_project()
        create_email_message(project)
        counts_before = self._counts()

        ProjectKnowledgeBuilder.build(BuildProjectKnowledgeCommand(project=project))

        self.assertEqual(self._counts(), counts_before)

    def _counts(self):
        return {
            "audit": AuditEvent.objects.count(),
            "email_links": EmailProjectLink.objects.count(),
            "questions": EmailQuestion.objects.count(),
            "answer_drafts": EmailAnswerDraft.objects.count(),
            "attachments": EmailAttachment.objects.count(),
            "documents": project_document_count(),
            "workflow_instances": WorkflowInstance.objects.count(),
            "workflow_events": WorkflowEvent.objects.count(),
        }


def project_document_count():
    return Document.objects.count()
