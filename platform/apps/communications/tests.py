from django.db import IntegrityError
from django.test import TestCase

from apps.core.services import CreateOrganizationCommand, OrganizationService

from .models import EmailAccount, EmailMessage, EmailThread


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
