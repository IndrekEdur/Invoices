import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import time
from copy import deepcopy
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin

from apps.accounting.dto import MeritDimensionDTO
from apps.accounting.models import AccountingIntegration
from apps.accounting.secrets import SecretMissingError, SecretProvider

from .base import AccountingConnector
from .exceptions import (
    AccountingAPIError,
    AccountingAuthenticationError,
    AccountingConnectionError,
    AccountingRateLimitError,
    AccountingUnexpectedResponseError,
)


DEFAULT_MERIT_BASE_URL = "https://aktiva.merit.ee"
DEFAULT_TIMEOUT_SECONDS = 30


class MeritAPIClient(AccountingConnector):
    """Low-level Merit Aktiva API client.

    This class is the integration boundary for direct Merit HTTP calls.
    Business services should use this connector instead of urllib/requests.
    """

    DIMENSIONS_LIST_ENDPOINT = "/api/v2/getdimensions"
    DIMENSION_DETAIL_ENDPOINT = "/api/v2/getdimension"
    DIMENSIONS_CREATE_ENDPOINT = "/api/v2/senddimvalues"

    def __init__(self, integration: AccountingIntegration, *, timeout=DEFAULT_TIMEOUT_SECONDS, secret_provider=None):
        if integration.provider != AccountingIntegration.Provider.MERIT:
            raise ValueError("MeritAPIClient requires an AccountingIntegration with provider='merit'.")

        self.integration = integration
        self.api_base_url = (integration.api_base_url or DEFAULT_MERIT_BASE_URL).rstrip("/")
        self.api_id = integration.api_id.strip()
        self.secret_provider = secret_provider or SecretProvider()
        self.timeout = timeout

    def authenticate(self):
        if not self.api_id:
            raise AccountingAuthenticationError("Merit API credentials are not configured.")
        try:
            self.secret_provider.get_secret(self.integration)
        except SecretMissingError as exc:
            raise AccountingAuthenticationError("Merit API credentials are not configured.") from exc
        return True

    def request(self, method, path, *, payload=None, params=None, headers=None, timeout=None):
        self.authenticate()
        method = method.upper()
        if method not in {"GET", "POST"}:
            raise ValueError("MeritAPIClient supports only GET and POST requests.")

        body = self._json_body(payload if payload is not None else {})
        url = self._signed_url(path, body if method == "POST" else "", params=params)
        request_headers = self._headers(headers)
        data = body.encode("utf-8") if method == "POST" else None
        http_request = request.Request(url, data=data, headers=request_headers, method=method)

        try:
            with request.urlopen(http_request, timeout=timeout or self.timeout) as response:
                raw = response.read().decode("utf-8-sig")
                status_code = getattr(response, "status", 200)
                response_headers = dict(getattr(response, "headers", {}) or {})
        except HTTPError as exc:
            raise self._map_http_error(exc) from exc
        except TimeoutError as exc:
            raise AccountingConnectionError("Merit API request timed out.") from exc
        except URLError as exc:
            raise AccountingConnectionError("Could not connect to Merit API.") from exc

        if status_code >= 400:
            raise self._map_status_error(status_code)

        return self._parse_response(raw, response_headers)

    def health(self):
        started = time.perf_counter()
        self.authenticate()
        response_time_ms = round((time.perf_counter() - started) * 1000, 3)

        return {
            "healthy": True,
            "provider": AccountingIntegration.Provider.MERIT,
            "response_time_ms": response_time_ms,
            "status_code": None,
            "mode": "local_check",
        }

    def list_dimensions(self):
        response_data = self.request(
            "POST",
            self.DIMENSIONS_LIST_ENDPOINT,
            payload={"AllValues": True},
        )
        return [self._dimension_dto_from_raw(item) for item in self._dimension_items(response_data)]

    def get_dimension(self, external_id):
        if external_id is None:
            return None
        try:
            response_data = self.request(
                "GET",
                self.DIMENSION_DETAIL_ENDPOINT,
                params={"Id": str(external_id)},
            )
        except AccountingUnexpectedResponseError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
        items = self._dimension_items(response_data)
        if not items:
            return None
        return self._dimension_dto_from_raw(items[0])

    def create_dimension(self, code, name, dimension_type="project"):
        payload = {
            "Dimensions": [
                {
                    "Name": dimension_type,
                    "Values": [
                        {
                            "Code": code,
                            "Name": name,
                        }
                    ],
                }
            ]
        }
        response_data = self.request("POST", self.DIMENSIONS_CREATE_ENDPOINT, payload=payload)
        created_items = self._dimension_items(response_data)
        if created_items:
            return self._dimension_dto_from_raw(created_items[0], default_dimension_type=dimension_type)

        return MeritDimensionDTO(
            external_id="",
            code=str(code or ""),
            name=str(name or ""),
            dimension_type=str(dimension_type or "project"),
            active=True,
            raw={},
        )

    def _signed_url(self, path, body, *, params=None):
        clean_path = path.lstrip("/")
        timestamp = self._timestamp()
        query_params = {
            **(params or {}),
            **{
                "apiId": self.api_id,
                "timestamp": timestamp,
                "signature": self._signature(timestamp, body),
            },
        }
        query = urlencode(query_params)
        return f"{urljoin(f'{self.api_base_url}/', clean_path)}?{query}"

    def _signature(self, timestamp, body):
        data = f"{self.api_id}{timestamp}{body}".encode("utf-8")
        api_secret = self.secret_provider.get_secret(self.integration)
        digest = hmac.new(api_secret.encode("ascii"), data, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("ascii")

    def _headers(self, extra_headers):
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "OperationsWorkspacePlatform/1.0",
        }
        headers.update(extra_headers or {})
        return headers

    def _json_body(self, payload):
        return json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))

    def _parse_response(self, raw, response_headers):
        if not raw:
            return None

        content_type = response_headers.get("Content-Type", response_headers.get("content-type", ""))
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            if "json" in content_type.lower():
                raise AccountingUnexpectedResponseError("Merit API returned invalid JSON.") from exc
            return raw

    def _map_status_error(self, status_code):
        if status_code in {401, 403}:
            return AccountingAuthenticationError(f"Merit API returned HTTP {status_code}.")
        if status_code == 429:
            return AccountingRateLimitError(f"Merit API returned HTTP {status_code}.")
        if status_code >= 500:
            return AccountingAPIError(f"Merit API returned HTTP {status_code}.")
        return AccountingUnexpectedResponseError(f"Merit API returned HTTP {status_code}.")

    def _map_http_error(self, exc):
        message = self._safe_http_error_message(exc)
        if exc.code in {401, 403}:
            return AccountingAuthenticationError(message)
        if exc.code == 429:
            return AccountingRateLimitError(message)
        if exc.code >= 500:
            return AccountingAPIError(message)
        return AccountingUnexpectedResponseError(message)

    def _dimension_items(self, response_data):
        if response_data is None:
            return []
        if isinstance(response_data, list):
            return self._flatten_dimension_items(response_data)
        if isinstance(response_data, dict):
            for key in ("Dimensions", "dimensions", "Items", "items", "Data", "data"):
                value = response_data.get(key)
                if isinstance(value, list):
                    return self._flatten_dimension_items(value)
            return self._flatten_dimension_items([response_data])
        return []

    def _flatten_dimension_items(self, items):
        flattened = []
        for item in items:
            if not isinstance(item, dict):
                continue

            values = item.get("Values") or item.get("values")
            if isinstance(values, list):
                parent_type = (
                    item.get("DimensionType")
                    or item.get("dimension_type")
                    or item.get("Type")
                    or item.get("type")
                    or item.get("Code")
                    or item.get("Name")
                )
                for value in values:
                    if isinstance(value, dict):
                        merged = {**value}
                        merged.setdefault("DimensionType", parent_type or "project")
                        flattened.append(merged)
                continue

            flattened.append(item)
        return flattened

    def _dimension_dto_from_raw(self, raw, default_dimension_type="project"):
        raw_copy = deepcopy(raw or {})
        external_id = self._first_value(raw_copy, "ExternalId", "external_id", "Id", "ID", "id", "ValueId", "value_id")
        code = self._first_value(raw_copy, "Code", "code", "DimensionCode", "dimension_code")
        name = self._first_value(raw_copy, "Name", "name", "Description", "description")
        dimension_type = self._first_value(
            raw_copy,
            "DimensionType",
            "dimension_type",
            "Type",
            "type",
            default=default_dimension_type,
        )
        active = self._as_bool(self._first_value(raw_copy, "Active", "active", "IsActive", "is_active", default=True))

        return MeritDimensionDTO(
            external_id=str(external_id or ""),
            code=str(code or ""),
            name=str(name or ""),
            dimension_type=str(dimension_type or default_dimension_type),
            active=active,
            raw=raw_copy,
        )

    def _first_value(self, data, *keys, default=""):
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        return default

    def _as_bool(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"false", "0", "no", "n"}
        return bool(value)

    def _safe_http_error_message(self, exc):
        raw = exc.read().decode("utf-8-sig", errors="replace") if exc.fp else ""
        if not raw:
            return f"Merit API returned HTTP {exc.code}."
        return f"Merit API returned HTTP {exc.code}: {raw}"

    def _timestamp(self):
        return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
