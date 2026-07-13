from copy import deepcopy

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.services import AuditService

from ..models import (
    ManagementAllocationRule,
    ManagementAllocationVersion,
    ManagementCostPool,
    VersionStatus,
)


class ManagementCostPoolService:
    """Create and validate management cost pool setup records."""

    @staticmethod
    @transaction.atomic
    def create_pool(command):
        metadata = deepcopy(command.metadata or {})
        pool = ManagementCostPool.objects.create(
            organization=command.organization,
            name=command.name,
            description=command.description,
            default_strategy=command.default_strategy,
            display_order=command.display_order,
            is_active=command.is_active,
        )
        AuditService.record(
            event_type="management_cost_pool_created",
            message=f"Management cost pool created: {pool.name}",
            organization=pool.organization,
            actor=command.actor,
            object_type="ManagementCostPool",
            object_id=str(pool.id),
            metadata=metadata,
        )
        return pool

    @staticmethod
    @transaction.atomic
    def create_rule(command):
        metadata = deepcopy(command.metadata or {})
        configuration = deepcopy(command.configuration or {})
        rule = ManagementAllocationRule.objects.create(
            pool=command.pool,
            strategy=command.strategy,
            is_active=command.is_active,
            configuration=configuration,
        )
        AuditService.record(
            event_type="management_allocation_rule_created",
            message=f"Management allocation rule created for {rule.pool.name}",
            organization=rule.pool.organization,
            actor=command.actor,
            object_type="ManagementAllocationRule",
            object_id=str(rule.id),
            metadata=metadata,
        )
        return rule


class ManagementAllocationVersionService:
    """Manage allocation version lifecycle without calculating allocations."""

    @staticmethod
    @transaction.atomic
    def create_version(command):
        metadata = deepcopy(command.metadata or {})
        version_number = command.version_number
        if version_number is None:
            latest = (
                ManagementAllocationVersion.objects.filter(period=command.period, pool=command.pool)
                .aggregate(max_version=Max("version_number"))
                .get("max_version")
                or 0
            )
            version_number = latest + 1

        version = ManagementAllocationVersion.objects.create(
            period=command.period,
            pool=command.pool,
            version_number=version_number,
            created_by=command.created_by,
            reason=command.reason,
        )
        AuditService.record(
            event_type="management_allocation_version_created",
            message=f"Management allocation version created: {version}",
            organization=version.period.organization,
            actor=command.created_by,
            object_type="ManagementAllocationVersion",
            object_id=str(version.id),
            metadata=metadata,
        )
        return version

    @staticmethod
    @transaction.atomic
    def approve(command):
        metadata = deepcopy(command.metadata or {})
        version = (
            ManagementAllocationVersion.objects.select_for_update()
            .select_related("period", "pool")
            .get(pk=command.version.pk)
        )
        if version.status == VersionStatus.SUPERSEDED:
            raise ValueError("Superseded management allocation versions cannot be approved.")
        if not version.pool.is_active:
            raise ValueError("Inactive management cost pools cannot be approved.")

        previous_versions = (
            ManagementAllocationVersion.objects.select_for_update()
            .filter(period=version.period, pool=version.pool, status=VersionStatus.APPROVED)
            .exclude(pk=version.pk)
        )
        for previous in previous_versions:
            previous.status = VersionStatus.SUPERSEDED
            previous.save(update_fields=["status"])
            AuditService.record(
                event_type="management_allocation_version_superseded",
                message=f"Management allocation version superseded: {previous}",
                organization=previous.period.organization,
                actor=command.actor,
                object_type="ManagementAllocationVersion",
                object_id=str(previous.id),
                metadata={
                    **metadata,
                    "superseded_by_version_id": version.id,
                },
            )

        version.status = VersionStatus.APPROVED
        version.approved_by = command.actor
        version.approved_at = timezone.now()
        if command.reason:
            version.reason = command.reason
        version.save(update_fields=["status", "approved_by", "approved_at", "reason"])
        AuditService.record(
            event_type="management_allocation_version_approved",
            message=f"Management allocation version approved: {version}",
            organization=version.period.organization,
            actor=command.actor,
            object_type="ManagementAllocationVersion",
            object_id=str(version.id),
            metadata=metadata,
        )
        return version
