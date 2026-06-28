class BaseService:
    """Minimal base class for domain services.

    Future service infrastructure may add shared logging, database transactions,
    event emission, policy checks, and audit hooks here. For now this class only
    carries optional organization and actor context so services have a consistent
    shape without introducing a complex framework too early.
    """

    def __init__(self, *, organization=None, actor=None):
        self.organization = organization
        self.actor = actor
