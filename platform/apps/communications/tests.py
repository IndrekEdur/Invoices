import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import override_settings
from django.test import TestCase

from apps.core.models import AuditEvent
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.documents.models import Document, DocumentVersion
from apps.projects.models import Project
from apps.workflow.models import WorkflowDefinition, WorkflowInstance, WorkflowState

from .models import EmailAccount, EmailAttachment, EmailMessage, EmailProjectLink, EmailThread
from .services import ConvertEmailAttachmentToDocumentCommand, EmailAttachmentDocumentService


def create_organization(name="Communications Org"):
    return OrganizationService.create(CreateOrganizationCommand(name=name))


def create_email_account(organization=None, email_address="mail@example.com"):
    organization = organization or create_organization()
    return EmailAccount.objects.create(
        organization=organization,
        provider=EmailAccount.Provider.IMAP,
        display_name="Mailbox",
        email_address=email_address,
    )


def create_email_message(organization=None):
    organization = organization or create_organization()
    account = create_email_account(organization=organization)
    return EmailMessage.objects.create(
        organization=organization,
        account=account,
        external_message_id="message-attachment-test",
        subject="Message with attachment",
    )


def create_email_attachment():
    message = create_email_message()
    return EmailAttachment.objects.create(
        organization=message.organization,
        email_message=message,
        original_filename="invoice.pdf",
        content_type="application/pdf",
    )


def create_project(organization=None, code="26070", name="Kanarbiku"):
    organization = organization or create_organization()
    return Project.objects.create(
        organization=organization,
        code=code,
        name=name,
    )


def create_document_workflow():
    workflow = WorkflowDefinition.objects.create(code="email-attachment-document", name="Email attachment document")
    WorkflowState.objects.create(workflow=workflow, code="received", name="Received", is_initial=True)
    return workflow


class EmailAccountModelTests(TestCase):
    def test_can_create_email_account(self):
        organization = create_organization()

        account = EmailAccount.objects.create(
            organization=organization,
            provider=EmailAccount.Provider.IMAP,
            display_name="Zone.eu mailbox",
            email_address="info@example.com",
            username="info@example.com",
            host="imap.zone.eu",
            port=993,
            auth_type="password",
        )

        self.assertIsNotNone(account.id)
        self.assertEqual(account.organization, organization)
        self.assertEqual(account.provider, EmailAccount.Provider.IMAP)
        self.assertEqual(account.host, "imap.zone.eu")
        self.assertEqual(account.port, 993)

    def test_default_flags(self):
        organization = create_organization()

        account = EmailAccount.objects.create(
            organization=organization,
            provider=EmailAccount.Provider.IMAP,
            display_name="Default account",
            email_address="mail@example.com",
        )

        self.assertTrue(account.use_ssl)
        self.assertFalse(account.use_tls)
        self.assertTrue(account.is_active)
        self.assertIsNone(account.last_sync_at)

    def test_metadata_defaults_to_empty_dict(self):
        organization = create_organization()

        account = EmailAccount.objects.create(
            organization=organization,
            provider=EmailAccount.Provider.PST_IMPORT,
            display_name="Legacy PST import",
            email_address="archive@example.com",
        )

        self.assertEqual(account.metadata, {})

    def test_provider_choices_include_required_providers(self):
        values = {choice for choice, _label in EmailAccount.Provider.choices}

        self.assertEqual(
            values,
            {"imap", "microsoft_365", "pst_import", "gmail", "other"},
        )

    def test_pst_import_can_be_created_without_host_or_port(self):
        organization = create_organization()

        account = EmailAccount.objects.create(
            organization=organization,
            provider=EmailAccount.Provider.PST_IMPORT,
            display_name="Local PST archive",
            email_address="archive@example.com",
        )

        self.assertEqual(account.host, "")
        self.assertIsNone(account.port)

    def test_str_includes_display_name_and_email(self):
        organization = create_organization()

        account = EmailAccount.objects.create(
            organization=organization,
            provider=EmailAccount.Provider.GMAIL,
            display_name="Gmail account",
            email_address="gmail@example.com",
        )

        self.assertEqual(str(account), "Gmail account <gmail@example.com>")


