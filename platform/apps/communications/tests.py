import shutil
import tempfile
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import override_settings
from django.test import TestCase
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.documents.models import Document, DocumentVersion
from apps.projects.models import Project, ProjectParty
from apps.workflow.models import WorkflowDefinition, WorkflowInstance, WorkflowState

from .connectors import IMAPEmailConnector
from .dto import IMAPMailboxSnapshot, RawEmailMessage
from .models import (
    EmailAccount,
    EmailAnswerDraft,
    EmailAttachment,
    EmailMailboxState,
    EmailMessage,
    EmailProjectLink,
    EmailQuestion,
    EmailThread,
)
from .services import (
    ApproveEmailAnswerDraftCommand,
    BuildConversationContextCommand,
    ConfirmEmailProjectLinkCommand,
    ConversationContextBuilder,
    CreateEmailAnswerDraftCommand,
    ConvertEmailAttachmentToDocumentCommand,
    CorrectEmailProjectLinkCommand,
    DetectEmailQuestionsCommand,
    DeterministicEmailProjectLinkingService,
    EmailAnswerDraftService,
    EmailAttachmentDocumentService,
    EmailImportService,
    EmailMailboxStateService,
    EmailProcessingService,
    EmailProjectLinkService,
    EmailProjectSuggestionService,
    EmailQuestionDetectionService,
    GetOrCreateMailboxStateCommand,
    MailboxUIDValidityChangedError,
    MarkMailboxSyncCompletedCommand,
    MarkMailboxSyncFailedCommand,
    MarkMailboxSyncStartedCommand,
    MarkEmailAnswerDraftNeedsReviewCommand,
    ProcessEmailCommand,
    RejectEmailAnswerDraftCommand,
    RejectEmailProjectLinkCommand,
    SuggestEmailProjectLinksCommand,
    SyncEmailAccountCommand,
    UpdateMailboxSyncProgressCommand,
    EmailSyncService,
    EvaluateEmailProjectLinksCommand,
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


class EmailMailboxStateModelTests(TestCase):
    def test_can_create_mailbox_state(self):
        account = create_email_account()

        state = EmailMailboxState.objects.create(
            organization=account.organization,
            email_account=account,
            mailbox_name="INBOX",
        )

        self.assertIsNotNone(state.id)
        self.assertEqual(state.organization, account.organization)
        self.assertEqual(state.email_account, account)

    def test_defaults_are_correct(self):
        account = create_email_account()

        state = EmailMailboxState.objects.create(
            organization=account.organization,
            email_account=account,
            mailbox_name="INBOX",
        )

        self.assertEqual(state.external_mailbox_id, "")
        self.assertEqual(state.sync_status, EmailMailboxState.SyncStatus.IDLE)
        self.assertEqual(state.initial_import_status, EmailMailboxState.InitialImportStatus.NOT_STARTED)
        self.assertEqual(state.last_error, "")
        self.assertEqual(state.discovered_count, 0)
        self.assertEqual(state.imported_count, 0)
        self.assertEqual(state.processed_count, 0)
        self.assertEqual(state.skipped_count, 0)
        self.assertEqual(state.failed_count, 0)
        self.assertEqual(state.cursor_metadata, {})
        self.assertEqual(state.metadata, {})

    def test_account_and_mailbox_uniqueness(self):
        account = create_email_account()
        EmailMailboxState.objects.create(
            organization=account.organization,
            email_account=account,
            mailbox_name="INBOX",
        )

        with self.assertRaises(IntegrityError):
            EmailMailboxState.objects.create(
                organization=account.organization,
                email_account=account,
                mailbox_name="INBOX",
            )

    def test_cursor_fields_are_nullable(self):
        account = create_email_account()

        state = EmailMailboxState.objects.create(
            organization=account.organization,
            email_account=account,
            mailbox_name="INBOX",
        )

        self.assertIsNone(state.uid_validity)
        self.assertIsNone(state.last_discovered_uid)
        self.assertIsNone(state.last_processed_uid)
        self.assertIsNone(state.highest_modseq)

    def test_str_shows_account_mailbox_and_status(self):
        account = create_email_account(email_address="sync@example.com")

        state = EmailMailboxState.objects.create(
            organization=account.organization,
            email_account=account,
            mailbox_name="Archive",
        )

        self.assertEqual(str(state), "sync@example.com Archive (idle)")


class EmailMailboxStateServiceTests(TestCase):
    def test_get_or_create_creates_state(self):
        account = create_email_account()

        state = EmailMailboxStateService.get_or_create(
            GetOrCreateMailboxStateCommand(
                email_account=account,
                mailbox_name="INBOX",
                external_mailbox_id="inbox-id",
                uid_validity=123,
                metadata={"source": "test"},
            )
        )

        self.assertEqual(state.organization, account.organization)
        self.assertEqual(state.email_account, account)
        self.assertEqual(state.mailbox_name, "INBOX")
        self.assertEqual(state.external_mailbox_id, "inbox-id")
        self.assertEqual(state.uid_validity, 123)
        self.assertEqual(state.metadata, {"source": "test"})

    def test_get_or_create_returns_existing_without_resetting_progress(self):
        account = create_email_account()
        state = EmailMailboxState.objects.create(
            organization=account.organization,
            email_account=account,
            mailbox_name="INBOX",
            uid_validity=123,
            last_processed_uid=50,
            imported_count=10,
        )

        returned = EmailMailboxStateService.get_or_create(
            GetOrCreateMailboxStateCommand(email_account=account, mailbox_name="INBOX", uid_validity=123)
        )

        self.assertEqual(returned, state)
        self.assertEqual(returned.last_processed_uid, 50)
        self.assertEqual(returned.imported_count, 10)

    def test_organization_copied_from_account(self):
        account = create_email_account()

        state = EmailMailboxStateService.get_or_create(GetOrCreateMailboxStateCommand(email_account=account))

        self.assertEqual(state.organization, account.organization)

    def test_mark_started_updates_status_and_timestamps(self):
        state = self._state()

        EmailMailboxStateService.mark_started(MarkMailboxSyncStartedCommand(mailbox_state=state))

        state.refresh_from_db()
        self.assertEqual(state.sync_status, EmailMailboxState.SyncStatus.RUNNING)
        self.assertIsNotNone(state.last_sync_started_at)
        self.assertIsNotNone(state.last_progress_at)
        self.assertEqual(state.last_error, "")

    def test_initial_import_start_updates_initial_import_status(self):
        state = self._state()

        EmailMailboxStateService.mark_started(
            MarkMailboxSyncStartedCommand(mailbox_state=state, initial_import=True)
        )

        state.refresh_from_db()
        self.assertEqual(state.initial_import_status, EmailMailboxState.InitialImportStatus.RUNNING)

    def test_update_progress_updates_cursors(self):
        state = self._state()

        EmailMailboxStateService.update_progress(
            UpdateMailboxSyncProgressCommand(
                mailbox_state=state,
                last_discovered_uid=100,
                last_processed_uid=90,
                highest_modseq=5000,
            )
        )

        state.refresh_from_db()
        self.assertEqual(state.last_discovered_uid, 100)
        self.assertEqual(state.last_processed_uid, 90)
        self.assertEqual(state.highest_modseq, 5000)
        self.assertIsNotNone(state.last_progress_at)

    def test_update_progress_increments_counts(self):
        state = self._state()

        EmailMailboxStateService.update_progress(
            UpdateMailboxSyncProgressCommand(
                mailbox_state=state,
                discovered_increment=3,
                imported_increment=2,
                processed_increment=1,
                skipped_increment=4,
                failed_increment=5,
            )
        )

        state.refresh_from_db()
        self.assertEqual(state.discovered_count, 3)
        self.assertEqual(state.imported_count, 2)
        self.assertEqual(state.processed_count, 1)
        self.assertEqual(state.skipped_count, 4)
        self.assertEqual(state.failed_count, 5)

    def test_update_progress_rejects_negative_increments(self):
        state = self._state()

        with self.assertRaisesMessage(ValueError, "cannot be negative"):
            EmailMailboxStateService.update_progress(
                UpdateMailboxSyncProgressCommand(mailbox_state=state, imported_increment=-1)
            )

    def test_mark_completed_updates_successful_sync_timestamps(self):
        state = self._state()

        EmailMailboxStateService.mark_completed(MarkMailboxSyncCompletedCommand(mailbox_state=state))

        state.refresh_from_db()
        self.assertEqual(state.sync_status, EmailMailboxState.SyncStatus.IDLE)
        self.assertIsNotNone(state.last_sync_completed_at)
        self.assertIsNotNone(state.last_successful_sync_at)
        self.assertIsNotNone(state.last_progress_at)
        self.assertEqual(state.last_error, "")

    def test_initial_import_completion_updates_status(self):
        state = self._state(initial_import_status=EmailMailboxState.InitialImportStatus.RUNNING)

        EmailMailboxStateService.mark_completed(
            MarkMailboxSyncCompletedCommand(mailbox_state=state, initial_import=True)
        )

        state.refresh_from_db()
        self.assertEqual(state.initial_import_status, EmailMailboxState.InitialImportStatus.COMPLETED)

    def test_mark_failed_stores_safe_error(self):
        state = self._state()

        EmailMailboxStateService.mark_failed(
            MarkMailboxSyncFailedCommand(
                mailbox_state=state,
                safe_error="IMAP fetch failed safely",
                initial_import=True,
            )
        )

        state.refresh_from_db()
        self.assertEqual(state.sync_status, EmailMailboxState.SyncStatus.FAILED)
        self.assertEqual(state.initial_import_status, EmailMailboxState.InitialImportStatus.FAILED)
        self.assertEqual(state.last_error, "IMAP fetch failed safely")
        self.assertIsNotNone(state.last_sync_completed_at)
        self.assertIsNotNone(state.last_progress_at)

    def test_pause_changes_status(self):
        state = self._state(
            sync_status=EmailMailboxState.SyncStatus.RUNNING,
            initial_import_status=EmailMailboxState.InitialImportStatus.RUNNING,
        )

        EmailMailboxStateService.pause(state)

        state.refresh_from_db()
        self.assertEqual(state.sync_status, EmailMailboxState.SyncStatus.PAUSED)
        self.assertEqual(state.initial_import_status, EmailMailboxState.InitialImportStatus.PAUSED)

    def test_metadata_not_mutated(self):
        account = create_email_account()
        metadata = {"source": {"name": "test"}}
        original_metadata = {"source": {"name": "test"}}

        state = EmailMailboxStateService.get_or_create(
            GetOrCreateMailboxStateCommand(email_account=account, metadata=metadata)
        )
        state.metadata["source"]["name"] = "changed"

        self.assertEqual(metadata, original_metadata)

    def test_cursor_metadata_not_mutated(self):
        state = self._state()
        cursor_metadata = {"cursor": {"uid": 10}}
        original_cursor_metadata = {"cursor": {"uid": 10}}

        EmailMailboxStateService.update_progress(
            UpdateMailboxSyncProgressCommand(mailbox_state=state, cursor_metadata=cursor_metadata)
        )
        state.refresh_from_db()
        state.cursor_metadata["cursor"]["uid"] = 20

        self.assertEqual(cursor_metadata, original_cursor_metadata)

    def test_audit_event_created_for_start_completed_failed_and_pause(self):
        state = self._state()

        EmailMailboxStateService.mark_started(MarkMailboxSyncStartedCommand(mailbox_state=state))
        EmailMailboxStateService.mark_completed(MarkMailboxSyncCompletedCommand(mailbox_state=state))
        EmailMailboxStateService.mark_failed(MarkMailboxSyncFailedCommand(mailbox_state=state, safe_error="safe"))
        EmailMailboxStateService.pause(state)

        event_types = set(AuditEvent.objects.values_list("event_type", flat=True))
        self.assertIn("email.mailbox_sync_started", event_types)
        self.assertIn("email.mailbox_sync_completed", event_types)
        self.assertIn("email.mailbox_sync_failed", event_types)
        self.assertIn("email.mailbox_sync_paused", event_types)

    def test_transaction_rollback(self):
        state = self._state()

        with patch("apps.communications.services.mailbox_state.AuditService.record", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                EmailMailboxStateService.mark_started(MarkMailboxSyncStartedCommand(mailbox_state=state))

        state.refresh_from_db()
        self.assertEqual(state.sync_status, EmailMailboxState.SyncStatus.IDLE)
        self.assertIsNone(state.last_sync_started_at)

    def test_uidvalidity_change_is_detected_and_not_silently_accepted(self):
        account = create_email_account()
        state = EmailMailboxState.objects.create(
            organization=account.organization,
            email_account=account,
            mailbox_name="INBOX",
            uid_validity=123,
            last_processed_uid=50,
        )

        with self.assertRaises(MailboxUIDValidityChangedError):
            EmailMailboxStateService.get_or_create(
                GetOrCreateMailboxStateCommand(email_account=account, mailbox_name="INBOX", uid_validity=456)
            )

        state.refresh_from_db()
        self.assertEqual(state.uid_validity, 123)
        self.assertEqual(state.last_processed_uid, 50)
        self.assertEqual(state.cursor_metadata, {})

    def test_organization_isolation_works(self):
        account = create_email_account(email_address="one@example.com")
        other_account = create_email_account(email_address="two@example.com")

        state = EmailMailboxStateService.get_or_create(
            GetOrCreateMailboxStateCommand(email_account=account, mailbox_name="INBOX")
        )
        other_state = EmailMailboxStateService.get_or_create(
            GetOrCreateMailboxStateCommand(email_account=other_account, mailbox_name="INBOX")
        )

        self.assertNotEqual(state.organization, other_state.organization)
        self.assertEqual(state.email_account, account)
        self.assertEqual(other_state.email_account, other_account)

    def _state(self, **kwargs):
        account = kwargs.pop("email_account", None) or create_email_account()
        defaults = {
            "organization": account.organization,
            "email_account": account,
            "mailbox_name": "INBOX",
        }
        defaults.update(kwargs)
        return EmailMailboxState.objects.create(**defaults)


class IMAPEmailConnectorTests(TestCase):
    def make_plain_email(
        self,
        *,
        subject="Hello from IMAP",
        message_id="<message-1@example.com>",
        from_header="Sender Name <sender@example.com>",
        to_header="Receiver <receiver@example.com>",
        cc_header="Copy <copy@example.com>",
        body="Plain body",
        date_header="Tue, 7 Jul 2026 10:00:00 +0300",
        references="",
        in_reply_to="",
    ):
        headers = [
            f"Message-ID: {message_id}" if message_id else "",
            f"Date: {date_header}" if date_header else "",
            f"From: {from_header}",
            f"To: {to_header}",
            f"Cc: {cc_header}",
            f"Subject: {subject}",
            f"References: {references}" if references else "",
            f"In-Reply-To: {in_reply_to}" if in_reply_to else "",
            "Content-Type: text/plain; charset=utf-8",
        ]
        return ("\r\n".join(header for header in headers if header) + f"\r\n\r\n{body}").encode()

    def make_multipart_email(self):
        return b"""Message-ID: <multipart@example.com>
Date: Tue, 7 Jul 2026 11:00:00 +0300
From: Sender <sender@example.com>
To: Receiver <receiver@example.com>
Subject: Multipart message
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="mixed-boundary"

--mixed-boundary
Content-Type: multipart/alternative; boundary="alt-boundary"

--alt-boundary
Content-Type: text/plain; charset=utf-8

Plain multipart body
--alt-boundary
Content-Type: text/html; charset=utf-8

<p>HTML multipart body</p>
--alt-boundary--
--mixed-boundary
Content-Type: text/plain
Content-Disposition: attachment; filename="note.txt"

Attachment body should be ignored
--mixed-boundary--
"""

    def connect_with_mock_client(self, client):
        account = create_imap_email_account()
        with patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL") as imap_class:
            imap_class.return_value = client
            client.login.return_value = ("OK", [])
            return IMAPEmailConnector(account).connect()

    def test_imap_connector_accepts_imap_account(self):
        account = create_imap_email_account()

        with patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL") as imap_class:
            imap_class.return_value.login.return_value = ("OK", [])

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
        client = patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL").start().return_value
        self.addCleanup(patch.stopall)
        client.login.return_value = ("OK", [])
        client.select.return_value = ("OK", [])
        client.uid.return_value = ("OK", [b""])

        connector = IMAPEmailConnector(create_imap_email_account()).connect()
        messages = connector.fetch_messages()

        self.assertEqual(messages, [])

    def test_disconnect_safe_before_and_after_connect(self):
        account = create_imap_email_account()
        connector = IMAPEmailConnector(account)

        connector.disconnect()
        self.assertFalse(connector.connected)

        with patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL") as imap_class:
            imap_class.return_value.login.return_value = ("OK", [])

            connector.connect()

        connector.disconnect()
        self.assertFalse(connector.connected)

    def test_ssl_imap_connection_is_used_when_use_ssl_true(self):
        account = create_imap_email_account(use_ssl=True)

        with patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL") as imap_ssl:
            imap_ssl.return_value.login.return_value = ("OK", [])

            IMAPEmailConnector(account).connect()

        imap_ssl.assert_called_once_with(account.host, account.port)

    def test_non_ssl_imap_connection_is_used_when_use_ssl_false(self):
        account = create_imap_email_account(use_ssl=False)

        with patch("apps.communications.connectors.imap.imaplib.IMAP4") as imap_plain:
            imap_plain.return_value.login.return_value = ("OK", [])

            IMAPEmailConnector(account).connect()

        imap_plain.assert_called_once_with(account.host, account.port)

    def test_login_called_with_username_and_secret(self):
        account = create_imap_email_account(username="mail@example.com", encrypted_secret_placeholder="temporary-secret")

        with patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL") as imap_ssl:
            client = imap_ssl.return_value
            client.login.return_value = ("OK", [])

            IMAPEmailConnector(account).connect()

        client.login.assert_called_once_with("mail@example.com", "temporary-secret")

    def test_logout_called_on_disconnect(self):
        account = create_imap_email_account()

        with patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL") as imap_ssl:
            client = imap_ssl.return_value
            client.login.return_value = ("OK", [])
            connector = IMAPEmailConnector(account).connect()

            connector.disconnect()

        client.logout.assert_called_once_with()

    def test_list_mailboxes_parses_mocked_imap_response(self):
        account = create_imap_email_account()

        with patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL") as imap_ssl:
            client = imap_ssl.return_value
            client.login.return_value = ("OK", [])
            client.list.return_value = (
                "OK",
                [
                    b'(\\HasNoChildren) "/" "INBOX"',
                    b'(\\HasNoChildren) "/" "Archive"',
                ],
            )
            connector = IMAPEmailConnector(account).connect()

            mailboxes = connector.list_mailboxes()

        self.assertEqual(mailboxes, ["INBOX", "Archive"])

    def test_connection_failure_raises_clear_exception(self):
        account = create_imap_email_account()

        with patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL") as imap_ssl:
            imap_ssl.side_effect = OSError("network unavailable")

            with self.assertRaisesRegex(RuntimeError, "IMAP connection failed"):
                IMAPEmailConnector(account).connect()

    def test_login_failure_raises_clear_exception(self):
        account = create_imap_email_account()

        with patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL") as imap_ssl:
            imap_ssl.return_value.login.return_value = ("NO", [b"authentication failed"])

            with self.assertRaisesRegex(RuntimeError, "IMAP login failed"):
                IMAPEmailConnector(account).connect()

    def test_fetch_messages_returns_raw_email_message_list(self):
        client = patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL").start().return_value
        self.addCleanup(patch.stopall)
        client.login.return_value = ("OK", [])
        client.select.return_value = ("OK", [])
        client.uid.side_effect = [
            ("OK", [b"1"]),
            ("OK", [(b"1 (RFC822)", self.make_plain_email())]),
        ]

        messages = IMAPEmailConnector(create_imap_email_account()).connect().fetch_messages()

        self.assertEqual(len(messages), 1)
        self.assertIsInstance(messages[0], RawEmailMessage)
        self.assertEqual(messages[0].metadata["imap_uid"], 1)
        self.assertEqual(messages[0].external_message_id, "imap:INBOX:1")

    def test_fetch_messages_respects_limit(self):
        client = patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL").start().return_value
        self.addCleanup(patch.stopall)
        client.login.return_value = ("OK", [])
        client.select.return_value = ("OK", [])
        client.uid.side_effect = [
            ("OK", [b"1 2 3"]),
            ("OK", [(b"2 (RFC822)", self.make_plain_email(message_id="<message-2@example.com>"))]),
            ("OK", [(b"3 (RFC822)", self.make_plain_email(message_id="<message-3@example.com>"))]),
        ]

        messages = IMAPEmailConnector(create_imap_email_account()).connect().fetch_messages(limit=2)

        self.assertEqual([message.external_message_id for message in messages], ["imap:INBOX:2", "imap:INBOX:3"])

    def test_fetch_messages_selects_inbox_by_default(self):
        client = patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL").start().return_value
        self.addCleanup(patch.stopall)
        client.login.return_value = ("OK", [])
        client.select.return_value = ("OK", [])
        client.uid.return_value = ("OK", [b""])

        IMAPEmailConnector(create_imap_email_account()).connect().fetch_messages()

        client.select.assert_called_once_with("INBOX")

    def test_mailbox_snapshot_parses_uidvalidity_and_message_count(self):
        client = patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL").start().return_value
        self.addCleanup(patch.stopall)
        client.login.return_value = ("OK", [])
        client.select.return_value = ("OK", [b"3"])
        client.response.return_value = ("OK", [b"777"])
        client.uid.return_value = ("OK", [b"9 10 11"])

        snapshot = IMAPEmailConnector(create_imap_email_account()).connect().get_mailbox_snapshot()

        self.assertEqual(snapshot.uid_validity, 777)
        self.assertEqual(snapshot.message_count, 3)
        self.assertEqual(snapshot.highest_uid, 11)

    def test_fetch_messages_uses_uid_search_and_uid_fetch(self):
        client = patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL").start().return_value
        self.addCleanup(patch.stopall)
        client.login.return_value = ("OK", [])
        client.select.return_value = ("OK", [])
        client.uid.side_effect = [
            ("OK", [b"1"]),
            ("OK", [(b"1 (RFC822)", self.make_plain_email())]),
        ]

        IMAPEmailConnector(create_imap_email_account()).connect().fetch_messages()

        self.assertEqual(client.uid.call_args_list[0].args, ("search", None, "ALL"))
        self.assertEqual(client.uid.call_args_list[1].args, ("fetch", "1", "(RFC822)"))

    def test_after_uid_filters_sorts_and_limits_oldest_next_batch(self):
        client = patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL").start().return_value
        self.addCleanup(patch.stopall)
        client.login.return_value = ("OK", [])
        client.select.return_value = ("OK", [])
        client.uid.side_effect = [
            ("OK", [b"12 10 11 9 8"]),
            ("OK", [(b"10 (RFC822)", self.make_plain_email(message_id="<10@example.com>"))]),
            ("OK", [(b"11 (RFC822)", self.make_plain_email(message_id="<11@example.com>"))]),
        ]

        messages = IMAPEmailConnector(create_imap_email_account()).connect().fetch_messages(limit=2, after_uid=9)

        self.assertEqual([message.metadata["imap_uid"] for message in messages], [10, 11])

    def test_initial_no_cursor_selects_latest_limited_uids_in_ascending_order(self):
        client = patch("apps.communications.connectors.imap.imaplib.IMAP4_SSL").start().return_value
        self.addCleanup(patch.stopall)
        client.login.return_value = ("OK", [])
        client.select.return_value = ("OK", [])
        client.uid.side_effect = [
            ("OK", [b"1 2 3 4 5"]),
            ("OK", [(b"4 (RFC822)", self.make_plain_email(message_id="<4@example.com>"))]),
            ("OK", [(b"5 (RFC822)", self.make_plain_email(message_id="<5@example.com>"))]),
        ]

        messages = IMAPEmailConnector(create_imap_email_account()).connect().fetch_messages(limit=2)

        self.assertEqual([message.metadata["imap_uid"] for message in messages], [4, 5])

    def test_parse_email_message_parses_subject(self):
        connector = IMAPEmailConnector(create_imap_email_account())

        message = connector.parse_email_message(self.make_plain_email(subject="Parsed subject"), "1")

        self.assertEqual(message.subject, "Parsed subject")

    def test_parse_email_message_parses_sender(self):
        connector = IMAPEmailConnector(create_imap_email_account())

        message = connector.parse_email_message(
            self.make_plain_email(from_header="Sender Name <sender@example.com>"),
            "1",
        )

        self.assertEqual(message.sender_name, "Sender Name")
        self.assertEqual(message.sender_email, "sender@example.com")

    def test_parse_email_message_parses_recipients(self):
        connector = IMAPEmailConnector(create_imap_email_account())

        message = connector.parse_email_message(
            self.make_plain_email(to_header="One <one@example.com>, two@example.com"),
            "1",
        )

        self.assertEqual(
            message.recipients,
            [
                {"name": "One", "email": "one@example.com"},
                {"name": "", "email": "two@example.com"},
            ],
        )

    def test_parse_email_message_parses_body_text(self):
        connector = IMAPEmailConnector(create_imap_email_account())

        message = connector.parse_email_message(self.make_plain_email(body="Body text"), "1")

        self.assertEqual(message.body_text, "Body text")

    def test_parse_email_message_parses_body_html(self):
        connector = IMAPEmailConnector(create_imap_email_account())

        message = connector.parse_email_message(self.make_multipart_email(), "1")

        self.assertEqual(message.body_html.strip(), "<p>HTML multipart body</p>")

    def test_parse_email_message_parses_message_id(self):
        connector = IMAPEmailConnector(create_imap_email_account())

        message = connector.parse_email_message(self.make_plain_email(message_id="<custom@example.com>"), "7")

        self.assertEqual(message.internet_message_id, "<custom@example.com>")

    def test_parse_email_message_handles_missing_message_id(self):
        connector = IMAPEmailConnector(create_imap_email_account())

        message = connector.parse_email_message(self.make_plain_email(message_id=""), "7")

        self.assertEqual(message.external_message_id, "7")
        self.assertEqual(message.internet_message_id, "")

    def test_parse_email_message_handles_multipart_email(self):
        connector = IMAPEmailConnector(create_imap_email_account())

        message = connector.parse_email_message(self.make_multipart_email(), "1")

        self.assertEqual(message.body_text.strip(), "Plain multipart body")
        self.assertEqual(message.body_html.strip(), "<p>HTML multipart body</p>")

    def test_parse_email_message_ignores_attachments_for_now(self):
        connector = IMAPEmailConnector(create_imap_email_account())

        message = connector.parse_email_message(self.make_multipart_email(), "1")

        self.assertNotIn("Attachment body should be ignored", message.body_text)

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
        connector.get_mailbox_snapshot.assert_called_once_with("INBOX")
        connector.fetch_messages.assert_called_once_with(limit=25, mailbox="INBOX", after_uid=None)
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

        connector.fetch_messages.assert_called_once_with(limit=7, mailbox="INBOX", after_uid=None)

    def test_incremental_sync_creates_mailbox_state_and_records_uidvalidity(self):
        account = create_imap_email_account()
        raw_message = create_raw_email(
            external_message_id="imap:INBOX:10",
            metadata={"imap_uid": 10, "mailbox_name": "INBOX", "uid_validity": 123},
        )

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.get_mailbox_snapshot.return_value = IMAPMailboxSnapshot(
                mailbox_name="INBOX",
                uid_validity=123,
                highest_uid=10,
                message_count=1,
            )
            connector.fetch_messages.return_value = [raw_message]

            result = EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        state = EmailMailboxState.objects.get(email_account=account, mailbox_name="INBOX")
        self.assertEqual(state.uid_validity, 123)
        self.assertEqual(state.last_discovered_uid, 10)
        self.assertEqual(state.last_processed_uid, 10)
        self.assertEqual(state.discovered_count, 1)
        self.assertEqual(state.imported_count, 1)
        self.assertEqual(result["mailbox_state"], state)
        self.assertEqual(result["cursor_before"], None)
        self.assertEqual(result["cursor_after"], 10)
        self.assertTrue(result["incremental"])

    def test_incremental_sync_uses_stored_last_processed_uid_as_after_uid(self):
        account = create_imap_email_account()
        EmailMailboxState.objects.create(
            organization=account.organization,
            email_account=account,
            mailbox_name="INBOX",
            uid_validity=123,
            last_processed_uid=20,
        )

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.get_mailbox_snapshot.return_value = IMAPMailboxSnapshot("INBOX", uid_validity=123)
            connector.fetch_messages.return_value = []

            result = EmailSyncService.sync(SyncEmailAccountCommand(email_account=account, limit=5))

        connector.fetch_messages.assert_called_once_with(limit=5, mailbox="INBOX", after_uid=20)
        self.assertEqual(result["cursor_before"], 20)
        self.assertEqual(result["cursor_after"], 20)

    def test_incremental_sync_with_no_new_messages_leaves_cursor_unchanged(self):
        account = create_imap_email_account()
        state = EmailMailboxState.objects.create(
            organization=account.organization,
            email_account=account,
            mailbox_name="INBOX",
            uid_validity=123,
            last_processed_uid=20,
            imported_count=4,
        )

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.get_mailbox_snapshot.return_value = IMAPMailboxSnapshot("INBOX", uid_validity=123)
            connector.fetch_messages.return_value = []

            result = EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        state.refresh_from_db()
        self.assertEqual(state.last_processed_uid, 20)
        self.assertEqual(state.imported_count, 4)
        self.assertEqual(result["imported_count"], 0)

    def test_repeated_same_uid_does_not_create_duplicate_message(self):
        account = create_imap_email_account()
        raw_message = create_raw_email(
            external_message_id="imap:INBOX:10",
            metadata={"imap_uid": 10, "mailbox_name": "INBOX"},
        )

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.get_mailbox_snapshot.return_value = IMAPMailboxSnapshot("INBOX", uid_validity=123)
            connector.fetch_messages.return_value = [raw_message]

            EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))
            EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        self.assertEqual(EmailMessage.objects.filter(account=account, external_message_id="imap:INBOX:10").count(), 1)

    def test_partial_processing_failure_preserves_earlier_cursor_and_stops_batch(self):
        account = create_imap_email_account()
        raw_messages = [
            create_raw_email(external_message_id="imap:INBOX:10", metadata={"imap_uid": 10}),
            create_raw_email(external_message_id="imap:INBOX:11", metadata={"imap_uid": 11}),
            create_raw_email(external_message_id="imap:INBOX:12", metadata={"imap_uid": 12}),
        ]

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.get_mailbox_snapshot.return_value = IMAPMailboxSnapshot("INBOX", uid_validity=123)
            connector.fetch_messages.return_value = raw_messages

            with patch("apps.communications.services.sync.EmailProcessingService") as processing_service:
                processing_service.process.side_effect = [{"processed": True}, RuntimeError("processing failed")]

                with self.assertRaises(RuntimeError):
                    EmailSyncService.sync(
                        SyncEmailAccountCommand(
                            email_account=account,
                            process_imported=True,
                        )
                    )

        state = EmailMailboxState.objects.get(email_account=account, mailbox_name="INBOX")
        self.assertEqual(state.last_processed_uid, 10)
        self.assertEqual(state.imported_count, 1)
        self.assertEqual(state.processed_count, 1)
        self.assertEqual(state.sync_status, EmailMailboxState.SyncStatus.FAILED)
        self.assertIn("RuntimeError", state.last_error)
        self.assertEqual(processing_service.process.call_count, 2)
        self.assertFalse(EmailMessage.objects.filter(account=account, external_message_id="imap:INBOX:12").exists())
        connector.disconnect.assert_called_once_with()

    def test_next_sync_resumes_after_preserved_cursor(self):
        account = create_imap_email_account()
        EmailMailboxState.objects.create(
            organization=account.organization,
            email_account=account,
            mailbox_name="INBOX",
            uid_validity=123,
            last_processed_uid=10,
        )

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.get_mailbox_snapshot.return_value = IMAPMailboxSnapshot("INBOX", uid_validity=123)
            connector.fetch_messages.return_value = [
                create_raw_email(external_message_id="imap:INBOX:11", metadata={"imap_uid": 11})
            ]

            EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        connector.fetch_messages.assert_called_once_with(limit=50, mailbox="INBOX", after_uid=10)
        state = EmailMailboxState.objects.get(email_account=account, mailbox_name="INBOX")
        self.assertEqual(state.last_processed_uid, 11)

    def test_uidvalidity_conflict_prevents_fetch_and_import(self):
        account = create_imap_email_account()
        EmailMailboxState.objects.create(
            organization=account.organization,
            email_account=account,
            mailbox_name="INBOX",
            uid_validity=123,
            last_processed_uid=10,
        )

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.get_mailbox_snapshot.return_value = IMAPMailboxSnapshot("INBOX", uid_validity=456)

            with self.assertRaises(MailboxUIDValidityChangedError):
                EmailSyncService.sync(SyncEmailAccountCommand(email_account=account))

        connector.fetch_messages.assert_not_called()
        connector.disconnect.assert_called_once_with()
        self.assertEqual(EmailMessage.objects.count(), 0)
        state = EmailMailboxState.objects.get(email_account=account, mailbox_name="INBOX")
        self.assertEqual(state.last_processed_uid, 10)
        self.assertEqual(state.sync_status, EmailMailboxState.SyncStatus.FAILED)

    def test_process_imported_true_increments_processed_count(self):
        account = create_imap_email_account()
        raw_message = create_raw_email(
            external_message_id="imap:INBOX:10",
            metadata={"imap_uid": 10},
        )

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.get_mailbox_snapshot.return_value = IMAPMailboxSnapshot("INBOX", uid_validity=123)
            connector.fetch_messages.return_value = [raw_message]

            result = EmailSyncService.sync(
                SyncEmailAccountCommand(
                    email_account=account,
                    process_imported=True,
                )
            )

        state = EmailMailboxState.objects.get(email_account=account, mailbox_name="INBOX")
        self.assertEqual(state.processed_count, 1)
        self.assertEqual(result["processed_count"], 1)

    def test_incremental_false_preserves_bounded_latest_without_cursor(self):
        account = create_imap_email_account()

        with patch("apps.communications.services.sync.IMAPEmailConnector") as connector_class:
            connector = connector_class.return_value
            connector.fetch_messages.return_value = []

            result = EmailSyncService.sync(
                SyncEmailAccountCommand(
                    email_account=account,
                    limit=3,
                    incremental=False,
                )
            )

        connector.get_mailbox_snapshot.assert_not_called()
        connector.fetch_messages.assert_called_once_with(limit=3, mailbox="INBOX", after_uid=None)
        self.assertFalse(EmailMailboxState.objects.filter(email_account=account).exists())
        self.assertFalse(result["incremental"])


