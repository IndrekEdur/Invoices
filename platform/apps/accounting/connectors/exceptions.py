class AccountingAPIError(RuntimeError):
    """Base exception for accounting connector failures."""


class AccountingAuthenticationError(AccountingAPIError):
    """Raised when an accounting API rejects credentials or signatures."""


class AccountingConnectionError(AccountingAPIError):
    """Raised when the connector cannot reach the accounting API."""


class AccountingRateLimitError(AccountingAPIError):
    """Raised when an accounting API reports request throttling."""


class AccountingUnexpectedResponseError(AccountingAPIError):
    """Raised when an accounting API returns an invalid or unsupported response."""


AuthenticationError = AccountingAuthenticationError
ConnectionError = AccountingConnectionError
RateLimitError = AccountingRateLimitError
UnexpectedResponseError = AccountingUnexpectedResponseError
