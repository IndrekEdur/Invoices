import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import override_settings
from django.test import TestCase
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.documents.models import Document, DocumentVersion
from apps.projects.models import Project
from apps.workflow.models import WorkflowDefinition, WorkflowInstance, WorkflowState

from .connectors import IMAPEmailConnector
from .dto import RawEmailMessage
from .models import EmailAccount, EmailAttachment, EmailMessage, EmailProjectLink, EmailQuestion, EmailThread
from .services import (
    ConfirmEmailProjectLinkCommand,
    ConvertEmailAttachmentToDocumentCommand,
    CorrectEmailProjectLinkCommand,
    DetectEmailQuestionsCommand,
    EmailAttachmentDocumentService,
    EmailImportService,
    EmailProcessingService,
    EmailProjectLinkService,
    EmailProjectSuggestionService,
    EmailQuestionDetectionService,
    ProcessEmailCommand,
    RejectEmailProjectLinkCommand,
    SuggestEmailProjectLinksCommand,
    SyncEmailAccountCommand,
    EmailSyncService,
)


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


def create_imap_email_account(**overrides):
    organization = overrides.pop("organization", None) or create_organization()
    data = {
        "organization": organization,
        "provider": EmailAccount.Provider.IMAP,
        "display_name": "IMAP mailbox",
        "email_address": "imap@example.com",
        "username": "imap@example.com",
        "host": "imap.example.com",
        "port": 993,
        "encrypted_secret_placeholder": "secret-placeholder",
    }
    data.update(overrides)
    return EmailAccount.objects.create(**data)


def create_email_message(organization=None, subject="Message with attachment", body_text=""):
    organization = organization or create_organization()
    account = create_email_account(organization=organization)
    return EmailMessage.objects.create(
        organization=organization,
        account=account,
        external_message_id="message-attachment-test",
        subject=subject,
        body_text=body_text,
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


def create_email_project_link():
    message = create_email_message()
    project = create_project(organization=message.organization)
    return EmailProjectLink.objects.create(
        organization=message.organization,
        email_message=message,
        project=project,
        confidence=72,
        evidence={"subject": "possible project match"},
    )


def create_document_workflow():
    workflow = WorkflowDefinition.objects.create(code="email-attachment-document", name="Email attachment document")
    WorkflowState.objects.create(workflow=workflow, code="received", name="Received", is_initial=True)
    return workflow


def create_raw_email(**overrides):
    data = {
        "external_message_id": "raw-message-1",
        "internet_message_id": "<raw-message-1@example.com>",
        "external_thread_id": "raw-thread-1",
        "subject": "Raw imported message",
        "body_text": "Raw body",
        "body_html": "<p>Raw body</p>",
        "sender_email": "sender@example.com",
        "sender_name": "Sender",
        "recipients": [{"email": "recipient@example.com"}],
        "cc": [],
        "bcc": [],
        "direction": EmailMessage.Direction.INBOUND,
        "received_at": timezone.now(),
        "metadata": {"provider": "imap"},
    }
    data.update(overrides)
    return RawEmailMessage(**data)


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


class IMAPEmailConnectorTests(TestCase):
    def test_imap_connector_accepts_imap_account(self):
        account = create_imap_email_account()

        connector = IMAPEmailConnector(account)
        result = connector.connect()

        self.assertEqual(result, connector)
        self.assertTrue(connector.connected)

    def test_rejects_non_imap_account(self):
        account = create_imap_email_account(provider=EmailAccount.Provider.GMAIL)
        connector = IMAPEmailConnector(account)

        with self.assertRaises(ValidationError):
            connector.connect()

    def test_rejects_missing_host(self):
        account = create_imap_email_account(host="")
        connector = IMAPEmailConnector(account)

        with self.assertRaises(ValidationError):
            connector.connect()

    def test_rejects_missing_port(self):
        account = create_imap_email_account(port=None)
        connector = IMAPEmailConnector(account)

        with self.assertRaises(ValidationError):
            connector.connect()

    def test_rejects_missing_username(self):
        account = create_imap_email_account(username="")
        connector = IMAPEmailConnector(account)

        with self.assertRaises(ValidationError):
            connector.connect()

    def test_rejects_missing_secret_placeholder(self):
        account = create_imap_email_account(encrypted_secret_placeholder="")
        connector = IMAPEmailConnector(account)

        with self.assertRaises(ValidationError):
            connector.connect()

    def test_fetch_messages_returns_list(self):
        account = create_imap_email_account()
        connector = IMAPEmailConnector(account)

        messages = connector.fetch_messages()

        self.assertEqual(messages, [])

    def test_disconnect_safe_before_and_after_connect(self):
        account = create_imap_email_account()
        connector = IMAPEmailConnector(account)

        connector.disconnect()
        self.assertFalse(connector.connected)

        connector.connect()
        connector.disconnect()
        self.assertFalse(connector.connected)

    def test_maps_dict_to_raw_email_message(self):
        account = create_imap_email_account()
        connector = IMAPEmailConnector(account)

        message = connector.map_imap_message(
            {
                "external_message_id": "imap-1",
                "internet_message_id": "<imap-1@example.com>",
                "external_thread_id": "thread-1",
                "subject": "Mapped message",
                "sender_email": "sender@example.com",
                "sender_name": "Sender",
                "recipients": [{"email": "to@example.com"}],
                "metadata": {"folder": "INBOX"},
            }
        )

        self.assertIsInstance(message, RawEmailMessage)
        self.assertEqual(message.external_message_id, "imap-1")
        self.assertEqual(message.internet_message_id, "<imap-1@example.com>")
        self.assertEqual(message.external_thread_id, "thread-1")
        self.assertEqual(message.subject, "Mapped message")
        self.assertEqual(message.sender_email, "sender@example.com")
        self.assertEqual(message.sender_name, "Sender")
        self.assertEqual(message.recipients, [{"email": "to@example.com"}])
        self.assertEqual(message.metadata, {"folder": "INBOX"})

    def test_map_defaults_recipients_cc_bcc_to_empty_lists(self):
        account = create_imap_email_account()
        connector = IMAPEmailConnector(account)

        message = connector.map_imap_message({"external_message_id": "imap-1"})

        self.assertEqual(message.recipients, [])
        self.assertEqual(message.cc, [])
        self.assertEqual(message.bcc, [])

    def test_map_defaults_direction_to_inbound(self):
        account = create_imap_email_account()
        connector = IMAPEmailConnector(account)

        message = connector.map_imap_message({"external_message_id": "imap-1"})

        self.assertEqual(message.direction, "inbound")

    def test_map_defaults_metadata_to_empty_dict(self):
        account = create_imap_email_account()
        connector = IMAPEmailConnector(account)

        message = connector.map_imap_message({"external_message_id": "imap-1"})

        self.assertEqual(message.metadata, {})

    def test_map_does_not_mutate_raw_data(self):
        account = create_imap_email_account()
        connector = IMAPEmailConnector(account)
        raw_data = {
            "external_message_id": "imap-1",
            "recipients": [{"email": "to@example.com"}],
        }
        original_data = {
            "external_message_id": "imap-1",
            "recipients": [{"email": "to@example.com"}],
        }

        connector.map_imap_message(raw_data)

        self.assertEqual(raw_data, original_data)

    def test_map_does_not_mutate_metadata(self):
        account = create_imap_email_account()
        connector = IMAPEmailConnector(account)
        metadata = {"folder": "INBOX"}
        raw_data = {"external_message_id": "imap-1", "metadata": metadata}

        message = connector.map_imap_message(raw_data)
        metadata["folder"] = "Archive"

        self.assertEqual(message.metadata, {"folder": "INBOX"})

    def test_map_supports_body_text_and_body_html(self):
        account = create_imap_email_account()
        connector = IMAPEmailConnector(account)

        message = connector.map_imap_message(
            {
                "external_message_id": "imap-1",
                "body_text": "Plain body",
                "body_html": "<p>HTML body</p>",
            }
        )

        self.assertEqual(message.body_text, "Plain body")
        self.assertEqual(message.body_html, "<p>HTML body</p>")

    def test_map_supports_sent_at_and_received_at(self):
        account = create_imap_email_account()
        connector = IMAPEmailConnector(account)
        sent_at = timezone.now() - timezone.timedelta(minutes=5)
        received_at = timezone.now()

        message = connector.map_imap_message(
            {
                "external_message_id": "imap-1",
                "sent_at": sent_at,
                "received_at": received_at,
            }
        )

        self.assertEqual(message.sent_at, sent_at)
        self.assertEqual(message.received_at, received_at)


class EmailSyncServiceTests(TestCase):
    def test_sync_imap_account_returns_structured_result(self):
        account = create_imap_email_account()
        raw_message = create_raw_email()

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.fetch_messages.return_value = [raw_message]

            result = EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        self.assertEqual(result["email_account"], account)
        self.assertEqual(result["fetched_count"], 1)
        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(result["raw_messages"], [raw_message])
        self.assertEqual(result["imported_messages"][0].external_message_id, raw_message.external_message_id)
        self.assertEqual(result["processed_count"], 0)
        self.assertEqual(result["processing_results"], [])
        self.assertTrue(result["synced"])

    def test_default_process_imported_is_false(self):
        account = create_imap_email_account()

        command = SyncEmailAccountCommand(email_account=account)

        self.assertFalse(command.process_imported)

    def test_sync_does_not_process_by_default(self):
        account = create_imap_email_account()

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector_class.return_value.fetch_messages.return_value = [create_raw_email()]

            with patch("apps.communications.services.sync.EmailProcessingService") as processing_service:
                result = EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        processing_service.process.assert_not_called()
        self.assertEqual(result["processed_count"], 0)
        self.assertEqual(result["processing_results"], [])

    def test_sync_processes_imported_emails_when_requested(self):
        account = create_imap_email_account()

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector_class.return_value.fetch_messages.return_value = [create_raw_email()]

            with patch("apps.communications.services.sync.EmailProcessingService") as processing_service:
                processing_service.process.return_value = {"processed": True}

                result = EmailSyncService.sync(
                    SyncEmailAccountCommand(
                        email_account=account,
                        process_imported=True,
                    )
                )

        processing_service.process.assert_called_once()
        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(result["processing_results"], [{"processed": True}])

    def test_disconnect_called_if_processing_fails(self):
        account = create_imap_email_account()

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.fetch_messages.return_value = [create_raw_email()]

            with patch("apps.communications.services.sync.EmailProcessingService") as processing_service:
                processing_service.process.side_effect = RuntimeError("processing failed")

                with self.assertRaises(RuntimeError):
                    EmailSyncService.sync(
                        SyncEmailAccountCommand(
                            email_account=account,
                            process_imported=True,
                        )
                    )

        connector.disconnect.assert_called_once_with()

    def test_project_suggestions_can_be_created_through_processing_hook(self):
        account = create_imap_email_account()
        create_project(organization=account.organization, code="26070", name="Kanarbiku")
        raw_message = create_raw_email(
            subject="Question about 26070",
            body_text="No extra body.",
        )

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector_class.return_value.fetch_messages.return_value = [raw_message]

            result = EmailSyncService.sync(
                SyncEmailAccountCommand(
                    email_account=account,
                    process_imported=True,
                )
            )

        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(EmailProjectLink.objects.count(), 1)
        self.assertEqual(result["processing_results"][0]["project_links"][0].project.code, "26070")

    def test_questions_can_be_created_through_processing_hook(self):
        account = create_imap_email_account()
        raw_message = create_raw_email(
            subject="Kas saad kinnitada?",
            body_text="Palun kinnitage.",
        )

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector_class.return_value.fetch_messages.return_value = [raw_message]

            result = EmailSyncService.sync(
                SyncEmailAccountCommand(
                    email_account=account,
                    process_imported=True,
                )
            )

        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(EmailQuestion.objects.count(), 1)
        self.assertEqual(result["processing_results"][0]["questions"][0].status, EmailQuestion.Status.DETECTED)

    def test_sync_imports_fetched_raw_email_message(self):
        account = create_imap_email_account()

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector_class.return_value.fetch_messages.return_value = [create_raw_email()]

            EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        self.assertTrue(
            EmailMessage.objects.filter(
                account=account,
                external_message_id="raw-message-1",
            ).exists()
        )

    def test_multiple_raw_messages_are_imported(self):
        account = create_imap_email_account()
        raw_messages = [
            create_raw_email(external_message_id="raw-1"),
            create_raw_email(external_message_id="raw-2"),
        ]

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector_class.return_value.fetch_messages.return_value = raw_messages

            result = EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        self.assertEqual(result["fetched_count"], 2)
        self.assertEqual(result["imported_count"], 2)
        self.assertEqual(EmailMessage.objects.filter(account=account).count(), 2)

    def test_duplicate_raw_message_does_not_create_duplicate_email_message(self):
        account = create_imap_email_account()
        raw_messages = [
            create_raw_email(subject="First version"),
            create_raw_email(subject="Updated version"),
        ]

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector_class.return_value.fetch_messages.return_value = raw_messages

            result = EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        self.assertEqual(result["fetched_count"], 2)
        self.assertEqual(result["imported_count"], 2)
        self.assertEqual(EmailMessage.objects.filter(account=account).count(), 1)
        self.assertEqual(EmailMessage.objects.get(account=account).subject, "Updated version")

    def test_unsupported_provider_raises_error(self):
        account = create_imap_email_account(provider=EmailAccount.Provider.GMAIL)

        with self.assertRaises(ValueError):
            EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

    def test_connector_connect_fetch_disconnect_are_called(self):
        account = create_imap_email_account()

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.fetch_messages.return_value = []

            EmailSyncService.sync(SyncEmailAccountCommand(email_account=account, limit=25))

        connector_class.assert_called_once_with(account)
        connector.connect.assert_called_once_with()
        connector.fetch_messages.assert_called_once_with(limit=25)
        connector.disconnect.assert_called_once_with()

    def test_disconnect_called_if_fetch_fails(self):
        account = create_imap_email_account()

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.fetch_messages.side_effect = RuntimeError("fetch failed")

            with self.assertRaises(RuntimeError):
                EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        connector.disconnect.assert_called_once_with()

    def test_disconnect_called_if_import_fails(self):
        account = create_imap_email_account()

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.fetch_messages.return_value = [create_raw_email()]

            with patch("apps.communications.services.sync.EmailImportService") as import_service:
                import_service.import_message.side_effect = RuntimeError("import failed")

                with self.assertRaises(RuntimeError):
                    EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        connector.disconnect.assert_called_once_with()

    def test_audit_event_created_for_started_and_completed(self):
        account = create_imap_email_account()

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector_class.return_value.fetch_messages.return_value = []

            EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="email.sync_started",
                object_type="EmailAccount",
                object_id=str(account.id),
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="email.sync_completed",
                object_type="EmailAccount",
                object_id=str(account.id),
            ).exists()
        )
        audit_event = AuditEvent.objects.get(event_type="email.sync_completed")
        self.assertEqual(audit_event.metadata["fetched_count"], 0)
        self.assertEqual(audit_event.metadata["imported_count"], 0)
        self.assertEqual(audit_event.metadata["processed_count"], 0)

    def test_metadata_is_not_mutated(self):
        account = create_imap_email_account()
        metadata = {"source": "manual-sync"}

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector_class.return_value.fetch_messages.return_value = []

            EmailSyncService.sync(
                SyncEmailAccountCommand(
                    email_account=account,
                    metadata=metadata,
                )
            )
        metadata["source"] = "caller-changed"

        audit_event = AuditEvent.objects.get(event_type="email.sync_completed")
        self.assertEqual(audit_event.metadata["sync_metadata"], {"source": "manual-sync"})

    def test_limit_passed_to_fetch_messages(self):
        account = create_imap_email_account()

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.fetch_messages.return_value = []

            EmailSyncService.sync(SyncEmailAccountCommand(email_account=account, limit=7))

        connector.fetch_messages.assert_called_once_with(limit=7)


