from io import BytesIO
from dataclasses import FrozenInstanceError
from django.db import IntegrityError
from django.test import TestCase
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from apps.accounting.connectors import (
    AccountingAPIError,
    AccountingAuthenticationError,
    AccountingConnectionError,
    AccountingRateLimitError,
    AccountingUnexpectedResponseError,
    MeritAuthentication,
    MeritAuthenticationService,
    MeritAPIClient,
)
from apps.accounting.dto import MeritDimensionDTO, MeritDimensionValueDTO
from apps.accounting.models import AccountingDimension, AccountingIntegration
from apps.accounting.secrets import SecretMissingError, SecretProvider
from apps.accounting.services import (
    AccountingDimensionValueService,
    AccountingDimensionSyncService,
    CreateAccountingDimensionValueCommand,
    ProjectCodeAllocationService,
    SuggestNextProjectCodeCommand,
    SyncAccountingDimensionsCommand,
)
from apps.core.models import AuditEvent
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.projects.models import Project


def create_organization(name="Accounting Org"):
    return OrganizationService.create(CreateOrganizationCommand(name=name))


def create_merit_integration(organization=None):
    organization = organization or create_organization()
    return AccountingIntegration.objects.create(
        organization=organization,
        provider=AccountingIntegration.Provider.MERIT,
        display_name="Merit API",
        api_base_url="https://merit.example.test",
        api_id="api-id",
        encrypted_secret_placeholder="api-secret",
    )


class FakeHTTPResponse:
    def __init__(self, body, *, status=200, headers=None):
        self.body = body.encode("utf-8")
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.body


class StaticSecretProvider:
    def __init__(self, secret="provider-secret"):
        self.secret = secret
        self.calls = 0

    def get_secret(self, integration):
        self.calls += 1
        return self.secret


class TrackingSecretProvider:
    def __init__(self, secret="api-secret"):
        self.secret = secret
        self.calls = 0

    def get_secret(self, integration):
        self.calls += 1
        return self.secret


def http_error(status, body=""):
    return HTTPError(
        url="https://merit.example.test/api",
        code=status,
        msg="Error",
        hdrs={},
        fp=BytesIO(body.encode("utf-8")),
    )


class AccountingIntegrationTests(TestCase):
    def test_can_create_integration(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Merit Aktiva",
            api_base_url="https://api.merit.ee/",
            api_id="test-api-id",
            encrypted_secret_placeholder="not-a-real-secret",
        )

        self.assertEqual(integration.display_name, "Merit Aktiva")

    def test_default_provider_is_merit(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Default provider",
        )

        self.assertEqual(integration.provider, AccountingIntegration.Provider.MERIT)

    def test_organization_linked(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Linked organization",
        )

        self.assertEqual(integration.organization, organization)

    def test_is_active_defaults_true(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Active integration",
        )

        self.assertTrue(integration.is_active)

    def test_str_works(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Merit production",
        )

        self.assertEqual(str(integration), "Merit production (merit)")

    def test_last_sync_at_can_be_null(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Never synced",
        )

        self.assertIsNone(integration.last_sync_at)


class AccountingDimensionTests(TestCase):
    def test_can_create_accounting_dimension(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26124",
            name="Kanarbiku",
        )

        self.assertEqual(dimension.code, "26124")
        self.assertEqual(dimension.name, "Kanarbiku")

    def test_default_provider_is_merit(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26125",
            name="Default provider",
        )

        self.assertEqual(dimension.provider, AccountingDimension.Provider.MERIT)

    def test_default_dimension_type_is_project(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26126",
            name="Default type",
        )

        self.assertEqual(dimension.dimension_type, AccountingDimension.DimensionType.PROJECT)

    def test_is_active_defaults_true(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26127",
            name="Active dimension",
        )

        self.assertTrue(dimension.is_active)

    def test_organization_code_uniqueness_works(self):
        organization = create_organization()
        AccountingDimension.objects.create(
            organization=organization,
            code="26128",
            name="First dimension",
        )

        with self.assertRaises(IntegrityError):
            AccountingDimension.objects.create(
                organization=organization,
                code="26128",
                name="Duplicate dimension",
            )

    def test_external_id_can_be_null(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26129",
            name="No external id",
        )

        self.assertIsNone(dimension.external_id)

    def test_last_synced_at_can_be_null(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26130",
            name="Never synced",
        )

        self.assertIsNone(dimension.last_synced_at)

    def test_str_includes_code_and_name(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26131",
            name="Display name",
        )

        self.assertEqual(str(dimension), "26131 Display name")


