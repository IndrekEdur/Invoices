from abc import ABC, abstractmethod


class AccountingConnector(ABC):
    """Base interface for provider-specific accounting API connectors."""

    @abstractmethod
    def authenticate(self):
        """Prepare authentication data for future provider-specific requests."""

    @abstractmethod
    def request(self, method, path, *, payload=None, headers=None, timeout=None):
        """Perform a provider API request and return parsed response data."""

    @abstractmethod
    def health(self):
        """Return a sanitized provider connectivity health result."""