class EmailImportServiceTests(TestCase):
    def test_imports_new_email_message(self):
        account = create_email_account()
        raw_message = create_raw_email()

        message = EmailImportService.import_message(account, raw_message)

        self.assertIsNotNone(message.id)
        self.assertEqual(message.account, account)
        self.assertEqual(message.external_message_id, "raw-message-1")
        self.assertEqual(message.subject, "Raw imported message")
        self.assertEqual(message.sender_email, "sender@example.com")

    def test_creates_email_thread_when_external_thread_id_exists(self):
        account = create_email_account()
        raw_message = create_raw_email(external_thread_id="thread-from-provider")

        message = EmailImportService.import_message(account, raw_message)

        self.assertIsNotNone(message.thread)
        self.assertEqual(message.thread.external_thread_id, "thread-from-provider")
        self.assertEqual(message.thread.organization, account.organization)

    def test_imports_email_message_without_thread(self):
        account = create_email_account()
        raw_message = create_raw_email(external_thread_id="")

        message = EmailImportService.import_message(account, raw_message)

        self.assertIsNone(message.thread)
        self.assertEqual(EmailThread.objects.count(), 0)

    def test_duplicate_external_message_id_updates_existing_message(self):
        account = create_email_account()
        EmailImportService.import_message(account, create_raw_email(subject="First subject"))

        message = EmailImportService.import_message(account, create_raw_email(subject="Updated subject"))

        self.assertEqual(EmailMessage.objects.count(), 1)
        self.assertEqual(message.subject, "Updated subject")

    def test_thread_message_count_updates(self):
        account = create_email_account()

        EmailImportService.import_message(account, create_raw_email(external_message_id="raw-1"))
        message = EmailImportService.import_message(account, create_raw_email(external_message_id="raw-2"))

        message.thread.refresh_from_db()
        self.assertEqual(message.thread.message_count, 2)

    def test_thread_last_message_at_updates(self):
        account = create_email_account()
        older = timezone.now() - timezone.timedelta(days=1)
        newer = timezone.now()

        EmailImportService.import_message(account, create_raw_email(external_message_id="raw-1", received_at=older))
        message = EmailImportService.import_message(
            account,
            create_raw_email(external_message_id="raw-2", received_at=newer),
        )

        message.thread.refresh_from_db()
        self.assertEqual(message.thread.last_message_at, newer)

    def test_organization_copied_from_account(self):
        account = create_email_account()

        message = EmailImportService.import_message(account, create_raw_email())

        self.assertEqual(message.organization, account.organization)

    def test_audit_event_created(self):
        account = create_email_account()

        message = EmailImportService.import_message(account, create_raw_email())

        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="email.message_imported",
                object_type="EmailMessage",
                object_id=str(message.id),
            ).exists()
        )

    def test_metadata_is_not_mutated(self):
        account = create_email_account()
        metadata = {"source": "manual-import"}

        EmailImportService.import_message(account, create_raw_email(), metadata=metadata)
        metadata["source"] = "caller-changed"

        audit_event = AuditEvent.objects.get(event_type="email.message_imported")
        self.assertEqual(audit_event.metadata["import_metadata"], {"source": "manual-import"})

    def test_raw_message_metadata_is_not_mutated(self):
        account = create_email_account()
        raw_metadata = {"provider": "imap"}
        raw_message = create_raw_email(metadata=raw_metadata)

        message = EmailImportService.import_message(account, raw_message)
        raw_metadata["provider"] = "caller-changed"

        message.refresh_from_db()
        self.assertEqual(message.metadata, {"provider": "imap"})


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


