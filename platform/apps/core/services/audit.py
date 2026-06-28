from ..models import AuditEvent


class AuditService:
    """Central append-only entry point for creating audit records."""

    @staticmethod
    def record(
        *,
        event_type,
        message="",
        organization=None,
        actor=None,
        object_type="",
        object_id="",
        metadata=None,
        ip_address=None,
        user_agent=None,
    ):
        """Create and return an AuditEvent.

        Audit events are append-only compliance records. Callers should create a
        new audit event for every important action instead of updating an
        existing event.
        """

        event_metadata = dict(metadata or {})

        return AuditEvent.objects.create(
            event_type=event_type,
            message=message,
            organization=organization,
            actor=actor,
            object_type=object_type,
            object_id=object_id,
            metadata=event_metadata,
            ip_address=ip_address,
            user_agent=user_agent,
        )
