import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import time
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from apps.accounting.models import AccountingIntegration

from .base import AccountingConnector
from .exceptions import (
    AuthenticationError,
    ConnectionError,
    RateLimitError,
    UnexpectedResponseError,
)


DEFAULT_MERIT_BASE_URL = "https://aktiva.merit.ee"
DEFAULT_TIMEOUT_SECONDS = 20


class MeritAPIClient(AccountingConnector):
    """Low-level Merit Aktiva API client.

    This class is the integration boundary for direct Merit HTTP calls.
    Business services should use this connector instead of urllib/requests.
    """

    health_endpoint = "/api/v1/gettaxes"

    def __init__(self, integration: AccountingIntegration, *, timeout=DEFAULT_TIMEOUT_SECONDS):
        if integration.provider != AccountingIntegration.Provider.MERIT:
            raise ValueError("MeritAPIClient requires an AccountingIntegration with provider='merit'.")

        self.integration = integration
        self.api_base_url = (integration.api_base_url or DEFAULT_MERIT_BASE_URL).rstrip("/")
        self.api_id = integration.api_id.strip()
        # TODO: Replace encrypted_secret_placeholder with real encrypted secret management.
        self.api_secret = integration.encrypted_secret_placeholder.strip()
        self.timeout = timeout

    def authenticate(self):
        if not self.api_id or not self.api_secret:
            raise AuthenticationError("Merit API credentials are not configured.")
        return {"api_id": self.api_id}

    def request(self, method, path, *, payload=None, headers=None, timeout=None):
        self.authenticate()
        method = method.upper()
        if method not in {"GET", "POST"}:
            raise ValueError("MeritAPIClient supports only GET and POST requests.")

        body = self._json_body(payload if payload is not None else {})
        url = self._signed_url(path, body if method == "POST" else "")
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
            raise ConnectionError("Merit API request timed out.") from exc
        except URLError as exc:
            raise ConnectionError("Could not connect to Merit API.") from exc

        if status_code >= 400:
            raise UnexpectedResponseError(f"Merit API returned HTTP {status_code}.")

        return self._parse_response(raw, response_headers)

    def health(self):
        started = time.perf_counter()
        response_data = self.request("POST", self.health_endpoint, payload={})
        response_time = round(time.perf_counter() - started, 3)

        return {
            "healthy": True,
            "response_time": response_time,
            "provider": AccountingIntegration.Provider.MERIT,
            "version": self._extract_version(response_data),
        }

    def _signed_url(self, path, body):
        clean_path = path if path.startswith("/") else f"/{path}"
        timestamp = self._timestamp()
        params = urlencode(
            {
                "apiId": self.api_id,
                "timestamp": timestamp,
                "signature": self._signature(timestamp, body),
            }
        )
        return f"{self.api_base_url}{clean_path}?{params}"

    def _signature(self, timestamp, body):
        data = f"{self.api_id}{timestamp}{body}".encode("utf-8")
        digest = hmac.new(self.api_secret.encode("ascii"), data, hashlib.sha256).digest()
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
                raise UnexpectedResponseError("Merit API returned invalid JSON.") from exc
            return raw

    def _map_http_error(self, exc):
        message = self._safe_http_error_message(exc)
        if exc.code in {401, 403}:
            return AuthenticationError(message)
        if exc.code == 429:
            return RateLimitError(message)
        if exc.code >= 500:
            return ConnectionError(message)
        return UnexpectedResponseError(message)

    def _safe_http_error_message(self, exc):
        raw = exc.read().decode("utf-8-sig", errors="replace") if exc.fp else ""
        if not raw:
            return f"Merit API returned HTTP {exc.code}."
        return f"Merit API returned HTTP {exc.code}: {raw}"

    def _extract_version(self, response_data):
        if isinstance(response_data, dict):
            return response_data.get("version") or response_data.get("Version")
        return None

    def _timestamp(self):
        return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