class SecretProviderTests(TestCase):
    def test_get_secret_returns_placeholder_secret(self):
        integration = create_merit_integration()

        secret = SecretProvider.get_secret(integration)

        self.assertEqual(secret, "api-secret")

    def test_missing_secret_raises_secret_missing_error(self):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = ""

        with self.assertRaises(SecretMissingError):
            SecretProvider.get_secret(integration)

    def test_mask_secret_returns_empty_for_empty_value(self):
        self.assertEqual(SecretProvider.mask_secret(""), "")
        self.assertEqual(SecretProvider.mask_secret(None), "")

    def test_mask_secret_hides_short_secret(self):
        self.assertEqual(SecretProvider.mask_secret("abc"), "****")
        self.assertEqual(SecretProvider.mask_secret("abcd"), "****")

    def test_mask_secret_masks_long_secret(self):
        self.assertEqual(SecretProvider.mask_secret("abcdefyz"), "ab****yz")

    def test_secret_is_not_included_in_exception_message(self):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = ""

        with self.assertRaises(SecretMissingError) as context:
            SecretProvider.get_secret(integration)

        self.assertNotIn("api-secret", str(context.exception))
        self.assertNotIn("encrypted_secret_placeholder", str(context.exception))

    def test_provider_does_not_mutate_integration(self):
        integration = create_merit_integration()
        original_secret = integration.encrypted_secret_placeholder
        original_api_id = integration.api_id

        SecretProvider.get_secret(integration)
        SecretProvider.mask_secret(integration.encrypted_secret_placeholder)

        self.assertEqual(integration.encrypted_secret_placeholder, original_secret)
        self.assertEqual(integration.api_id, original_api_id)


class MeritAuthenticationServiceTests(TestCase):
    def test_timestamp_generation_uses_merit_format(self):
        integration = create_merit_integration()
        service = MeritAuthenticationService()

        with patch.object(service, "_timestamp", return_value="20260102030405"):
            authentication = service.create_authentication(integration)

        self.assertEqual(authentication.timestamp, "20260102030405")
        self.assertEqual(len(authentication.timestamp), 14)

    def test_signature_is_deterministic(self):
        integration = create_merit_integration()
        service = MeritAuthenticationService()

        with patch.object(service, "_timestamp", return_value="20260102030405"):
            first = service.create_authentication(integration, body='{"hello":"world"}')
            second = service.create_authentication(integration, body='{"hello":"world"}')

        self.assertEqual(first.signature, second.signature)
        self.assertEqual(first.signature, "N2+UH9qs5blm/lqcpfJjedwse0cfUaY9JFkqDSMjRqQ=")

    def test_headers_generated_correctly(self):
        integration = create_merit_integration()
        service = MeritAuthenticationService()

        with patch.object(service, "_timestamp", return_value="20260102030405"):
            authentication = service.create_authentication(integration, body="{}")

        self.assertEqual(authentication.api_id, "api-id")
        self.assertEqual(authentication.headers, {})

    def test_secret_provider_called(self):
        integration = create_merit_integration()
        secret_provider = TrackingSecretProvider()
        service = MeritAuthenticationService(secret_provider=secret_provider)

        with patch.object(service, "_timestamp", return_value="20260102030405"):
            service.create_authentication(integration)

        self.assertEqual(secret_provider.calls, 1)

    def test_authentication_does_not_expose_secret(self):
        integration = create_merit_integration()
        service = MeritAuthenticationService()

        with patch.object(service, "_timestamp", return_value="20260102030405"):
            authentication = service.create_authentication(integration)

        self.assertNotIn("api-secret", repr(authentication))
        self.assertNotIn("api-secret", authentication.signature)

    def test_merit_authentication_is_immutable(self):
        authentication = MeritAuthentication(api_id="api-id", timestamp="20260102030405", signature="sig", headers={})

        with self.assertRaises(FrozenInstanceError):
            authentication.api_id = "changed"

    def test_missing_api_id_raises_authentication_error(self):
        integration = create_merit_integration()
        integration.api_id = ""

        with self.assertRaises(AccountingAuthenticationError):
            MeritAuthenticationService().create_authentication(integration)

    def test_missing_secret_raises_authentication_error(self):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = ""

        with self.assertRaises(AccountingAuthenticationError):
            MeritAuthenticationService().create_authentication(integration)


