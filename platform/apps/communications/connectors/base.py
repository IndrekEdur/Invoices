class BaseEmailConnector:
    """Base interface for provider-specific e-mail connectors."""

    def connect(self):
        raise NotImplementedError

    def fetch_messages(self, limit=50):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError
