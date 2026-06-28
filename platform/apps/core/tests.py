from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from .models import AppUserProfile, AuditEvent, Organization, OrganizationConfiguration
from .services import AuditService, CreateOrganizationCommand, OrganizationService


def create_organization(name="Erlin", **kwargs):
    return OrganizationService.create(CreateOrganizationCommand(name=name, **kwargs))


class HealthCheckTests(SimpleTestCase):
    def test_health_endpoint_returns_ok(self):
        response = self.client.get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class OrganizationModelTests(TestCase):
    def test_can_create_organization(self):
        organization = create_organization(
            name="Erlin",
            legal_name="Erlin OU",
            registration_number="12345678",
            vat_number="EE123456789",
        )

        self.assertIsNotNone(organization.id)
        self.assertIsNotNone(organization.uuid)
        self.assertEqual(organization.country, "EE")
        self.assertEqual(organization.currency, "EUR")
        self.assertEqual(organization.timezone, "Europe/Tallinn")

    def test_default_organization_type_is_company(self):
        organization = create_organization(name="Default type")

        self.assertEqual(organization.organization_type, Organization.Type.COMPANY)

    def test_default_is_active_is_true(self):
        organization = create_organization(name="Active organization")

        self.assertTrue(organization.is_active)

    def test_str_returns_name(self):
        organization = create_organization(name="Readable name")

        self.assertEqual(str(organization), "Readable name")


class OrganizationConfigurationModelTests(TestCase):
    def test_can_create_organization_configuration(self):
        organization = create_organization(name="Erlin")
        configuration = organization.configuration
        configuration.metadata = {"source": "test"}
        configuration.save(update_fields=["metadata", "updated_at"])

        self.assertIsNotNone(configuration.id)
        self.assertEqual(configuration.metadata, {"source": "test"})

    def test_defaults_are_correct(self):
        organization = create_organization(name="Default config")
        configuration = organization.configuration

        self.assertEqual(configuration.default_currency, "EUR")
        self.assertEqual(configuration.default_timezone, "Europe/Tallinn")
        self.assertEqual(configuration.language, "et")
        self.assertEqual(configuration.date_format, "YYYY-MM-DD")
        self.assertEqual(configuration.number_format, "1 234,56")

    def test_linked_to_organization(self):
        organization = create_organization(name="Linked config")
        configuration = organization.configuration

        self.assertEqual(configuration.organization, organization)
        self.assertEqual(organization.configuration, configuration)

    def test_auto_approval_enabled_defaults_false(self):
        organization = create_organization(name="Manual approval")
        configuration = organization.configuration

        self.assertFalse(configuration.auto_approval_enabled)

    def test_auto_approval_threshold_defaults_zero(self):
        organization = create_organization(name="Zero threshold")
        configuration = organization.configuration

        self.assertEqual(configuration.auto_approval_threshold, 0)

    def test_str_works(self):
        organization = create_organization(name="Readable config")
        configuration = organization.configuration

        self.assertEqual(str(configuration), "Configuration for Readable config")


class AppUserProfileModelTests(TestCase):
    def test_can_create_profile(self):
        user = get_user_model().objects.create_user(username="profile-user")

        profile = AppUserProfile.objects.create(user=user, metadata={"theme": "light"})

        self.assertIsNotNone(profile.id)
        self.assertEqual(profile.metadata, {"theme": "light"})

    def test_profile_links_to_user(self):
        user = get_user_model().objects.create_user(username="linked-user")

        profile = AppUserProfile.objects.create(user=user)

        self.assertEqual(profile.user, user)
        self.assertEqual(user.app_profile, profile)

    def test_active_organization_can_be_null(self):
        user = get_user_model().objects.create_user(username="no-org-user")

        profile = AppUserProfile.objects.create(user=user)

        self.assertIsNone(profile.active_organization)

    def test_active_organization_can_be_set(self):
        user = get_user_model().objects.create_user(username="org-user")
        organization = create_organization(name="Erlin")

        profile = AppUserProfile.objects.create(user=user, active_organization=organization)

        self.assertEqual(profile.active_organization, organization)

    def test_str_includes_username(self):
        user = get_user_model().objects.create_user(username="readable-user")
        profile = AppUserProfile.objects.create(user=user)

        self.assertIn("readable-user", str(profile))