class MeritAPIClientTests(TestCase):
    def test_health_returns_structured_local_check_result(self):
        integration = create_merit_integration()

        health = MeritAPIClient(integration).health()

        self.assertTrue(health["healthy"])
        self.assertEqual(health["provider"], AccountingIntegration.Provider.MERIT)
        self.assertEqual(health["mode"], "local_check")
        self.assertIsNone(health["status_code"])
        self.assertIn("response_time_ms", health)

    def test_authenticate_returns_true_when_api_id_and_secret_exist(self):
        integration = create_merit_integration()

        self.assertTrue(MeritAPIClient(integration).authenticate())

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_authentication_error_is_mapped(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(401, '{"Message":"Invalid signature"}')

        with self.assertRaises(AccountingAuthenticationError):
            MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

    def test_missing_credentials_raise_authentication_error(self):
        integration = create_merit_integration()
        integration.api_id = ""
        integration.encrypted_secret_placeholder = ""

        with self.assertRaises(AccountingAuthenticationError):
            MeritAPIClient(integration).health()

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_timeout_is_mapped(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = TimeoutError()

        with self.assertRaises(AccountingConnectionError):
            MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_connection_error_is_mapped(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = URLError("network down")

        with self.assertRaises(AccountingConnectionError):
            MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_500_response_is_mapped(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(500, '{"Message":"Server error"}')

        with self.assertRaises(AccountingAPIError):
            MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_rate_limit_response_is_mapped(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(429, '{"Message":"Too many requests"}')

        with self.assertRaises(AccountingRateLimitError):
            MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_json_parsing(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true, "items": [1, 2]}')

        response = MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

        self.assertEqual(response, {"ok": True, "items": [1, 2]})

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_get_request_builds_url_with_params(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')

        MeritAPIClient(integration).request("GET", "/api/v1/items", params={"page": 2})

        request_object = urlopen_mock.call_args.args[0]
        self.assertEqual(request_object.get_method(), "GET")
        self.assertIn("/api/v1/items?", request_object.full_url)
        self.assertIn("page=2", request_object.full_url)
        self.assertIn("apiId=api-id", request_object.full_url)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_post_request_sends_json_payload(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')

        MeritAPIClient(integration).request("POST", "/api/v1/items", payload={"name": "Test"})

        request_object = urlopen_mock.call_args.args[0]
        self.assertEqual(request_object.get_method(), "POST")
        self.assertEqual(request_object.data.decode("utf-8"), '{"name":"Test"}')

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_invalid_json_response_is_mapped_when_content_type_is_json(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse("{not-json", headers={"Content-Type": "application/json"})

        with self.assertRaises(AccountingUnexpectedResponseError):
            MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_headers_created_correctly(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')

        MeritAPIClient(integration).request(
            "POST",
            "/api/v1/gettaxes",
            payload={"hello": "world"},
            headers={"X-Test": "yes"},
        )

        request_object = urlopen_mock.call_args.args[0]
        self.assertEqual(request_object.headers["Accept"], "application/json")
        self.assertEqual(request_object.headers["Content-type"], "application/json; charset=utf-8")
        self.assertEqual(request_object.headers["User-agent"], "OperationsWorkspacePlatform/1.0")
        self.assertEqual(request_object.headers["X-test"], "yes")

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_signed_request_contains_auth_query_without_secret(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')

        MeritAPIClient(integration).request("GET", "/api/v1/ping")

        request_object = urlopen_mock.call_args.args[0]
        self.assertIn("apiId=api-id", request_object.full_url)
        self.assertIn("timestamp=", request_object.full_url)
        self.assertIn("signature=", request_object.full_url)
        self.assertNotIn("api-secret", request_object.full_url)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_client_reads_secret_through_secret_provider(self, urlopen_mock):
        integration = create_merit_integration()
        secret_provider = SecretProvider()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')

        with patch.object(secret_provider, "get_secret", wraps=secret_provider.get_secret) as get_secret_mock:
            MeritAPIClient(integration, secret_provider=secret_provider).request(
                "POST",
                "/api/v1/gettaxes",
                payload={},
            )

        self.assertGreaterEqual(get_secret_mock.call_count, 1)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_client_does_not_read_secret_field_directly_when_provider_injected(self, urlopen_mock):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = ""
        secret_provider = StaticSecretProvider()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')

        MeritAPIClient(integration, secret_provider=secret_provider).request("POST", "/api/v1/gettaxes", payload={})

        request_object = urlopen_mock.call_args.args[0]
        self.assertIn("signature=", request_object.full_url)
        self.assertEqual(secret_provider.calls, 1)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_authentication_is_attached_to_request(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')
        authentication_service = MeritAuthenticationService()

        with patch.object(authentication_service, "_timestamp", return_value="20260102030405"):
            MeritAPIClient(integration, authentication_service=authentication_service).request(
                "POST",
                "/api/v1/gettaxes",
                payload={"hello": "world"},
            )

        request_object = urlopen_mock.call_args.args[0]
        self.assertIn("apiId=api-id", request_object.full_url)
        self.assertIn("timestamp=20260102030405", request_object.full_url)
        self.assertIn("signature=", request_object.full_url)
        self.assertNotIn("api-secret", request_object.full_url)

    def test_authentication_error_mapping_from_service(self):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = ""

        with self.assertRaises(AccountingAuthenticationError):
            MeritAPIClient(integration).request(
                "POST",
                "/api/v1/gettaxes",
                payload={},
            )


class MeritDimensionAPITests(TestCase):
    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_list_dimensions_empty_list(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"Dimensions": []}')

        dimensions = MeritAPIClient(integration).list_dimensions()

        self.assertEqual(dimensions, [])

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_list_dimensions_single_dimension(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse(
            '{"Dimensions": [{"Id": "m-1", "Code": "26124", "Name": "Kanarbiku", "DimensionType": "project"}]}'
        )

        dimensions = MeritAPIClient(integration).list_dimensions()

        self.assertEqual(len(dimensions), 1)
        self.assertEqual(dimensions[0].external_id, "m-1")
        self.assertEqual(dimensions[0].code, "26124")
        self.assertEqual(dimensions[0].name, "Kanarbiku")
        self.assertEqual(dimensions[0].dimension_type, "project")
        self.assertTrue(dimensions[0].active)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_list_dimensions_multiple_dimensions(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse(
            '{"Dimensions": ['
            '{"Id": "m-1", "Code": "26124", "Name": "Kanarbiku"},'
            '{"Id": "m-2", "Code": "26125", "Name": "Lennujaama", "Active": false}'
            "]}"
        )

        dimensions = MeritAPIClient(integration).list_dimensions()

        self.assertEqual([dimension.code for dimension in dimensions], ["26124", "26125"])
        self.assertFalse(dimensions[1].active)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_list_dimensions_flattens_merit_values_shape(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse(
            '{"Dimensions": [{"Name": "project", "Values": ['
            '{"Id": "v-1", "Code": "26124", "Name": "Kanarbiku"}'
            "]}]}"
        )

        dimensions = MeritAPIClient(integration).list_dimensions()

        self.assertEqual(len(dimensions), 1)
        self.assertEqual(dimensions[0].external_id, "v-1")
        self.assertEqual(dimensions[0].dimension_type, "project")

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_list_dimensions_missing_fields(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"Dimensions": [{}]}')

        dimensions = MeritAPIClient(integration).list_dimensions()

        self.assertEqual(dimensions[0].external_id, "")
        self.assertEqual(dimensions[0].code, "")
        self.assertEqual(dimensions[0].name, "")
        self.assertEqual(dimensions[0].dimension_type, "project")
        self.assertTrue(dimensions[0].active)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_list_dimensions_invalid_json(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse("{not-json", headers={"Content-Type": "application/json"})

        with self.assertRaises(AccountingUnexpectedResponseError):
            MeritAPIClient(integration).list_dimensions()

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_get_dimension_returns_dto(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"Id": "m-1", "Code": "26124", "Name": "Kanarbiku"}')

        dimension = MeritAPIClient(integration).get_dimension("m-1")

        self.assertEqual(dimension.external_id, "m-1")
        self.assertEqual(dimension.code, "26124")
        request_object = urlopen_mock.call_args.args[0]
        self.assertIn("/api/v2/getdimension?", request_object.full_url)
        self.assertIn("Id=m-1", request_object.full_url)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_get_dimension_404_returns_none(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(404, '{"Message":"Not found"}')

        dimension = MeritAPIClient(integration).get_dimension("missing")

        self.assertIsNone(dimension)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_dimension_401_maps_to_authentication_error(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(401, '{"Message":"Unauthorized"}')

        with self.assertRaises(AccountingAuthenticationError):
            MeritAPIClient(integration).list_dimensions()

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_dimension_429_maps_to_rate_limit_error(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(429, '{"Message":"Too many requests"}')

        with self.assertRaises(AccountingRateLimitError):
            MeritAPIClient(integration).list_dimensions()

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_dimension_500_maps_to_api_error(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(500, '{"Message":"Server error"}')

        with self.assertRaises(AccountingAPIError):
            MeritAPIClient(integration).list_dimensions()

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_payload(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse(
            '{"Dimensions": [{"Id": "new-1", "Code": "26126", "Name": "New Project"}]}'
        )

        dimension = MeritAPIClient(integration).create_dimension(
            code="26126",
            name="New Project",
            dimension_type="project",
        )

        request_object = urlopen_mock.call_args.args[0]
        payload = request_object.data.decode("utf-8")
        self.assertIn("/api/v2/senddimvalues?", request_object.full_url)
        self.assertIn('"Dimensions":[{"Name":"project","Values":[{"Code":"26126","Name":"New Project"}]}]', payload)
        self.assertEqual(dimension.external_id, "new-1")
        self.assertEqual(dimension.code, "26126")

    def test_dimension_dto_is_immutable(self):
        dimension = MeritDimensionDTO(
            external_id="m-1",
            code="26124",
            name="Kanarbiku",
            dimension_type="project",
            active=True,
            raw={"Id": "m-1"},
        )

        with self.assertRaises(FrozenInstanceError):
            dimension.code = "changed"

    def test_dimension_methods_do_not_write_database(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        project_count = Project.objects.count()
        dimension_count = AccountingDimension.objects.count()

        with patch("apps.accounting.connectors.merit.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value = FakeHTTPResponse('{"Dimensions": []}')
            MeritAPIClient(integration).list_dimensions()

        self.assertEqual(Project.objects.count(), project_count)
        self.assertEqual(AccountingDimension.objects.count(), dimension_count)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_value_builds_correct_payload(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse(
            '{"Dimensions": [{"DimValueId": "dv-1", "DimValueCode": "26126", "DimValueName": "New Project"}]}'
        )

        value = MeritAPIClient(integration).create_dimension_value(
            code="26126",
            name="New Project",
            dimension_type="project",
            dimension_id="dim-project",
            external_id="dv-1",
            end_date="2026-12-31",
        )

        request_object = urlopen_mock.call_args.args[0]
        payload = request_object.data.decode("utf-8")
        self.assertIn("/api/v2/senddimvalues?", request_object.full_url)
        self.assertIn(
            '"Dimensions":[{"DimId":"dim-project","DimValueCode":"26126","DimValueName":"New Project",'
            '"DimValueId":"dv-1","EndDate":"2026-12-31"}]',
            payload,
        )
        self.assertEqual(value.external_id, "dv-1")
        self.assertEqual(value.code, "26126")
        self.assertEqual(value.name, "New Project")
        self.assertEqual(value.dimension_type, "project")

    def test_create_dimension_value_requires_dimension_id(self):
        integration = create_merit_integration()

        with self.assertRaises(ValueError):
            MeritAPIClient(integration).create_dimension_value(code="26126", name="New Project")

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_value_maps_response_to_dto(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse(
            '{"Dimensions": [{"DimValueId": "dv-1", "DimValueCode": "26126", "DimValueName": "New Project", "Active": true}]}'
        )

        value = MeritAPIClient(integration).create_dimension_value(
            code="26126",
            name="New Project",
            dimension_id="dim-project",
        )

        self.assertIsInstance(value, MeritDimensionValueDTO)
        self.assertEqual(value.external_id, "dv-1")
        self.assertEqual(value.raw["DimValueId"], "dv-1")
        self.assertTrue(value.active)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_value_401_maps_to_authentication_error(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(401, '{"Message":"Unauthorized"}')

        with self.assertRaises(AccountingAuthenticationError):
            MeritAPIClient(integration).create_dimension_value(
                code="26126",
                name="New Project",
                dimension_id="dim-project",
            )

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_value_429_maps_to_rate_limit_error(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(429, '{"Message":"Too many requests"}')

        with self.assertRaises(AccountingRateLimitError):
            MeritAPIClient(integration).create_dimension_value(
                code="26126",
                name="New Project",
                dimension_id="dim-project",
            )

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_value_500_maps_to_api_error(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(500, '{"Message":"Server error"}')

        with self.assertRaises(AccountingAPIError):
            MeritAPIClient(integration).create_dimension_value(
                code="26126",
                name="New Project",
                dimension_id="dim-project",
            )

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_value_invalid_json(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse("{not-json", headers={"Content-Type": "application/json"})

        with self.assertRaises(AccountingUnexpectedResponseError):
            MeritAPIClient(integration).create_dimension_value(
                code="26126",
                name="New Project",
                dimension_id="dim-project",
            )

    def test_dimension_value_methods_do_not_write_database(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        project_count = Project.objects.count()
        dimension_count = AccountingDimension.objects.count()

        with patch("apps.accounting.connectors.merit.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value = FakeHTTPResponse(
                '{"Dimensions": [{"DimValueId": "dv-1", "DimValueCode": "26126", "DimValueName": "New Project"}]}'
            )
            MeritAPIClient(integration).create_dimension_value(
                code="26126",
                name="New Project",
                dimension_id="dim-project",
            )

        self.assertEqual(Project.objects.count(), project_count)
        self.assertEqual(AccountingDimension.objects.count(), dimension_count)


class AccountingDimensionSyncServiceTests(TestCase):
    def test_creates_new_accounting_dimension_from_dto(self):
        integration = create_merit_integration()
        dto = MeritDimensionDTO("m-1", "26124", "Kanarbiku", "project", True, {"Id": "m-1"})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        dimension = AccountingDimension.objects.get(code="26124")
        self.assertEqual(result.created_count, 1)
        self.assertEqual(dimension.organization, integration.organization)
        self.assertEqual(dimension.provider, integration.provider)
        self.assertEqual(dimension.integration, integration)
        self.assertEqual(dimension.external_id, "m-1")
        self.assertEqual(dimension.name, "Kanarbiku")
        self.assertEqual(dimension.raw_data, {"Id": "m-1"})
        self.assertIsNotNone(dimension.last_synced_at)

    def test_updates_existing_accounting_dimension(self):
        integration = create_merit_integration()
        dimension = AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="m-1",
            code="26124",
            name="Old name",
            last_synced_at="2026-01-01T00:00:00Z",
        )
        dto = MeritDimensionDTO("m-1", "26124", "New name", "project", True, {"Id": "m-1", "Name": "New name"})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        dimension.refresh_from_db()
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(dimension.name, "New name")
        self.assertEqual(dimension.raw_data, {"Id": "m-1", "Name": "New name"})

    def test_unchanged_dimension_counted(self):
        integration = create_merit_integration()
        AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="m-1",
            code="26124",
            name="Kanarbiku",
            raw_data={"Id": "m-1"},
            last_synced_at="2026-01-01T00:00:00Z",
        )
        dto = MeritDimensionDTO("m-1", "26124", "Kanarbiku", "project", True, {"Id": "m-1"})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        self.assertEqual(result.unchanged_count, 1)
        self.assertEqual(result.updated_count, 0)

    def test_archives_missing_previously_synced_dimension(self):
        integration = create_merit_integration()
        dimension = AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="m-old",
            code="26123",
            name="Old project",
            last_synced_at="2026-01-01T00:00:00Z",
        )
        dto = MeritDimensionDTO("m-1", "26124", "Kanarbiku", "project", True, {"Id": "m-1"})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        dimension.refresh_from_db()
        self.assertEqual(result.archived_count, 1)
        self.assertFalse(dimension.is_active)

    def test_detects_duplicate_incoming_code_conflict(self):
        integration = create_merit_integration()
        dtos = [
            MeritDimensionDTO("m-1", "26124", "Kanarbiku A", "project", True, {}),
            MeritDimensionDTO("m-2", "26124", "Kanarbiku B", "project", True, {}),
        ]

        with patch.object(MeritAPIClient, "list_dimensions", return_value=dtos):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        self.assertEqual(result.conflict_count, 1)
        self.assertEqual(result.conflicts[0]["type"], "duplicate_incoming_code")
        self.assertFalse(AccountingDimension.objects.filter(code="26124").exists())

    def test_detects_same_code_different_external_id_conflict(self):
        integration = create_merit_integration()
        AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="m-existing",
            code="26124",
            name="Existing",
        )
        dto = MeritDimensionDTO("m-new", "26124", "Incoming", "project", True, {})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        self.assertEqual(result.conflict_count, 1)
        self.assertEqual(result.conflicts[0]["type"], "same_code_different_external_id")
        self.assertEqual(AccountingDimension.objects.get(code="26124").external_id, "m-existing")

    def test_detects_same_external_id_different_code_conflict(self):
        integration = create_merit_integration()
        AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="m-1",
            code="26124",
            name="Existing",
        )
        dto = MeritDimensionDTO("m-1", "26125", "Incoming", "project", True, {})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        self.assertEqual(result.conflict_count, 1)
        self.assertEqual(result.conflicts[0]["type"], "same_external_id_different_code")
        self.assertEqual(AccountingDimension.objects.get(external_id="m-1").code, "26124")

    def test_creates_sync_started_and_completed_audit_events(self):
        integration = create_merit_integration()
        dto = MeritDimensionDTO("m-1", "26124", "Kanarbiku", "project", True, {})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        event_types = list(AuditEvent.objects.values_list("event_type", flat=True))
        self.assertIn("accounting_dimension_sync_started", event_types)
        self.assertIn("accounting_dimension_sync_completed", event_types)

    def test_metadata_is_not_mutated(self):
        integration = create_merit_integration()
        metadata = {"source": {"requested_by": "test"}}
        original_metadata = {"source": {"requested_by": "test"}}

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[]):
            result = AccountingDimensionSyncService.sync(
                SyncAccountingDimensionsCommand(integration=integration, metadata=metadata)
            )

        result.metadata["source"]["requested_by"] = "changed"
        self.assertEqual(metadata, original_metadata)

    def test_api_errors_propagate_safely(self):
        integration = create_merit_integration()

        with patch.object(MeritAPIClient, "list_dimensions", side_effect=AccountingAPIError("Merit down")):
            with self.assertRaises(AccountingAPIError):
                AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

    def test_organization_scoping_works(self):
        integration = create_merit_integration()
        other_integration = create_merit_integration(create_organization("Other Org"))
        AccountingDimension.objects.create(
            organization=other_integration.organization,
            integration=other_integration,
            provider=other_integration.provider,
            external_id="m-1",
            code="26124",
            name="Other org dimension",
        )
        dto = MeritDimensionDTO("m-1", "26124", "Own org dimension", "project", True, {})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        self.assertEqual(result.created_count, 1)
        self.assertEqual(AccountingDimension.objects.filter(code="26124").count(), 2)

    def test_no_project_objects_created(self):
        integration = create_merit_integration()
        project_count = Project.objects.count()
        dto = MeritDimensionDTO("m-1", "26124", "Kanarbiku", "project", True, {})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        self.assertEqual(Project.objects.count(), project_count)


class AccountingDimensionValueServiceTests(TestCase):
    def _dto(self, external_id="dv-1", code="26124", name="Kanarbiku", active=True):
        return MeritDimensionValueDTO(
            external_id=external_id,
            code=code,
            name=name,
            dimension_type="project",
            active=active,
            raw={"DimValueId": external_id, "DimValueCode": code, "DimValueName": name},
        )

    def test_creates_dimension_via_mocked_merit_api_client(self):
        integration = create_merit_integration()
        dto = self._dto()

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=dto) as create_mock:
            result = AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                    dimension_id="dim-project",
                )
            )

        create_mock.assert_called_once_with(
            code="26124",
            name="Kanarbiku",
            dimension_type="project",
            dimension_id="dim-project",
            external_id=None,
            end_date=None,
        )
        self.assertTrue(result.created)
        self.assertFalse(result.updated)
        self.assertEqual(result.dto, dto)
        self.assertEqual(result.dimension.organization, integration.organization)
        self.assertEqual(result.dimension.provider, integration.provider)
        self.assertEqual(result.dimension.integration, integration)
        self.assertEqual(result.dimension.external_id, "dv-1")
        self.assertEqual(result.dimension.code, "26124")
        self.assertEqual(result.dimension.name, "Kanarbiku")
        self.assertEqual(result.dimension.raw_data, dto.raw)

    def test_updates_existing_accounting_dimension(self):
        integration = create_merit_integration()
        dimension = AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="dv-1",
            code="26124",
            name="Old name",
        )
        dto = self._dto(name="New name")

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=dto):
            result = AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="New name",
                    dimension_id="dim-project",
                    external_id="dv-1",
                )
            )

        dimension.refresh_from_db()
        self.assertFalse(result.created)
        self.assertTrue(result.updated)
        self.assertEqual(dimension.name, "New name")
        self.assertIsNotNone(dimension.last_synced_at)

    def test_does_not_duplicate_same_code(self):
        integration = create_merit_integration()
        AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="old-id",
            code="26124",
            name="Existing",
        )
        dto = self._dto(external_id="dv-1", code="26124", name="Updated")

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=dto):
            result = AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Updated",
                    dimension_id="dim-project",
                )
            )

        self.assertFalse(result.created)
        self.assertEqual(AccountingDimension.objects.filter(code="26124").count(), 1)
        self.assertEqual(AccountingDimension.objects.get(code="26124").external_id, "dv-1")

    def test_sets_last_synced_at(self):
        integration = create_merit_integration()

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=self._dto()):
            result = AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                    dimension_id="dim-project",
                )
            )

        self.assertIsNotNone(result.dimension.last_synced_at)

    def test_creates_audit_event(self):
        integration = create_merit_integration()

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=self._dto()):
            AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                    dimension_id="dim-project",
                )
            )

        event = AuditEvent.objects.get(event_type="accounting_dimension_value_created")
        self.assertEqual(event.organization, integration.organization)
        self.assertEqual(event.object_type, "AccountingDimension")
        self.assertEqual(event.metadata["created"], True)

    def test_metadata_is_not_mutated(self):
        integration = create_merit_integration()
        metadata = {"source": {"requested_by": "test"}}
        original_metadata = {"source": {"requested_by": "test"}}

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=self._dto()):
            result = AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                    dimension_id="dim-project",
                    metadata=metadata,
                )
            )

        result.metadata["source"]["requested_by"] = "changed"
        self.assertEqual(metadata, original_metadata)

    def test_api_error_prevents_db_write(self):
        integration = create_merit_integration()

        with patch.object(
            MeritAPIClient,
            "create_dimension_value",
            side_effect=AccountingAPIError("Merit down"),
        ):
            with self.assertRaises(AccountingAPIError):
                AccountingDimensionValueService.create(
                    CreateAccountingDimensionValueCommand(
                        integration=integration,
                        code="26124",
                        name="Kanarbiku",
                        dimension_id="dim-project",
                    )
                )

        self.assertFalse(AccountingDimension.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(event_type="accounting_dimension_value_created").exists())

    def test_requires_dimension_id(self):
        integration = create_merit_integration()

        with self.assertRaises(ValueError):
            AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                )
            )

    def test_organization_scoped(self):
        integration = create_merit_integration()
        other_integration = create_merit_integration(create_organization("Other Org"))
        AccountingDimension.objects.create(
            organization=other_integration.organization,
            integration=other_integration,
            provider=other_integration.provider,
            external_id="dv-1",
            code="26124",
            name="Other org dimension",
        )

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=self._dto()):
            result = AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                    dimension_id="dim-project",
                )
            )

        self.assertTrue(result.created)
        self.assertEqual(AccountingDimension.objects.filter(code="26124").count(), 2)

    def test_no_project_created(self):
        integration = create_merit_integration()
        project_count = Project.objects.count()

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=self._dto()):
            AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                    dimension_id="dim-project",
                )
            )

        self.assertEqual(Project.objects.count(), project_count)