class SyncEmailAccountCommandTests(TestCase):
    def test_command_calls_email_sync_service(self):
        account = create_email_account()

        with patch("apps.communications.management.commands.sync_email_account.EmailSyncService") as sync_service:
            sync_service.sync.return_value = {
                "email_account": account,
                "fetched_count": 0,
                "imported_count": 0,
                "processed_count": 0,
                "raw_messages": [],
                "imported_messages": [],
                "processing_results": [],
                "synced": True,
            }

            call_command("sync_email_account", str(account.id), stdout=StringIO())

        sync_service.sync.assert_called_once()

    def test_limit_is_passed(self):
        account = create_email_account()

        with patch("apps.communications.management.commands.sync_email_account.EmailSyncService") as sync_service:
            sync_service.sync.return_value = {
                "email_account": account,
                "fetched_count": 0,
                "imported_count": 0,
                "processed_count": 0,
                "raw_messages": [],
                "imported_messages": [],
                "processing_results": [],
                "synced": True,
            }

            call_command("sync_email_account", str(account.id), "--limit", "5", stdout=StringIO())

        command = sync_service.sync.call_args.args[0]
        self.assertEqual(command.limit, 5)

    def test_process_sets_process_imported_true(self):
        account = create_email_account()

        with patch("apps.communications.management.commands.sync_email_account.EmailSyncService") as sync_service:
            sync_service.sync.return_value = {
                "email_account": account,
                "fetched_count": 0,
                "imported_count": 0,
                "processed_count": 0,
                "raw_messages": [],
                "imported_messages": [],
                "processing_results": [],
                "synced": True,
            }

            call_command("sync_email_account", str(account.id), "--process", stdout=StringIO())

        command = sync_service.sync.call_args.args[0]
        self.assertTrue(command.process_imported)

    def test_missing_account_raises_command_error(self):
        with self.assertRaisesRegex(CommandError, "EmailAccount not found"):
            call_command("sync_email_account", "999999", stdout=StringIO())

    def test_sync_failure_raises_command_error(self):
        account = create_email_account()

        with patch("apps.communications.management.commands.sync_email_account.EmailSyncService") as sync_service:
            sync_service.sync.side_effect = RuntimeError("sync exploded")

            with self.assertRaisesRegex(CommandError, "Email sync failed"):
                call_command("sync_email_account", str(account.id), stdout=StringIO())

    def test_output_includes_fetched_imported_and_processed_counts(self):
        account = create_email_account(email_address="sync@example.com")
        output = StringIO()

        with patch("apps.communications.management.commands.sync_email_account.EmailSyncService") as sync_service:
            sync_service.sync.return_value = {
                "email_account": account,
                "fetched_count": 5,
                "imported_count": 4,
                "processed_count": 3,
                "raw_messages": [],
                "imported_messages": [],
                "processing_results": [],
                "synced": True,
            }

            call_command("sync_email_account", str(account.id), stdout=output)

        text = output.getvalue()
        self.assertIn("account: sync@example.com", text)
        self.assertIn("fetched_count: 5", text)
        self.assertIn("imported_count: 4", text)
        self.assertIn("processed_count: 3", text)
        self.assertIn("synced: True", text)


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


