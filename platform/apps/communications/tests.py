from django.test import TestCase

from apps.core.services import CreateOrganizationCommand, OrganizationService

from .models import EmailAccount


def create_organization(name="Communications Org"):
    return OrganizationService.create(CreateOrganizationCommand(name=name))


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