class EmailThreadModelTests(TestCase):
    def test_can_create_email_thread(self):
        organization = create_organization()
        account = create_email_account(organization=organization)

        thread = EmailThread.objects.create(
            organization=organization,
            account=account,
            external_thread_id="thread-1",
            subject="Invoice question",
            normalized_subject="invoice question",
            message_count=2,
            metadata={"source": "imap"},
        )

        self.assertIsNotNone(thread.id)
        self.assertEqual(thread.organization, organization)
        self.assertEqual(thread.account, account)
        self.assertEqual(thread.message_count, 2)
        self.assertEqual(thread.metadata, {"source": "imap"})

    def test_external_thread_id_unique_per_account(self):
        organization = create_organization()
        account = create_email_account(organization=organization)

        EmailThread.objects.create(
            organization=organization,
            account=account,
            external_thread_id="thread-1",
        )

        with self.assertRaises(IntegrityError):
            EmailThread.objects.create(
                organization=organization,
                account=account,
                external_thread_id="thread-1",
            )

    def test_same_external_thread_id_allowed_for_different_accounts(self):
        organization = create_organization()
        account = create_email_account(organization=organization, email_address="one@example.com")
        other_account = create_email_account(organization=organization, email_address="two@example.com")

        EmailThread.objects.create(
            organization=organization,
            account=account,
            external_thread_id="thread-1",
        )
        other_thread = EmailThread.objects.create(
            organization=organization,
            account=other_account,
            external_thread_id="thread-1",
        )

        self.assertIsNotNone(other_thread.id)

    def test_thread_str(self):
        account = create_email_account()

        thread = EmailThread.objects.create(
            organization=account.organization,
            account=account,
            external_thread_id="thread-1",
            subject="Readable thread",
        )

        self.assertEqual(str(thread), "Readable thread")


class EmailMessageModelTests(TestCase):
    def test_can_create_email_message(self):
        organization = create_organization()
        account = create_email_account(organization=organization)
        thread = EmailThread.objects.create(
            organization=organization,
            account=account,
            external_thread_id="thread-1",
            subject="Invoice thread",
        )

        message = EmailMessage.objects.create(
            organization=organization,
            account=account,
            thread=thread,
            external_message_id="message-1",
            internet_message_id="<message-1@example.com>",
            subject="Invoice attached",
            body_text="Please see invoice.",
            body_html="<p>Please see invoice.</p>",
            sender_email="supplier@example.com",
            sender_name="Supplier",
            recipients=[{"email": "info@example.com", "name": "Info"}],
            cc=[],
            bcc=[],
            direction=EmailMessage.Direction.INBOUND,
            metadata={"source": "imap"},
        )

        self.assertIsNotNone(message.id)
        self.assertEqual(message.organization, organization)
        self.assertEqual(message.account, account)
        self.assertEqual(message.thread, thread)
        self.assertEqual(message.recipients[0]["email"], "info@example.com")
        self.assertEqual(message.metadata, {"source": "imap"})

    def test_email_message_can_be_without_thread(self):
        account = create_email_account()

        message = EmailMessage.objects.create(
            organization=account.organization,
            account=account,
            external_message_id="message-1",
            subject="Standalone message",
        )

        self.assertIsNone(message.thread)

    def test_direction_default_is_unknown(self):
        account = create_email_account()

        message = EmailMessage.objects.create(
            organization=account.organization,
            account=account,
            external_message_id="message-1",
        )

        self.assertEqual(message.direction, EmailMessage.Direction.UNKNOWN)

    def test_external_message_id_unique_per_account(self):
        organization = create_organization()
        account = create_email_account(organization=organization)

        EmailMessage.objects.create(
            organization=organization,
            account=account,
            external_message_id="message-1",
        )

        with self.assertRaises(IntegrityError):
            EmailMessage.objects.create(
                organization=organization,
                account=account,
                external_message_id="message-1",
            )

    def test_same_external_message_id_allowed_for_different_accounts(self):
        organization = create_organization()
        account = create_email_account(organization=organization, email_address="one@example.com")
        other_account = create_email_account(organization=organization, email_address="two@example.com")

        EmailMessage.objects.create(
            organization=organization,
            account=account,
            external_message_id="message-1",
        )
        other_message = EmailMessage.objects.create(
            organization=organization,
            account=other_account,
            external_message_id="message-1",
        )

        self.assertIsNotNone(other_message.id)

    def test_message_str(self):
        account = create_email_account()

        message = EmailMessage.objects.create(
            organization=account.organization,
            account=account,
            external_message_id="message-1",
            subject="Readable message",
        )

        self.assertEqual(str(message), "Readable message")


