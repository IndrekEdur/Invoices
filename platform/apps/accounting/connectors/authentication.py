import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac

from apps.accounting.secrets import SecretMissingError, SecretProvider

from .exceptions import AccountingAuthenticationError


@dataclass(frozen=True)
class MeritAuthentication:
    api_id: str
    timestamp: str
    signature: str
    headers: dict


class MeritAuthenticationService:
    """Creates Merit API authentication values according to Merit API rules.

    Merit authentication uses query parameters:
    apiId, timestamp and signature. The signature is HMAC-SHA256 over
    apiId + timestamp + HTTP body, signed with the API key.
    """

    def __init__(self, *, secret_provider=None):
        self.secret_provider = secret_provider or SecretProvider()

    def create_authentication(self, integration, *, body=""):
        api_id = (integration.api_id or "").strip()
        if not api_id:
            raise AccountingAuthenticationError("Merit API credentials are not configured.")

        try:
            api_secret = self.secret_provider.get_secret(integration)
        except SecretMissingError as exc:
            raise AccountingAuthenticationError("Merit API credentials are not configured.") from exc

        timestamp = self._timestamp()
        signature = self._signature(api_id=api_id, api_secret=api_secret, timestamp=timestamp, body=body)
        return MeritAuthentication(
            api_id=api_id,
            timestamp=timestamp,
            signature=signature,
            headers={},
        )

    def _timestamp(self):
        return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    def _signature(self, *, api_id, api_secret, timestamp, body):
        data = f"{api_id}{timestamp}{body}".encode("utf-8")
        digest = hmac.new(api_secret.encode("ascii"), data, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("ascii")
