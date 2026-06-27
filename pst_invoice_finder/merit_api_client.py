from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib import request
from urllib.parse import urlencode


BASE_URL = "https://aktiva.merit.ee"


class MeritApiError(RuntimeError):
    pass


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def signature(api_id: str, api_key: str, timestamp: str, body: str) -> str:
    data = (api_id + timestamp + body).encode("utf-8")
    digest = hmac.new(api_key.encode("ascii"), data, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


class MeritClient:
    def __init__(self, api_id: str, api_key: str, base_url: str = BASE_URL):
        self.api_id = api_id.strip()
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")

    def post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not self.api_id or not self.api_key:
            raise MeritApiError("Meriti API ID või võti puudub.")
        body = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
        ts = timestamp_utc()
        params = urlencode(
            {
                "apiId": self.api_id,
                "timestamp": ts,
                "signature": signature(self.api_id, self.api_key, ts, body),
            }
        )
        url = f"{self.base_url}{path}?{params}"
        req = request.Request(
            url,
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=20) as response:
                raw = response.read().decode("utf-8-sig")
        except HTTPError as exc:
            raw_error = exc.read().decode("utf-8-sig", errors="replace")
            message = f"HTTP {exc.code} {exc.reason}"
            if raw_error:
                message += f": {raw_error}"
            raise MeritApiError(message) from exc
        except URLError as exc:
            raise MeritApiError(f"Connection error: {exc}") from exc
        except Exception as exc:
            raise MeritApiError(str(exc)) from exc
        try:
            return json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return raw

    def get_taxes(self) -> Any:
        return self.post("/api/v1/gettaxes", {})

    def get_banks(self) -> Any:
        return self.post("/api/v1/getbanks", {})

    def get_payment_types(self, type_id: int = 1) -> Any:
        return self.post("/api/v2/getpaymenttypes", {"Type": int(type_id)})

    def get_purchase_invoices(self, period_start: str, period_end: str, unpaid: bool = False) -> Any:
        payload = {
            "PeriodStart": period_start,
            "PeriodEnd": period_end,
            "UnPaid": bool(unpaid),
            "DateType": 0,
        }
        try:
            return self.post("/api/v2/getpurchorders", payload)
        except MeritApiError:
            payload["Periodstart"] = payload.pop("PeriodStart")
            return self.post("/api/v2/getpurchorders", payload)

    def get_dimensions(self, all_values: bool = True) -> Any:
        return self.post("/api/v2/getdimensions", {"AllValues": bool(all_values)})

    def get_vendors(self, payload: dict[str, Any] | None = None) -> Any:
        return self.post("/api/v1/getvendors", payload or {})

    def send_dimension_values(self, dimensions: list[dict[str, Any]]) -> Any:
        return self.post("/api/v2/senddimvalues", {"Dimensions": dimensions})

    def send_purchase_invoice(self, payload: dict[str, Any]) -> Any:
        return self.post("/api/v2/sendpurchinvoice", payload)

    def send_purchase_payment(self, payload: dict[str, Any]) -> Any:
        return self.post("/api/v1/sendPaymentV", payload)