class ConversationContextBuilderTests(TestCase):
    def create_context_message(self):
        organization = create_organization()
        account = create_email_account(organization=organization)
        thread = EmailThread.objects.create(
            organization=organization,
            account=account,
            external_thread_id="context-thread",
            subject="Context thread",
        )
        message = EmailMessage.objects.create(
            organization=organization,
            account=account,
            thread=thread,
            external_message_id="context-message",
            subject="Context message",
            body_text="Please review.",
        )
        return message

    def test_builds_context_for_single_email(self):
        message = create_email_message()

        context = ConversationContextBuilder.build(BuildConversationContextCommand(email_message=message))

        self.assertEqual(context.email_message, message)
        self.assertEqual(context.thread_messages, [message])
        self.assertEqual(context.project_links, [])
        self.assertEqual(context.questions, [])
        self.assertEqual(context.attachments, [])
        self.assertEqual(context.documents, [])
        self.assertEqual(context.evidence, [])

    def test_includes_thread_messages(self):
        message = self.create_context_message()
        EmailMessage.objects.create(
            organization=message.organization,
            account=message.account,
            thread=message.thread,
            external_message_id="context-message-2",
            subject="Follow-up",
        )

        context = ConversationContextBuilder.build(BuildConversationContextCommand(email_message=message))

        self.assertEqual(len(context.thread_messages), 2)

    def test_includes_confirmed_project_links(self):
        message = self.create_context_message()
        project = create_project(organization=message.organization, code="26071", name="Confirmed project")
        EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
            status=EmailProjectLink.Status.CONFIRMED,
            confidence=100,
            evidence={"user": "confirmed"},
        )

        context = ConversationContextBuilder.build(BuildConversationContextCommand(email_message=message))

        self.assertEqual(context.confirmed_projects, [project])
        self.assertEqual(context.suggested_projects, [])

    def test_includes_suggested_project_links(self):
        message = self.create_context_message()
        project = create_project(organization=message.organization, code="26072", name="Suggested project")
        link = EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
            confidence=75,
            evidence={"subject": "name match"},
        )

        context = ConversationContextBuilder.build(BuildConversationContextCommand(email_message=message))

        self.assertEqual(context.project_links, [link])
        self.assertEqual(context.suggested_projects, [project])

    def test_includes_questions(self):
        message = self.create_context_message()
        question = EmailQuestion.objects.create(
            organization=message.organization,
            email_message=message,
            question_text="Kas kinnitate?",
            confidence=70,
            evidence={"rule": "question_mark"},
        )

        context = ConversationContextBuilder.build(BuildConversationContextCommand(email_message=message))

        self.assertEqual(context.questions, [question])

    def test_includes_attachments(self):
        message = self.create_context_message()
        attachment = EmailAttachment.objects.create(
            organization=message.organization,
            email_message=message,
            original_filename="invoice.pdf",
        )

        context = ConversationContextBuilder.build(BuildConversationContextCommand(email_message=message))

        self.assertEqual(context.attachments, [attachment])

    def test_includes_linked_documents(self):
        message = self.create_context_message()
        document = Document.objects.create(
            organization=message.organization,
            title="Invoice document",
            original_filename="invoice.pdf",
            source=Document.Source.EMAIL_ATTACHMENT,
        )
        EmailAttachment.objects.create(
            organization=message.organization,
            email_message=message,
            document=document,
            original_filename="invoice.pdf",
        )

        context = ConversationContextBuilder.build(BuildConversationContextCommand(email_message=message))

        self.assertEqual(context.documents, [document])

    def test_includes_evidence(self):
        message = self.create_context_message()
        project = create_project(organization=message.organization, code="26073", name="Evidence project")
        EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
            confidence=90,
            evidence={"subject": "code match"},
        )
        EmailQuestion.objects.create(
            organization=message.organization,
            email_message=message,
            question_text="Can you confirm?",
            confidence=70,
            evidence={"rule": "question_mark"},
        )

        context = ConversationContextBuilder.build(BuildConversationContextCommand(email_message=message))

        self.assertEqual(len(context.evidence), 2)
        self.assertEqual({item["source"] for item in context.evidence}, {"project_link", "question"})

    def test_respects_include_thread_false(self):
        message = self.create_context_message()

        context = ConversationContextBuilder.build(
            BuildConversationContextCommand(email_message=message, include_thread=False)
        )

        self.assertEqual(context.thread_messages, [])

    def test_respects_include_projects_false(self):
        message = self.create_context_message()
        project = create_project(organization=message.organization, code="26074", name="Hidden project")
        EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
            evidence={"subject": "code match"},
        )

        context = ConversationContextBuilder.build(
            BuildConversationContextCommand(email_message=message, include_projects=False)
        )

        self.assertEqual(context.project_links, [])
        self.assertEqual(context.confirmed_projects, [])
        self.assertEqual(context.suggested_projects, [])
        self.assertEqual(context.evidence, [])

    def test_respects_include_questions_false(self):
        message = self.create_context_message()
        EmailQuestion.objects.create(
            organization=message.organization,
            email_message=message,
            question_text="Kas kinnitate?",
            evidence={"rule": "question_mark"},
        )

        context = ConversationContextBuilder.build(
            BuildConversationContextCommand(email_message=message, include_questions=False)
        )

        self.assertEqual(context.questions, [])
        self.assertEqual(context.evidence, [])

    def test_respects_include_attachments_false(self):
        message = self.create_context_message()
        EmailAttachment.objects.create(
            organization=message.organization,
            email_message=message,
            original_filename="invoice.pdf",
        )

        context = ConversationContextBuilder.build(
            BuildConversationContextCommand(email_message=message, include_attachments=False)
        )

        self.assertEqual(context.attachments, [])
        self.assertEqual(context.documents, [])

    def test_metadata_is_not_mutated(self):
        message = self.create_context_message()
        metadata = {"purpose": "reply-draft"}

        context = ConversationContextBuilder.build(
            BuildConversationContextCommand(email_message=message, metadata=metadata)
        )
        metadata["purpose"] = "caller-changed"

        self.assertEqual(context.metadata, {"purpose": "reply-draft"})

    def test_organization_scoping_is_respected(self):
        message = self.create_context_message()
        other_organization = create_organization(name="Other Org")
        other_project = create_project(organization=other_organization, code="99001", name="Other project")
        EmailMessage.objects.create(
            organization=other_organization,
            account=message.account,
            thread=message.thread,
            external_message_id="other-org-message",
            subject="Wrong organization",
        )
        EmailProjectLink.objects.create(
            organization=other_organization,
            email_message=message,
            project=other_project,
            evidence={"subject": "wrong organization"},
        )
        EmailQuestion.objects.create(
            organization=other_organization,
            email_message=message,
            question_text="Wrong organization?",
            evidence={"rule": "wrong organization"},
        )
        EmailAttachment.objects.create(
            organization=other_organization,
            email_message=message,
            original_filename="wrong-org.pdf",
        )

        context = ConversationContextBuilder.build(BuildConversationContextCommand(email_message=message))

        self.assertEqual(context.thread_messages, [message])
        self.assertEqual(context.project_links, [])
        self.assertEqual(context.questions, [])
        self.assertEqual(context.attachments, [])