class EmailProjectLinkServiceTests(TestCase):
    def create_actor(self):
        return get_user_model().objects.create_user(username="project-reviewer")

    def test_confirm_changes_status(self):
        link = create_email_project_link()
        actor = self.create_actor()

        confirmed_link = EmailProjectLinkService.confirm(
            ConfirmEmailProjectLinkCommand(
                link=link,
                actor=actor,
            )
        )

        self.assertEqual(confirmed_link.status, EmailProjectLink.Status.CONFIRMED)

    def test_confirm_sets_confirmed_by_and_confirmed_at(self):
        link = create_email_project_link()
        actor = self.create_actor()

        confirmed_link = EmailProjectLinkService.confirm(
            ConfirmEmailProjectLinkCommand(
                link=link,
                actor=actor,
            )
        )

        self.assertEqual(confirmed_link.confirmed_by, actor)
        self.assertIsNotNone(confirmed_link.confirmed_at)

    def test_confirm_preserves_evidence(self):
        link = create_email_project_link()
        actor = self.create_actor()

        confirmed_link = EmailProjectLinkService.confirm(
            ConfirmEmailProjectLinkCommand(
                link=link,
                actor=actor,
            )
        )

        self.assertEqual(confirmed_link.evidence, {"subject": "possible project match"})

    def test_reject_changes_status(self):
        link = create_email_project_link()
        actor = self.create_actor()

        rejected_link = EmailProjectLinkService.reject(
            RejectEmailProjectLinkCommand(
                link=link,
                actor=actor,
                reason="Wrong project.",
            )
        )

        self.assertEqual(rejected_link.status, EmailProjectLink.Status.REJECTED)

    def test_reject_stores_reason_and_audit_metadata(self):
        link = create_email_project_link()
        actor = self.create_actor()

        rejected_link = EmailProjectLinkService.reject(
            RejectEmailProjectLinkCommand(
                link=link,
                actor=actor,
                reason="Wrong project.",
            )
        )

        self.assertEqual(rejected_link.metadata["rejection_reason"], "Wrong project.")
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="email_project_link.rejected",
                object_id=str(link.id),
                metadata__reason="Wrong project.",
            ).exists()
        )

    def test_correct_marks_original_as_corrected(self):
        link = create_email_project_link()
        new_project = create_project(organization=link.organization, code="26081", name="Correct project")
        actor = self.create_actor()

        EmailProjectLinkService.correct(
            CorrectEmailProjectLinkCommand(
                link=link,
                new_project=new_project,
                actor=actor,
                reason="User selected another project.",
            )
        )

        link.refresh_from_db()
        self.assertEqual(link.status, EmailProjectLink.Status.CORRECTED)
        self.assertEqual(link.metadata["correction_reason"], "User selected another project.")

    def test_correct_creates_confirmed_link_for_new_project(self):
        link = create_email_project_link()
        new_project = create_project(organization=link.organization, code="26082", name="Confirmed project")
        actor = self.create_actor()

        confirmed_link = EmailProjectLinkService.correct(
            CorrectEmailProjectLinkCommand(
                link=link,
                new_project=new_project,
                actor=actor,
            )
        )

        self.assertEqual(confirmed_link.project, new_project)
        self.assertEqual(confirmed_link.status, EmailProjectLink.Status.CONFIRMED)
        self.assertEqual(confirmed_link.confirmed_by, actor)
        self.assertIsNotNone(confirmed_link.confirmed_at)

    def test_correct_returns_confirmed_link(self):
        link = create_email_project_link()
        new_project = create_project(organization=link.organization, code="26083", name="Returned project")
        actor = self.create_actor()

        confirmed_link = EmailProjectLinkService.correct(
            CorrectEmailProjectLinkCommand(
                link=link,
                new_project=new_project,
                actor=actor,
            )
        )

        self.assertEqual(confirmed_link.status, EmailProjectLink.Status.CONFIRMED)
        self.assertEqual(confirmed_link.project, new_project)

    def test_metadata_is_not_mutated(self):
        link = create_email_project_link()
        actor = self.create_actor()
        metadata = {"source": "manual-review"}

        EmailProjectLinkService.confirm(
            ConfirmEmailProjectLinkCommand(
                link=link,
                actor=actor,
                metadata=metadata,
            )
        )
        metadata["source"] = "caller-changed"

        audit_event = AuditEvent.objects.get(event_type="email_project_link.confirmed")
        self.assertEqual(audit_event.metadata["decision_metadata"], {"source": "manual-review"})

    def test_audit_event_created_for_each_action(self):
        actor = self.create_actor()
        confirmed_link = create_email_project_link()
        rejected_link = create_email_project_link()
        corrected_link = create_email_project_link()
        new_project = create_project(organization=corrected_link.organization, code="26084", name="Audit project")

        EmailProjectLinkService.confirm(ConfirmEmailProjectLinkCommand(link=confirmed_link, actor=actor))
        EmailProjectLinkService.reject(RejectEmailProjectLinkCommand(link=rejected_link, actor=actor))
        EmailProjectLinkService.correct(
            CorrectEmailProjectLinkCommand(
                link=corrected_link,
                new_project=new_project,
                actor=actor,
            )
        )

        self.assertTrue(AuditEvent.objects.filter(event_type="email_project_link.confirmed").exists())
        self.assertTrue(AuditEvent.objects.filter(event_type="email_project_link.rejected").exists())
        self.assertTrue(AuditEvent.objects.filter(event_type="email_project_link.corrected").exists())

    def test_transaction_rolls_back_when_audit_fails(self):
        link = create_email_project_link()
        actor = self.create_actor()

        with patch("apps.communications.services.project_links.AuditService.record", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                EmailProjectLinkService.confirm(
                    ConfirmEmailProjectLinkCommand(
                        link=link,
                        actor=actor,
                    )
                )

        link.refresh_from_db()
        self.assertEqual(link.status, EmailProjectLink.Status.SUGGESTED)
        self.assertIsNone(link.confirmed_by)
        self.assertIsNone(link.confirmed_at)


class EmailProjectSuggestionServiceTests(TestCase):
    def test_suggests_by_project_code_in_subject(self):
        organization = create_organization()
        project = create_project(organization=organization, code="26090", name="Code subject project")
        message = create_email_message(organization=organization, subject="Question about 26090 invoice")

        suggestions = EmailProjectSuggestionService.suggest(
            SuggestEmailProjectLinksCommand(email_message=message)
        )

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].project, project)
        self.assertEqual(suggestions[0].confidence, 90)
        self.assertEqual(suggestions[0].status, EmailProjectLink.Status.SUGGESTED)

    def test_suggests_by_project_code_in_body(self):
        organization = create_organization()
        project = create_project(organization=organization, code="26091", name="Code body project")
        message = create_email_message(organization=organization, body_text="Please check project 26091 today.")

        suggestions = EmailProjectSuggestionService.suggest(
            SuggestEmailProjectLinksCommand(email_message=message)
        )

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].project, project)
        self.assertEqual(suggestions[0].confidence, 90)

    def test_suggests_by_project_name_in_subject(self):
        organization = create_organization()
        project = create_project(organization=organization, code="26092", name="Kanarbiku")
        message = create_email_message(organization=organization, subject="Kanarbiku weekly update")

        suggestions = EmailProjectSuggestionService.suggest(
            SuggestEmailProjectLinksCommand(email_message=message)
        )

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].project, project)
        self.assertEqual(suggestions[0].confidence, 75)

    def test_no_match_returns_empty_list(self):
        organization = create_organization()
        create_project(organization=organization, code="26093", name="No Match Project")
        message = create_email_message(organization=organization, subject="Unrelated message")

        suggestions = EmailProjectSuggestionService.suggest(
            SuggestEmailProjectLinksCommand(email_message=message)
        )

        self.assertEqual(suggestions, [])
        self.assertEqual(EmailProjectLink.objects.count(), 0)