class AuditEventModelTests(TestCase):
    def test_can_create_audit_event(self):
        organization = create_organization(name="Erlin")
        user = get_user_model().objects.create_user(username="audit-user")

        event = AuditEvent.objects.create(
            organization=organization,
            actor=user,
            event_type="invoice.approved",
            object_type="Invoice",
            object_id="123",
            message="Invoice approved.",
        )

        self.assertIsNotNone(event.id)
        self.assertIsNotNone(event.uuid)
        self.assertEqual(event.organization, organization)
        self.assertEqual(event.actor, user)

    def test_organization_nullable(self):
        event = AuditEvent.objects.create(
            event_type="system.started",
            object_type="System",
            object_id="platform",
        )

        self.assertIsNone(event.organization)

    def test_actor_nullable(self):
        organization = create_organization(name="Erlin")

        event = AuditEvent.objects.create(
            organization=organization,
            event_type="integration.sync",
            object_type="IntegrationSyncRun",
            object_id="sync-1",
        )

        self.assertIsNone(event.actor)

    def test_metadata_stored(self):
        event = AuditEvent.objects.create(
            event_type="invoice.sent",
            object_type="Invoice",
            object_id="456",
            metadata={"provider": "merit", "status": "ok"},
        )

        self.assertEqual(event.metadata["provider"], "merit")
        self.assertEqual(event.metadata["status"], "ok")

    def test_str_works(self):
        event = AuditEvent.objects.create(
            event_type="document.parsed",
            object_type="Document",
            object_id="789",
        )

        self.assertEqual(str(event), "document.parsed Document:789")


class AuditServiceTests(TestCase):
    def test_record_creates_audit_event(self):
        event = AuditService.record(
            event_type="invoice.approved",
            object_type="Invoice",
            object_id="123",
            message="Approved from review screen.",
        )

        self.assertIsInstance(event, AuditEvent)
        self.assertEqual(AuditEvent.objects.count(), 1)
        self.assertEqual(event.event_type, "invoice.approved")
        self.assertEqual(event.message, "Approved from review screen.")

    def test_record_defaults_metadata_to_empty_dict(self):
        event = AuditService.record(event_type="system.started")

        self.assertEqual(event.metadata, {})

    def test_record_does_not_mutate_caller_metadata(self):
        metadata = {"provider": "merit"}

        event = AuditService.record(event_type="invoice.sent", metadata=metadata)
        event.metadata["status"] = "ok"

        self.assertEqual(metadata, {"provider": "merit"})

    def test_record_accepts_organization(self):
        organization = create_organization(name="Erlin")

        event = AuditService.record(event_type="document.received", organization=organization)

        self.assertEqual(event.organization, organization)

    def test_record_accepts_actor(self):
        user = get_user_model().objects.create_user(username="service-user")

        event = AuditService.record(event_type="document.received", actor=user)

        self.assertEqual(event.actor, user)


class OrganizationServiceTests(TestCase):
    def test_create_creates_organization(self):
        organization = OrganizationService.create(
            CreateOrganizationCommand(
                name="Service Org",
                legal_name="Service Org OU",
                registration_number="12345678",
                vat_number="EE123456789",
            )
        )

        self.assertEqual(Organization.objects.count(), 1)
        self.assertEqual(organization.name, "Service Org")
        self.assertEqual(organization.legal_name, "Service Org OU")

    def test_create_creates_configuration(self):
        organization = OrganizationService.create(
            CreateOrganizationCommand(name="Configured Org", currency="USD", timezone="UTC")
        )

        self.assertEqual(OrganizationConfiguration.objects.count(), 1)
        self.assertEqual(organization.configuration.default_currency, "USD")
        self.assertEqual(organization.configuration.default_timezone, "UTC")

    def test_create_creates_audit_event(self):
        organization = OrganizationService.create(CreateOrganizationCommand(name="Audited Org"))

        audit_event = AuditEvent.objects.get(event_type="organization.created")
        self.assertEqual(audit_event.organization, organization)
        self.assertEqual(audit_event.object_type, "Organization")
        self.assertEqual(audit_event.object_id, str(organization.id))

    def test_create_returns_organization(self):
        organization = OrganizationService.create(CreateOrganizationCommand(name="Returned Org"))

        self.assertIsInstance(organization, Organization)
        self.assertEqual(organization.name, "Returned Org")

    def test_create_is_transactional(self):
        with patch("apps.core.services.organization.AuditService.record", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                OrganizationService.create(CreateOrganizationCommand(name="Rolled Back Org"))

        self.assertFalse(Organization.objects.filter(name="Rolled Back Org").exists())
        self.assertEqual(OrganizationConfiguration.objects.count(), 0)