class EmailAnswerDraftServiceTests(TestCase):
    def test_can_create_email_answer_draft(self):
        message = create_email_message()

        draft = EmailAnswerDraftService.create_draft(
            CreateEmailAnswerDraftCommand(
                email_message=message,
                draft_text="Draft answer",
            )
        )

        self.assertIsNotNone(draft.id)
        self.assertEqual(draft.organization, message.organization)
        self.assertEqual(draft.email_message, message)
        self.assertEqual(draft.draft_text, "Draft answer")

    def test_default_status_is_draft(self):
        message = create_email_message()

        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=message))

        self.assertEqual(draft.status, EmailAnswerDraft.Status.DRAFT)

    def test_default_generated_by_is_rule_based(self):
        message = create_email_message()

        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=message))

        self.assertEqual(draft.generated_by, EmailAnswerDraft.GeneratedBy.RULE_BASED)

    def test_question_can_be_null(self):
        message = create_email_message()

        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=message))

        self.assertIsNone(draft.question)

    def test_evidence_stored(self):
        message = create_email_message()
        evidence = {"sources": [{"type": "question", "confidence": 70}]}

        draft = EmailAnswerDraftService.create_draft(
            CreateEmailAnswerDraftCommand(email_message=message, evidence=evidence)
        )

        self.assertEqual(draft.evidence, evidence)

    def test_context_snapshot_stored(self):
        message = create_email_message()
        context_snapshot = {"thread_messages": ["Question"], "projects": ["26070"]}

        draft = EmailAnswerDraftService.create_draft(
            CreateEmailAnswerDraftCommand(email_message=message, context_snapshot=context_snapshot)
        )

        self.assertEqual(draft.context_snapshot, context_snapshot)

    def test_evidence_not_mutated(self):
        message = create_email_message()
        evidence = {"sources": [{"type": "question"}]}

        draft = EmailAnswerDraftService.create_draft(
            CreateEmailAnswerDraftCommand(email_message=message, evidence=evidence)
        )
        evidence["sources"][0]["type"] = "caller-changed"

        draft.refresh_from_db()
        self.assertEqual(draft.evidence, {"sources": [{"type": "question"}]})

    def test_context_snapshot_not_mutated(self):
        message = create_email_message()
        context_snapshot = {"messages": [{"subject": "Original"}]}

        draft = EmailAnswerDraftService.create_draft(
            CreateEmailAnswerDraftCommand(email_message=message, context_snapshot=context_snapshot)
        )
        context_snapshot["messages"][0]["subject"] = "caller-changed"

        draft.refresh_from_db()
        self.assertEqual(draft.context_snapshot, {"messages": [{"subject": "Original"}]})

    def test_metadata_not_mutated(self):
        message = create_email_message()
        metadata = {"source": {"name": "manual"}}

        EmailAnswerDraftService.create_draft(
            CreateEmailAnswerDraftCommand(email_message=message, metadata=metadata)
        )
        metadata["source"]["name"] = "caller-changed"

        audit_event = AuditEvent.objects.get(event_type="email.answer_draft_created")
        self.assertEqual(audit_event.metadata["draft_metadata"], {"source": {"name": "manual"}})

    def test_audit_event_created(self):
        message = create_email_message()

        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=message))

        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="email.answer_draft_created",
                object_type="EmailAnswerDraft",
                object_id=str(draft.id),
            ).exists()
        )

    def test_str_works(self):
        message = create_email_message(subject="Draft source")

        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=message))

        self.assertEqual(str(draft), "Answer draft for Draft source")

    def test_mark_needs_review_changes_status(self):
        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=create_email_message()))
        actor = get_user_model().objects.create_user(username="reviewer")

        EmailAnswerDraftService.mark_needs_review(
            MarkEmailAnswerDraftNeedsReviewCommand(draft=draft, actor=actor)
        )

        draft.refresh_from_db()
        self.assertEqual(draft.status, EmailAnswerDraft.Status.NEEDS_REVIEW)

    def test_mark_needs_review_sets_reviewed_by(self):
        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=create_email_message()))
        actor = get_user_model().objects.create_user(username="reviewer")

        EmailAnswerDraftService.mark_needs_review(
            MarkEmailAnswerDraftNeedsReviewCommand(draft=draft, actor=actor)
        )

        draft.refresh_from_db()
        self.assertEqual(draft.reviewed_by, actor)

    def test_approve_changes_status(self):
        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=create_email_message()))
        actor = get_user_model().objects.create_user(username="approver")

        EmailAnswerDraftService.approve(ApproveEmailAnswerDraftCommand(draft=draft, actor=actor))

        draft.refresh_from_db()
        self.assertEqual(draft.status, EmailAnswerDraft.Status.APPROVED)

    def test_approve_sets_approved_by_and_approved_at(self):
        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=create_email_message()))
        actor = get_user_model().objects.create_user(username="approver")

        EmailAnswerDraftService.approve(ApproveEmailAnswerDraftCommand(draft=draft, actor=actor))

        draft.refresh_from_db()
        self.assertEqual(draft.approved_by, actor)
        self.assertIsNotNone(draft.approved_at)

    def test_approve_copies_draft_text_to_final_text_if_missing(self):
        draft = EmailAnswerDraftService.create_draft(
            CreateEmailAnswerDraftCommand(email_message=create_email_message(), draft_text="Draft answer")
        )
        actor = get_user_model().objects.create_user(username="approver")

        EmailAnswerDraftService.approve(ApproveEmailAnswerDraftCommand(draft=draft, actor=actor))

        draft.refresh_from_db()
        self.assertEqual(draft.final_text, "Draft answer")

    def test_approve_uses_provided_final_text(self):
        draft = EmailAnswerDraftService.create_draft(
            CreateEmailAnswerDraftCommand(email_message=create_email_message(), draft_text="Draft answer")
        )
        actor = get_user_model().objects.create_user(username="approver")

        EmailAnswerDraftService.approve(
            ApproveEmailAnswerDraftCommand(draft=draft, actor=actor, final_text="Edited final answer")
        )

        draft.refresh_from_db()
        self.assertEqual(draft.final_text, "Edited final answer")

    def test_reject_changes_status(self):
        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=create_email_message()))
        actor = get_user_model().objects.create_user(username="reviewer")

        EmailAnswerDraftService.reject(RejectEmailAnswerDraftCommand(draft=draft, actor=actor))

        draft.refresh_from_db()
        self.assertEqual(draft.status, EmailAnswerDraft.Status.REJECTED)

    def test_reject_sets_reviewed_by(self):
        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=create_email_message()))
        actor = get_user_model().objects.create_user(username="reviewer")

        EmailAnswerDraftService.reject(RejectEmailAnswerDraftCommand(draft=draft, actor=actor))

        draft.refresh_from_db()
        self.assertEqual(draft.reviewed_by, actor)

    def test_reject_stores_reason(self):
        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=create_email_message()))
        actor = get_user_model().objects.create_user(username="reviewer")

        EmailAnswerDraftService.reject(
            RejectEmailAnswerDraftCommand(draft=draft, actor=actor, reason="Wrong tone")
        )

        draft.refresh_from_db()
        self.assertEqual(draft.metadata["rejection_reason"], "Wrong tone")
        audit_event = AuditEvent.objects.get(event_type="email.answer_draft_rejected")
        self.assertEqual(audit_event.metadata["review_metadata"]["reason"], "Wrong tone")

    def test_audit_event_created_for_each_review_action(self):
        actor = get_user_model().objects.create_user(username="reviewer")
        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=create_email_message()))

        EmailAnswerDraftService.mark_needs_review(
            MarkEmailAnswerDraftNeedsReviewCommand(draft=draft, actor=actor)
        )
        EmailAnswerDraftService.approve(ApproveEmailAnswerDraftCommand(draft=draft, actor=actor))
        EmailAnswerDraftService.reject(RejectEmailAnswerDraftCommand(draft=draft, actor=actor))

        self.assertTrue(AuditEvent.objects.filter(event_type="email.answer_draft_needs_review").exists())
        self.assertTrue(AuditEvent.objects.filter(event_type="email.answer_draft_approved").exists())
        self.assertTrue(AuditEvent.objects.filter(event_type="email.answer_draft_rejected").exists())

    def test_review_metadata_is_not_mutated(self):
        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=create_email_message()))
        actor = get_user_model().objects.create_user(username="reviewer")
        metadata = {"source": {"name": "manual-review"}}

        EmailAnswerDraftService.mark_needs_review(
            MarkEmailAnswerDraftNeedsReviewCommand(draft=draft, actor=actor, metadata=metadata)
        )
        metadata["source"]["name"] = "caller-changed"

        audit_event = AuditEvent.objects.get(event_type="email.answer_draft_needs_review")
        self.assertEqual(audit_event.metadata["review_metadata"], {"source": {"name": "manual-review"}})

    def test_review_action_rolls_back_if_audit_fails(self):
        draft = EmailAnswerDraftService.create_draft(CreateEmailAnswerDraftCommand(email_message=create_email_message()))
        actor = get_user_model().objects.create_user(username="reviewer")

        with patch("apps.communications.services.answer_drafts.AuditService.record") as record:
            record.side_effect = RuntimeError("audit failed")
            with self.assertRaises(RuntimeError):
                EmailAnswerDraftService.mark_needs_review(
                    MarkEmailAnswerDraftNeedsReviewCommand(draft=draft, actor=actor)
                )

        draft.refresh_from_db()
        self.assertEqual(draft.status, EmailAnswerDraft.Status.DRAFT)
        self.assertIsNone(draft.reviewed_by)


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


