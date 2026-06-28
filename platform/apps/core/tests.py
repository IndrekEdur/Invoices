from django.test import SimpleTestCase, TestCase

from .models import Organization


class HealthCheckTests(SimpleTestCase):
    def test_health_endpoint_returns_ok(self):
        response = self.client.get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class OrganizationModelTests(TestCase):
    def test_can_create_organization(self):
        organization = Organization.objects.create(
            name="Erlin",
            legal_name="Erlin OU",
            registration_number="12345678",
            vat_number="EE123456789",
            metadata={"source": "test"},
        )

        self.assertIsNotNone(organization.id)
        self.assertIsNotNone(organization.uuid)
        self.assertEqual(organization.country, "EE")
        self.assertEqual(organization.currency, "EUR")
        self.assertEqual(organization.timezone, "Europe/Tallinn")

    def test_default_organization_type_is_company(self):
        organization = Organization.objects.create(name="Default type")

        self.assertEqual(organization.organization_type, Organization.Type.COMPANY)

    def test_default_is_active_is_true(self):
        organization = Organization.objects.create(name="Active organization")

        self.assertTrue(organization.is_active)

    def test_str_returns_name(self):
        organization = Organization.objects.create(name="Readable name")

        self.assertEqual(str(organization), "Readable name")
