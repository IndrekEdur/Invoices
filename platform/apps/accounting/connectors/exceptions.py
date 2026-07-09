class AccountingAPIError(RuntimeError):
    """Base exception for accounting connector failures."""


class AuthenticationError(AccountingAPIError):
    """Raised when an accounting API rejects credentials or signatures."""


class ConnectionError(AccountingAPIError):
    """Raised when the connector cannot reach the accounting API."""


class RateLimitError(AccountingAPIError):
    """Raised when an accounting API reports request throttling."""


class UnexpectedResponseError(AccountingAPIError):
    """Raised when an accounting API returns an invalid or unsupported response."""