class DeterministicEmailProjectLinkingServiceTests(TestCase):
    def test_exact_project_code_in_subject_is_boundary_aware(self):
        organization = create_organization()
        project = create_project(organization=organization, code="26040", name="Boundary project")
        message = create_email_message(organization=organization, subject="[26040] Kawe Plaza")

        result = DeterministicEmailProjectLinkingService.evaluate(
            EvaluateEmailProjectLinksCommand(organization=organization, email_message_ids=(message.id,))
        )

        link = EmailProjectLink.objects.get(email_message=message, project=project)
        self.assertEqual(result.created_count, 1)
        self.assertEqual(link.source, EmailProjectLink.Source.EXACT_PROJECT_CODE_SUBJECT)
        self.assertEqual(link.confidence_band, EmailProjectLink.ConfidenceBand.HIGH)
        self.assertIn("Exact Project code 26040", link.evidence_summary)

    def test_project_code_does_not_match_inside_longer_number(self):
        organization = create_organization()
        create_project(organization=organization, code="26040", name="Boundary project")
        message = create_email_message(organization=organization, subject="Reference 1260407")

        result = DeterministicEmailProjectLinkingService.evaluate(
            EvaluateEmailProjectLinksCommand(organization=organization, email_message_ids=(message.id,))
        )

        self.assertEqual(result.suggestion_count, 0)
        self.assertEqual(EmailProjectLink.objects.count(), 0)

    def test_multiple_project_codes_create_separate_suggestions(self):
        organization = create_organization()
        first = create_project(organization=organization, code="26041", name="First project")
        second = create_project(organization=organization, code="26042", name="Second project")
        message = create_email_message(organization=organization, subject="26041 and 26042 both appear")

        result = DeterministicEmailProjectLinkingService.evaluate(
            EvaluateEmailProjectLinksCommand(organization=organization, email_message_ids=(message.id,))
        )

        self.assertEqual(result.suggestion_count, 2)
        self.assertEqual(result.conflict_count, 1)
        self.assertTrue(EmailProjectLink.objects.filter(email_message=message, project=first).exists())
        self.assertTrue(EmailProjectLink.objects.filter(email_message=message, project=second).exists())

    def test_repeated_evaluation_is_idempotent(self):
        organization = create_organization()
        create_project(organization=organization, code="26043", name="Idempotent project")
        message = create_email_message(organization=organization, subject="26043 update")

        DeterministicEmailProjectLinkingService.evaluate(
            EvaluateEmailProjectLinksCommand(organization=organization, email_message_ids=(message.id,))
        )
        result = DeterministicEmailProjectLinkingService.evaluate(
            EvaluateEmailProjectLinksCommand(organization=organization, email_message_ids=(message.id,))
        )

        self.assertEqual(EmailProjectLink.objects.count(), 1)
        self.assertEqual(result.unchanged_count, 1)

    def test_rejected_link_is_not_recreated(self):
        organization = create_organization()
        project = create_project(organization=organization, code="26044", name="Rejected deterministic project")
        message = create_email_message(organization=organization, subject="26044 update")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            status=EmailProjectLink.Status.REJECTED,
            confidence=20,
        )

        result = DeterministicEmailProjectLinkingService.evaluate(
            EvaluateEmailProjectLinksCommand(organization=organization, email_message_ids=(message.id,))
        )

        self.assertEqual(EmailProjectLink.objects.count(), 1)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(EmailProjectLink.objects.get().status, EmailProjectLink.Status.REJECTED)

    def test_dry_run_does_not_write_links(self):
        organization = create_organization()
        create_project(organization=organization, code="26045", name="Dry run project")
        message = create_email_message(organization=organization, subject="26045 update")

        result = DeterministicEmailProjectLinkingService.evaluate(
            EvaluateEmailProjectLinksCommand(
                organization=organization,
                email_message_ids=(message.id,),
                dry_run=True,
            )
        )

        self.assertTrue(result.dry_run)
        self.assertEqual(result.suggestion_count, 1)
        self.assertEqual(EmailProjectLink.objects.count(), 0)

    def test_confirmed_thread_link_creates_suggestion(self):
        organization = create_organization()
        account = create_email_account(organization)
        thread = EmailThread.objects.create(
            organization=organization,
            account=account,
            external_thread_id="thread-deterministic",
            subject="Thread",
        )
        project = create_project(organization=organization, code="26046", name="Thread project")
        confirmed_message = EmailMessage.objects.create(
            organization=organization,
            account=account,
            thread=thread,
            external_message_id="confirmed-thread-message",
            subject="Already confirmed",
        )
        new_message = EmailMessage.objects.create(
            organization=organization,
            account=account,
            thread=thread,
            external_message_id="new-thread-message",
            subject="Thread follow-up",
        )
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=confirmed_message,
            project=project,
            status=EmailProjectLink.Status.CONFIRMED,
            is_primary=True,
        )

        DeterministicEmailProjectLinkingService.evaluate(
            EvaluateEmailProjectLinksCommand(organization=organization, email_message_ids=(new_message.id,))
        )

        link = EmailProjectLink.objects.get(email_message=new_message)
        self.assertEqual(link.project, project)
        self.assertEqual(link.source, EmailProjectLink.Source.CONFIRMED_THREAD_LINK)
        self.assertEqual(link.status, EmailProjectLink.Status.SUGGESTED)

    def test_participant_alone_creates_no_suggestion(self):
        organization = create_organization()
        project = create_project(organization=organization, code="26047", name="Participant project")
        ProjectParty.objects.create(
            organization=organization,
            project=project,
            name="Customer",
            email="customer@example.com",
        )
        message = create_email_message(organization=organization, subject="General question")
        message.sender_email = "customer@example.com"
        message.save(update_fields=["sender_email"])

        result = DeterministicEmailProjectLinkingService.evaluate(
            EvaluateEmailProjectLinksCommand(organization=organization, email_message_ids=(message.id,))
        )

        self.assertEqual(result.suggestion_count, 0)
        self.assertEqual(EmailProjectLink.objects.count(), 0)

    def test_management_command_dry_run_summary(self):
        organization = create_organization()
        create_project(organization=organization, code="26048", name="Command project")
        message = create_email_message(organization=organization, subject="26048 update")
        output = StringIO()

        call_command(
            "evaluate_email_project_links",
            "--organization",
            str(organization.id),
            "--message",
            str(message.id),
            "--dry-run",
            stdout=output,
        )

        self.assertIn("evaluated=1", output.getvalue())
        self.assertIn("dry_run=True", output.getvalue())
        self.assertEqual(EmailProjectLink.objects.count(), 0)

    def test_management_command_requires_bounded_scope(self):
        organization = create_organization()

        with self.assertRaises(CommandError):
            call_command("evaluate_email_project_links", "--organization", str(organization.id))