class EmailQuestionModelAndDetectionServiceTests(TestCase):
    def test_detects_question_mark_in_subject(self):
        message = create_email_message(subject="Can you confirm this?")

        questions = EmailQuestionDetectionService.detect(
            DetectEmailQuestionsCommand(email_message=message)
        )

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].confidence, 70)
        self.assertEqual(questions[0].status, EmailQuestion.Status.DETECTED)
        self.assertEqual(questions[0].detection_method, EmailQuestion.DetectionMethod.RULE_BASED)

    def test_detects_question_mark_in_body(self):
        message = create_email_message(body_text="Kas see arve on korrektne?")

        questions = EmailQuestionDetectionService.detect(
            DetectEmailQuestionsCommand(email_message=message)
        )

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].confidence, 70)

    def test_detects_estonian_keyword(self):
        message = create_email_message(subject="Palun saatke dokument")

        questions = EmailQuestionDetectionService.detect(
            DetectEmailQuestionsCommand(email_message=message)
        )

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].confidence, 60)
        self.assertIn(
            {"matched_field": "subject", "rule": "estonian_keyword", "keyword": "palun", "confidence": 60},
            questions[0].evidence["matches"],
        )

    def test_detects_english_keyword(self):
        message = create_email_message(body_text="Please confirm the delivery date.")

        questions = EmailQuestionDetectionService.detect(
            DetectEmailQuestionsCommand(email_message=message)
        )

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].confidence, 60)
        self.assertIn(
            {"matched_field": "body_text", "rule": "english_keyword", "keyword": "please", "confidence": 60},
            questions[0].evidence["matches"],
        )

    def test_no_match_returns_empty_list(self):
        message = create_email_message(subject="FYI", body_text="Invoice attached.")

        questions = EmailQuestionDetectionService.detect(
            DetectEmailQuestionsCommand(email_message=message)
        )

        self.assertEqual(questions, [])
        self.assertEqual(EmailQuestion.objects.count(), 0)

    def test_evidence_is_stored(self):
        message = create_email_message(subject="Could you confirm this?")

        questions = EmailQuestionDetectionService.detect(
            DetectEmailQuestionsCommand(email_message=message)
        )

        evidence_matches = questions[0].evidence["matches"]
        self.assertIn(
            {"matched_field": "subject", "rule": "question_mark", "confidence": 70},
            evidence_matches,
        )
        self.assertIn(
            {"matched_field": "subject", "rule": "english_keyword", "keyword": "could you", "confidence": 60},
            evidence_matches,
        )

    def test_audit_event_created(self):
        message = create_email_message(subject="When can you send it?")

        questions = EmailQuestionDetectionService.detect(
            DetectEmailQuestionsCommand(email_message=message)
        )

        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="email_question.detected",
                object_id=str(questions[0].id),
                metadata__email_message_id=message.id,
            ).exists()
        )

    def test_metadata_is_not_mutated(self):
        message = create_email_message(subject="Please confirm")
        metadata = {"source": "rules"}

        questions = EmailQuestionDetectionService.detect(
            DetectEmailQuestionsCommand(
                email_message=message,
                metadata=metadata,
            )
        )
        metadata["source"] = "caller-changed"

        audit_event = AuditEvent.objects.get(event_type="email_question.detected")
        self.assertEqual(questions[0].metadata, {"source": "rules"})
        self.assertEqual(audit_event.metadata["detection_metadata"], {"source": "rules"})

    def test_organization_scoping_works(self):
        organization = create_organization(name="Question Org")
        other_organization = create_organization(name="Other Question Org")
        message = create_email_message(organization=organization, subject="Kas saate kinnitada?")
        create_email_message(organization=other_organization, subject="No detection here")

        questions = EmailQuestionDetectionService.detect(
            DetectEmailQuestionsCommand(email_message=message)
        )

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].organization, organization)
        self.assertEqual(EmailQuestion.objects.filter(organization=other_organization).count(), 0)

    def test_question_str_works(self):
        message = create_email_message(subject="How should we proceed?")

        question = EmailQuestionDetectionService.detect(
            DetectEmailQuestionsCommand(email_message=message)
        )[0]

        self.assertEqual(str(question), "How should we proceed?: How should we proceed?")