class ProjectCodeAllocationServiceTests(TestCase):
    def test_suggests_next_code_from_projects(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Existing 1")
        Project.objects.create(organization=organization, code="26125", name="Existing 2")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26126")

    def test_suggests_next_code_from_accounting_dimensions(self):
        organization = create_organization()
        AccountingDimension.objects.create(organization=organization, code="26124", name="Existing 1")
        AccountingDimension.objects.create(organization=organization, code="26125", name="Existing 2")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26126")

    def test_merges_project_and_accounting_dimension_codes(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Workspace project")
        AccountingDimension.objects.create(organization=organization, code="26125", name="Merit dimension")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26126")
        self.assertEqual(suggestion.used_codes, ["26124", "26125"])

    def test_ignores_non_numeric_codes(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="ABC", name="Non numeric")
        AccountingDimension.objects.create(organization=organization, code="26125", name="Numeric")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26126")
        self.assertIn("ABC", suggestion.used_codes)

    def test_respects_min_code(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Existing")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization, min_code=27000)
        )

        self.assertEqual(suggestion.suggested_code, "27000")

    def test_prefix_considers_matching_codes_and_preserves_suffix_width(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26001", name="Matching 1")
        Project.objects.create(organization=organization, code="26002", name="Matching 2")
        Project.objects.create(organization=organization, code="27099", name="Other prefix")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization, prefix="26")
        )

        self.assertEqual(suggestion.suggested_code, "26003")

    def test_organization_isolation(self):
        organization = create_organization()
        other_organization = create_organization("Other Org")
        Project.objects.create(organization=other_organization, code="99999", name="Other")
        Project.objects.create(organization=organization, code="26124", name="Own")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26125")
        self.assertNotIn("99999", suggestion.used_codes)

    def test_inactive_dimensions_are_ignored_for_allocation(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Workspace project")
        AccountingDimension.objects.create(
            organization=organization,
            code="26125",
            name="Inactive dimension",
            is_active=False,
        )

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26125")
        self.assertNotIn("26125", suggestion.used_codes)

    def test_metadata_is_not_mutated(self):
        organization = create_organization()
        metadata = {"source": {"requested_by": "test"}}
        original_metadata = {"source": {"requested_by": "test"}}

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization, metadata=metadata)
        )

        suggestion.metadata["source"] = "changed"
        self.assertEqual(metadata, original_metadata)

    def test_returns_source_summary(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Workspace project")
        AccountingDimension.objects.create(organization=organization, code="26125", name="Merit dimension")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.source_summary["project_codes_count"], 1)
        self.assertEqual(suggestion.source_summary["accounting_dimension_codes_count"], 1)
        self.assertEqual(suggestion.source_summary["used_numeric_codes_count"], 2)

    def test_no_database_writes_except_test_setup(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Workspace project")
        project_count = Project.objects.count()
        dimension_count = AccountingDimension.objects.count()

        ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(Project.objects.count(), project_count)
        self.assertEqual(AccountingDimension.objects.count(), dimension_count)
