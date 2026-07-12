import json
import time
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin

from apps.accounting.dto import (
    MeritDimensionDTO,
    MeritDimensionValueDTO,
    MeritGLBatchDTO,
    MeritGLCostAllocationDTO,
    MeritGLDateType,
    MeritGLEntryDTO,
)
from apps.accounting.models import AccountingIntegration
from apps.accounting.secrets import SecretProvider

from .authentication import MeritAuthenticationService
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
    DIMENSION_VALUES_CREATE_ENDPOINT = "/api/v2/senddimvalues"
    GL_BATCHES_FULL_PATH = "/GetGLBatchesFull"

    def __init__(
        self,
        integration: AccountingIntegration,
        *,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        secret_provider=None,
        authentication_service=None,
    ):
        if integration.provider != AccountingIntegration.Provider.MERIT:
            raise ValueError("MeritAPIClient requires an AccountingIntegration with provider='merit'.")

        self.integration = integration
        self.api_base_url = (integration.api_base_url or DEFAULT_MERIT_BASE_URL).rstrip("/")
        self.api_id = integration.api_id.strip()
        self.secret_provider = secret_provider or SecretProvider()
        self.authentication_service = authentication_service or MeritAuthenticationService(
            secret_provider=self.secret_provider
        )
        self.timeout = timeout

    def authenticate(self):
        self.authentication_service.create_authentication(self.integration)
        return True

    def request(self, method, path, *, payload=None, params=None, headers=None, timeout=None):
        method = method.upper()
        if method not in {"GET", "POST"}:
            raise ValueError("MeritAPIClient supports only GET and POST requests.")

        body = self._json_body(payload if payload is not None else {})
        authentication = self.authentication_service.create_authentication(
            self.integration,
            body=body if method == "POST" else "",
        )
        url = self._authenticated_url(path, authentication, params=params)
        request_headers = self._headers(headers, authentication_headers=authentication.headers)
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

    def create_dimension_value(
        self,
        code,
        name,
        dimension_type="project",
        dimension_id=None,
        external_id=None,
        end_date=None,
    ):
        if dimension_id is None:
            raise ValueError("Merit dimension_id is required to create or update a dimension value.")

        dimension_value = {
            "DimId": dimension_id,
            "DimValueCode": code,
            "DimValueName": name,
        }
        if external_id:
            dimension_value["DimValueId"] = external_id
        if end_date:
            dimension_value["EndDate"] = end_date

        response_data = self.request(
            "POST",
            self.DIMENSION_VALUES_CREATE_ENDPOINT,
            payload={"Dimensions": [dimension_value]},
        )
        created_items = self._dimension_items(response_data)
        if created_items:
            return self._dimension_value_dto_from_raw(created_items[0], default_dimension_type=dimension_type)

        return MeritDimensionValueDTO(
            external_id=str(external_id or ""),
            code=str(code or ""),
            name=str(name or ""),
            dimension_type=str(dimension_type or "project"),
            active=True,
            raw={},
        )

    def get_gl_batches_full(
        self,
        period_start,
        period_end,
        *,
        with_lines=True,
        with_cost_allocations=True,
        date_type=MeritGLDateType.DOCUMENT_DATE,
    ):
        start_date = self._coerce_date(period_start, field_name="period_start")
        end_date = self._coerce_date(period_end, field_name="period_end")
        if end_date < start_date:
            raise ValueError("period_end cannot be before period_start.")
        if (end_date - start_date).days > 30:
            raise ValueError("Merit GL full details period cannot exceed 31 calendar days.")
        if date_type not in MeritGLDateType.MERIT_VALUES:
            raise ValueError(f"Unsupported Merit GL date_type: {date_type}")

        response_data = self.request(
            "POST",
            self.GL_BATCHES_FULL_PATH,
            payload={
                "PeriodStart": self._format_merit_period_start(start_date),
                "PeriodEnd": self._format_merit_period_end(end_date),
                "WithLines": 1 if with_lines else 0,
                "WithCostAlloc": 1 if with_cost_allocations else 0,
                "DateType": MeritGLDateType.MERIT_VALUES[date_type],
            },
        )
        return self._gl_batches_from_response(response_data)

    def _authenticated_url(self, path, authentication, *, params=None):
        clean_path = path.lstrip("/")
        query_params = {
            **(params or {}),
            **{
                "apiId": authentication.api_id,
                "timestamp": authentication.timestamp,
                "signature": authentication.signature,
            },
        }
        query = urlencode(query_params)
        return f"{urljoin(f'{self.api_base_url}/', clean_path)}?{query}"

    def _headers(self, extra_headers, *, authentication_headers=None):
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "OperationsWorkspacePlatform/1.0",
        }
        headers.update(authentication_headers or {})
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

    def _dimension_value_dto_from_raw(self, raw, default_dimension_type="project"):
        raw_copy = deepcopy(raw or {})
        external_id = self._first_value(
            raw_copy,
            "DimValueId",
            "dim_value_id",
            "ExternalId",
            "external_id",
            "Id",
            "ID",
            "id",
            "ValueId",
            "value_id",
        )
        code = self._first_value(raw_copy, "DimValueCode", "dim_value_code", "Code", "code")
        name = self._first_value(raw_copy, "DimValueName", "dim_value_name", "Name", "name")
        dimension_type = self._first_value(
            raw_copy,
            "DimensionType",
            "dimension_type",
            "Type",
            "type",
            default=default_dimension_type,
        )
        active = self._as_bool(self._first_value(raw_copy, "Active", "active", "IsActive", "is_active", default=True))

        return MeritDimensionValueDTO(
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

    def _gl_batches_from_response(self, response_data):
        if response_data is None:
            return []
        if not isinstance(response_data, list):
            raise AccountingUnexpectedResponseError("Merit GL full details response must be a list.")
        return [self._gl_batch_dto_from_raw(item) for item in response_data]

    def _gl_batch_dto_from_raw(self, raw):
        if not isinstance(raw, dict):
            raise AccountingUnexpectedResponseError("Merit GL batch item must be an object.")

        raw_copy = deepcopy(raw)
        external_id = self._first_value(raw_copy, "GLBId", "glb_id", "Id", "id")
        if external_id in {None, ""}:
            raise AccountingUnexpectedResponseError("Merit GL batch is missing stable GLBId identity.")

        entries = self._gl_entries(raw_copy.get("Entries"), default_batch_id=str(external_id))
        return MeritGLBatchDTO(
            external_id=str(external_id),
            batch_code=str(self._first_value(raw_copy, "BatchCode", "batch_code")),
            number=str(self._first_value(raw_copy, "No", "Number", "number")),
            source_document_id=str(self._first_value(raw_copy, "DocId", "SourceDocumentId", "source_document_id")),
            document=str(self._first_value(raw_copy, "Document", "document")),
            batch_date=self._parse_merit_date(self._first_value(raw_copy, "BatchDate", "batch_date", default=None)),
            currency_code=str(self._first_value(raw_copy, "CurrencyCode", "currency_code")),
            currency_rate=self._decimal_or_none(self._first_value(raw_copy, "CurrencyRate", "currency_rate", default=None)),
            total_amount=self._decimal_or_none(self._first_value(raw_copy, "TotalAmount", "total_amount", default=None)),
            price_includes_vat=self._bool_or_none(self._first_value(raw_copy, "PriceInclVat", "price_incl_vat", default=None)),
            changed_at=self._parse_merit_date(self._first_value(raw_copy, "ChangedDate", "changed_date", default=None)),
            entries=entries,
            raw=raw_copy,
        )

    def _gl_entries(self, entries, *, default_batch_id):
        if entries is None or entries == "":
            return ()
        if not isinstance(entries, list):
            raise AccountingUnexpectedResponseError("Merit GL batch Entries must be a list when present.")
        return tuple(self._gl_entry_dto_from_raw(entry, default_batch_id=default_batch_id) for entry in entries)

    def _gl_entry_dto_from_raw(self, raw, *, default_batch_id):
        if not isinstance(raw, dict):
            raise AccountingUnexpectedResponseError("Merit GL entry must be an object.")

        raw_copy = deepcopy(raw)
        batch_id = str(self._first_value(raw_copy, "BatchId", "batch_id", default=default_batch_id))
        entry_id = str(self._first_value(raw_copy, "EntryId", "entry_id"))
        allocations = self._gl_cost_allocations(raw_copy.get("CostAllocLines"), batch_id=batch_id, entry_id=entry_id)
        return MeritGLEntryDTO(
            account_code=str(self._first_value(raw_copy, "AccountCode", "account_code")),
            account_name=str(self._first_value(raw_copy, "AccontName", "AccountName", "account_name")),
            memo=str(self._first_value(raw_copy, "Memo", "memo")),
            department_code=str(self._first_value(raw_copy, "DepartmentCode", "department_code")),
            debit_amount=self._decimal_or_none(self._first_value(raw_copy, "DebitAmount", "debit_amount", default=None)),
            debit_currency=str(self._first_value(raw_copy, "DebitCurrency", "debit_currency")),
            credit_amount=self._decimal_or_none(self._first_value(raw_copy, "CreditAmount", "credit_amount", default=None)),
            credit_currency=str(self._first_value(raw_copy, "CreditCurrency", "credit_currency")),
            type_id=str(self._first_value(raw_copy, "TypeId", "type_id")),
            batch_id=batch_id,
            entry_id=entry_id,
            tax_id=str(self._first_value(raw_copy, "TaxId", "tax_id")),
            tax_percent=self._decimal_or_none(self._first_value(raw_copy, "TaxPct", "tax_percent", default=None)),
            cost_allocations=allocations,
            raw=raw_copy,
        )

    def _gl_cost_allocations(self, allocations, *, batch_id, entry_id):
        if allocations is None or allocations == "":
            return ()
        if not isinstance(allocations, list):
            raise AccountingUnexpectedResponseError("Merit GL CostAllocLines must be a list when present.")
        return tuple(
            self._gl_cost_allocation_dto_from_raw(allocation, default_batch_id=batch_id, default_entry_id=entry_id)
            for allocation in allocations
        )

    def _gl_cost_allocation_dto_from_raw(self, raw, *, default_batch_id, default_entry_id):
        if not isinstance(raw, dict):
            raise AccountingUnexpectedResponseError("Merit GL cost allocation must be an object.")

        raw_copy = deepcopy(raw)
        return MeritGLCostAllocationDTO(
            source_type=str(self._first_value(raw_copy, "SourceType", "source_type")),
            code=str(self._first_value(raw_copy, "Code", "code")),
            name=str(self._first_value(raw_copy, "Name", "name")),
            multiplier=self._decimal_or_none(self._first_value(raw_copy, "Mult", "multiplier", default=None)),
            amount=self._decimal_or_none(self._first_value(raw_copy, "Amount", "amount", default=None)),
            batch_id=str(self._first_value(raw_copy, "BatchId", "batch_id", default=default_batch_id)),
            entry_id=str(self._first_value(raw_copy, "EntryId", "entry_id", default=default_entry_id)),
            raw=raw_copy,
        )

    def _coerce_date(self, value, *, field_name):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value.strip()[:10])
            except ValueError as exc:
                raise ValueError(f"{field_name} must be a date or ISO date string.") from exc
        raise ValueError(f"{field_name} must be a date or ISO date string.")

    def _format_merit_date(self, value):
        return value.isoformat()

    def _format_merit_period_start(self, value):
        return f"{self._format_merit_date(value)}T00:00:00"

    def _format_merit_period_end(self, value):
        return f"{self._format_merit_date(value)}T23:59:59"

    def _decimal_or_none(self, value):
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise AccountingUnexpectedResponseError(f"Merit GL numeric value is invalid: {value}") from exc

    def _parse_merit_date(self, value):
        if value is None or value == "":
            return None
        if isinstance(value, (datetime, date)):
            return value

        text = str(value).strip()
        if text.startswith("/Date("):
            digits = "".join(character for character in text if character.isdigit() or character == "-")
            if digits:
                try:
                    return datetime.fromtimestamp(int(digits) / 1000, tz=timezone.utc)
                except (OSError, ValueError, OverflowError):
                    return None

        try:
            if "T" in text:
                return datetime.fromisoformat(text.replace("Z", "+00:00"))
            return date.fromisoformat(text[:10])
        except ValueError:
            return None

    def _bool_or_none(self, value):
        if value is None:
            return None
        return self._as_bool(value)

    def _safe_http_error_message(self, exc):
        raw = exc.read().decode("utf-8-sig", errors="replace") if exc.fp else ""
        if not raw:
            return f"Merit API returned HTTP {exc.code}."
        return f"Merit API returned HTTP {exc.code}: {raw}"