class EmailProcessingServiceTests(TestCase):
    def test_process_creates_project_suggestions_when_project_code_exists(self):
        organization = create_organization()
        project = create_project(organization=organization, code="26100", name="Processing project")
        message = create_email_message(organization=organization, subject="26100 question")

        result = EmailProcessingService.process(ProcessEmailCommand(email_message=message))

        self.assertTrue(result["processed"])
        self.assertEqual(result["project_links"][0].project, project)
        self.assertEqual(EmailProjectLink.objects.count(), 1)

    def test_process_detects_questions(self):
        message = create_email_message(subject="Can you confirm?")

        result = EmailProcessingService.process(ProcessEmailCommand(email_message=message))

        self.assertTrue(result["processed"])
        self.assertEqual(len(result["questions"]), 1)
        self.assertEqual(EmailQuestion.objects.count(), 1)

    def test_process_returns_structured_result(self):
        message = create_email_message(subject="FYI")

        result = EmailProcessingService.process(ProcessEmailCommand(email_message=message))

        self.assertEqual(result["email_message"], message)
        self.assertEqual(result["project_links"], [])
        self.assertEqual(result["questions"], [])
        self.assertTrue(result["processed"])

    def test_process_creates_audit_event(self):
        message = create_email_message(subject="FYI")

        EmailProcessingService.process(ProcessEmailCommand(email_message=message))

        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="email.processing_completed",
                object_type="EmailMessage",
                object_id=str(message.id),
            ).exists()
        )

    def test_metadata_is_not_mutated(self):
        message = create_email_message(subject="Please confirm")
        metadata = {"source": "pipeline"}

        EmailProcessingService.process(
            ProcessEmailCommand(
                email_message=message,
                metadata=metadata,
            )
        )
        metadata["source"] = "caller-changed"

        audit_event = AuditEvent.objects.get(event_type="email.processing_completed")
        self.assertEqual(audit_event.metadata["processing_metadata"], {"source": "pipeline"})

    def test_no_project_no_question_still_returns_processed_true(self):
        message = create_email_message(subject="FYI", body_text="Document attached.")

        result = EmailProcessingService.process(ProcessEmailCommand(email_message=message))

        self.assertTrue(result["processed"])
        self.assertEqual(result["project_links"], [])
        self.assertEqual(result["questions"], [])

    def test_transaction_rolls_back_when_processing_audit_fails(self):
        organization = create_organization()
        create_project(organization=organization, code="26101", name="Rollback project")
        message = create_email_message(organization=organization, subject="26101 Can you confirm?")

        with patch("apps.communications.services.processing.AuditService.record", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                EmailProcessingService.process(ProcessEmailCommand(email_message=message))

        self.assertEqual(EmailProjectLink.objects.count(), 0)
        self.assertEqual(EmailQuestion.objects.count(), 0)

    def test_does_not_overwrite_confirmed_link(self):
        organization = create_organization()
        project = create_project(organization=organization, code="26094", name="Confirmed project")
        message = create_email_message(organization=organization, subject="26094 update")
        link = EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            status=EmailProjectLink.Status.CONFIRMED,
            confidence=100,
            evidence={"confirmed": True},
        )

        suggestions = EmailProjectSuggestionService.suggest(
            SuggestEmailProjectLinksCommand(email_message=message)
        )

        link.refresh_from_db()
        self.assertEqual(suggestions, [])
        self.assertEqual(link.status, EmailProjectLink.Status.CONFIRMED)
        self.assertEqual(link.confidence, 100)
        self.assertEqual(link.evidence, {"confirmed": True})

    def test_does_not_overwrite_rejected_link(self):
        organization = create_organization()
        project = create_project(organization=organization, code="26095", name="Rejected project")
        message = create_email_message(organization=organization, subject="26095 update")
        link = EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            status=EmailProjectLink.Status.REJECTED,
            confidence=20,
            evidence={"rejected": True},
        )

        suggestions = EmailProjectSuggestionService.suggest(
            SuggestEmailProjectLinksCommand(email_message=message)
        )

        link.refresh_from_db()
        self.assertEqual(suggestions, [])
        self.assertEqual(link.status, EmailProjectLink.Status.REJECTED)
        self.assertEqual(link.confidence, 20)
        self.assertEqual(link.evidence, {"rejected": True})

    def test_evidence_is_stored(self):
        organization = create_organization()
        create_project(organization=organization, code="26096", name="Evidence project")
        message = create_email_message(organization=organization, subject="26096 Evidence project")

        suggestions = EmailProjectSuggestionService.suggest(
            SuggestEmailProjectLinksCommand(email_message=message)
        )

        evidence_matches = suggestions[0].evidence["matches"]
        self.assertIn(
            {"matched_field": "subject", "matched_project_code": "26096", "confidence": 90},
            evidence_matches,
        )
        self.assertIn(
            {"matched_field": "subject", "matched_project_name": "Evidence project", "confidence": 75},
            evidence_matches,
        )

    def test_audit_event_created(self):
        organization = create_organization()
        project = create_project(organization=organization, code="26097", name="Audit suggestion")
        message = create_email_message(organization=organization, subject="26097 update")

        suggestions = EmailProjectSuggestionService.suggest(
            SuggestEmailProjectLinksCommand(email_message=message)
        )

        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="email_project_link.suggested",
                object_id=str(suggestions[0].id),
                metadata__project_id=project.id,
            ).exists()
        )

    def test_metadata_is_not_mutated(self):
        organization = create_organization()
        create_project(organization=organization, code="26098", name="Metadata project")
        message = create_email_message(organization=organization, subject="26098 update")
        metadata = {"source": "rules"}

        EmailProjectSuggestionService.suggest(
            SuggestEmailProjectLinksCommand(
                email_message=message,
                metadata=metadata,
            )
        )
        metadata["source"] = "caller-changed"

        link = EmailProjectLink.objects.get()
        audit_event = AuditEvent.objects.get(event_type="email_project_link.suggested")
        self.assertEqual(link.metadata, {"source": "rules"})
        self.assertEqual(audit_event.metadata["suggestion_metadata"], {"source": "rules"})

    def test_organization_scoping_works(self):
        organization = create_organization(name="Message Org")
        other_organization = create_organization(name="Other Org")
        create_project(organization=other_organization, code="26099", name="Other org project")
        message = create_email_message(organization=organization, subject="26099 update")

        suggestions = EmailProjectSuggestionService.suggest(
            SuggestEmailProjectLinksCommand(email_message=message)
        )

        self.assertEqual(suggestions, [])
        self.assertEqual(EmailProjectLink.objects.count(), 0)