class EmailAttachmentModelTests(TestCase):
    def test_can_create_email_attachment(self):
        message = create_email_message()

        attachment = EmailAttachment.objects.create(
            organization=message.organization,
            email_message=message,
            original_filename="invoice.pdf",
            content_type="application/pdf",
            size_bytes=12345,
            content_id="attachment-1",
            sha256="a" * 64,
            metadata={"source": "imap"},
        )

        self.assertIsNotNone(attachment.id)
        self.assertEqual(attachment.organization, message.organization)
        self.assertEqual(attachment.original_filename, "invoice.pdf")
        self.assertEqual(attachment.content_type, "application/pdf")
        self.assertEqual(attachment.size_bytes, 12345)
        self.assertEqual(attachment.metadata, {"source": "imap"})

    def test_attachment_belongs_to_email_message(self):
        message = create_email_message()

        attachment = EmailAttachment.objects.create(
            organization=message.organization,
            email_message=message,
            original_filename="invoice.pdf",
        )

        self.assertEqual(attachment.email_message, message)
        self.assertEqual(message.attachments.get(), attachment)

    def test_document_can_be_null(self):
        message = create_email_message()

        attachment = EmailAttachment.objects.create(
            organization=message.organization,
            email_message=message,
            original_filename="invoice.pdf",
        )

        self.assertIsNone(attachment.document)

    def test_document_can_be_linked(self):
        message = create_email_message()
        document = Document.objects.create(
            organization=message.organization,
            title="Invoice document",
            original_filename="invoice.pdf",
            source=Document.Source.MAIL,
        )

        attachment = EmailAttachment.objects.create(
            organization=message.organization,
            email_message=message,
            document=document,
            original_filename="invoice.pdf",
        )

        self.assertEqual(attachment.document, document)
        self.assertEqual(document.email_attachments.get(), attachment)

    def test_is_inline_defaults_false(self):
        message = create_email_message()

        attachment = EmailAttachment.objects.create(
            organization=message.organization,
            email_message=message,
            original_filename="logo.png",
        )

        self.assertFalse(attachment.is_inline)

    def test_attachment_str(self):
        message = create_email_message()

        attachment = EmailAttachment.objects.create(
            organization=message.organization,
            email_message=message,
            original_filename="invoice.pdf",
        )

        self.assertEqual(str(attachment), "invoice.pdf")


class EmailAttachmentDocumentServiceTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)

    def test_converts_attachment_to_document(self):
        attachment = create_email_attachment()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = EmailAttachmentDocumentService.convert(
            ConvertEmailAttachmentToDocumentCommand(
                attachment=attachment,
                file=uploaded_file,
            )
        )

        self.assertIsNotNone(document.id)
        self.assertEqual(document.organization, attachment.organization)
        self.assertEqual(document.original_filename, attachment.original_filename)
        self.assertEqual(document.source, Document.Source.EMAIL_ATTACHMENT)

    def test_links_document_to_email_attachment(self):
        attachment = create_email_attachment()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = EmailAttachmentDocumentService.convert(
            ConvertEmailAttachmentToDocumentCommand(
                attachment=attachment,
                file=uploaded_file,
            )
        )

        attachment.refresh_from_db()
        self.assertEqual(attachment.document, document)

    def test_creates_document_version(self):
        attachment = create_email_attachment()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = EmailAttachmentDocumentService.convert(
            ConvertEmailAttachmentToDocumentCommand(
                attachment=attachment,
                file=uploaded_file,
            )
        )

        version = document.versions.get()
        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.sha256, document.sha256)

    def test_creates_audit_event(self):
        attachment = create_email_attachment()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = EmailAttachmentDocumentService.convert(
            ConvertEmailAttachmentToDocumentCommand(
                attachment=attachment,
                file=uploaded_file,
            )
        )

        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="email_attachment.converted_to_document",
                organization=attachment.organization,
                object_type="EmailAttachment",
                object_id=str(attachment.id),
                metadata__document_uuid=str(document.uuid),
            ).exists()
        )

    def test_metadata_is_not_mutated(self):
        attachment = create_email_attachment()
        metadata = {"source": "email"}
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = EmailAttachmentDocumentService.convert(
            ConvertEmailAttachmentToDocumentCommand(
                attachment=attachment,
                file=uploaded_file,
                metadata=metadata,
            )
        )
        document.metadata["source"] = "changed"

        self.assertEqual(metadata, {"source": "email"})

    def test_optional_workflow_creates_workflow_instance(self):
        attachment = create_email_attachment()
        workflow = create_document_workflow()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = EmailAttachmentDocumentService.convert(
            ConvertEmailAttachmentToDocumentCommand(
                attachment=attachment,
                file=uploaded_file,
                workflow=workflow,
            )
        )

        instance = WorkflowInstance.objects.get(entity_uuid=document.uuid)
        self.assertEqual(instance.workflow, workflow)
        self.assertEqual(instance.entity_type, "document")

    def test_transaction_rolls_back_when_attachment_audit_fails(self):
        attachment = create_email_attachment()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        with patch("apps.communications.services.attachments.AuditService.record", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                EmailAttachmentDocumentService.convert(
                    ConvertEmailAttachmentToDocumentCommand(
                        attachment=attachment,
                        file=uploaded_file,
                    )
                )

        attachment.refresh_from_db()
        self.assertIsNone(attachment.document)
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentVersion.objects.count(), 0)


class EmailProjectLinkModelTests(TestCase):
    def test_can_create_email_project_link(self):
        message = create_email_message()
        project = create_project(organization=message.organization)

        link = EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
            status=EmailProjectLink.Status.CONFIRMED,
            confidence=95,
            evidence={"subject": "matched project code"},
            metadata={"source": "test"},
        )

        self.assertIsNotNone(link.id)
        self.assertEqual(link.organization, message.organization)
        self.assertEqual(link.email_message, message)
        self.assertEqual(link.project, project)
        self.assertEqual(link.evidence, {"subject": "matched project code"})

    def test_default_status_is_suggested(self):
        message = create_email_message()
        project = create_project(organization=message.organization)

        link = EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
        )

        self.assertEqual(link.status, EmailProjectLink.Status.SUGGESTED)

    def test_default_confidence_is_zero(self):
        message = create_email_message()
        project = create_project(organization=message.organization)

        link = EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
        )

        self.assertEqual(link.confidence, 0)

    def test_evidence_defaults_to_empty_dict(self):
        message = create_email_message()
        project = create_project(organization=message.organization)

        link = EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
        )

        self.assertEqual(link.evidence, {})

    def test_metadata_defaults_to_empty_dict(self):
        message = create_email_message()
        project = create_project(organization=message.organization)

        link = EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
        )

        self.assertEqual(link.metadata, {})

    def test_confirmed_by_can_be_null(self):
        message = create_email_message()
        project = create_project(organization=message.organization)

        link = EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
        )

        self.assertIsNone(link.confirmed_by)

    def test_confirmed_at_can_be_null(self):
        message = create_email_message()
        project = create_project(organization=message.organization)

        link = EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
        )

        self.assertIsNone(link.confirmed_at)

    def test_unique_email_message_project(self):
        message = create_email_message()
        project = create_project(organization=message.organization)
        EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
        )

        with self.assertRaises(IntegrityError):
            EmailProjectLink.objects.create(
                organization=message.organization,
                email_message=message,
                project=project,
            )

    def test_str_includes_email_subject_and_project_code(self):
        message = create_email_message()
        project = create_project(organization=message.organization, code="26080")

        link = EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
        )

        self.assertEqual(str(link), "Message with attachment -> 26080")
