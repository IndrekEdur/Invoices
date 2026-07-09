from .exceptions import SecretMissingError


class SecretProvider:
    """Minimal integration secret access abstraction.

    TODO: Replace the placeholder field lookup with encrypted storage or a
    deployment-grade secret backend before real credentials are used.
    """

    @staticmethod
    def get_secret(integration):
        secret = (integration.encrypted_secret_placeholder or "").strip()
        if not secret:
            raise SecretMissingError("Integration secret is not configured.")
        return secret

    @staticmethod
    def mask_secret(value):
        secret = value or ""
        if not secret:
            return ""
        if len(secret) <= 4:
            return "****"
        return f"{secret[:2]}****{secret[-2:]}"
