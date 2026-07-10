from copy import deepcopy

from django.db import transaction

from apps.accounting.models import AccountingDimension
from apps.core.services import AuditService

from .commands import (
    DimensionConflictResolutionResult,
    IgnoreDimensionConflictCommand,
    ResolveDimensionConflictCommand,
)


class AccountingDimensionConflictResolutionService:
    """Resolve cached accounting dimension conflicts through explicit decisions.

    This service only updates local AccountingDimension cache rows. It never
    calls Merit, deletes dimensions, touches projects, or resolves conflicts
    automatically.
    """

    KEEP_LOCAL = "keep_local"
    ACCEPT_INCOMING = "accept_incoming"
    MARK_INACTIVE = "mark_inactive"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"

    SUPPORTED_RESOLUTION_TYPES = {
        KEEP_LOCAL,
        ACCEPT_INCOMING,
        MARK_INACTIVE,
        MANUAL_REVIEW_REQUIRED,
    }

    @staticmethod
    def resolve(command: ResolveDimensionConflictCommand) -> DimensionConflictResolutionResult:
        if command.resolution_type not in AccountingDimensionConflictResolutionService.SUPPORTED_RESOLUTION_TYPES:
            raise ValueError(f"Unsupported dimension conflict resolution type: {command.resolution_type}")

        conflict = deepcopy(command.conflict or {})
        metadata = deepcopy(command.metadata or {})

        with transaction.atomic():
            if command.resolution_type == AccountingDimensionConflictResolutionService.KEEP_LOCAL:
                result = AccountingDimensionConflictResolutionService._keep_local(command, conflict, metadata)
            elif command.resolution_type == AccountingDimensionConflictResolutionService.ACCEPT_INCOMING:
                result = AccountingDimensionConflictResolutionService._accept_incoming(command, conflict, metadata)
            elif command.resolution_type == AccountingDimensionConflictResolutionService.MARK_INACTIVE:
                result = AccountingDimensionConflictResolutionService._mark_inactive(command, conflict, metadata)
            else:
                result = AccountingDimensionConflictResolutionService._manual_review_required(
                    command,
                    conflict,
                    metadata,
                )

            AccountingDimensionConflictResolutionService._record_audit(command, conflict, result)
            return result

    @staticmethod
    def ignore(command: IgnoreDimensionConflictCommand) -> DimensionConflictResolutionResult:
        conflict = deepcopy(command.conflict or {})
        metadata = deepcopy(command.metadata or {})
        metadata["reason"] = command.reason

        with transaction.atomic():
            dimension = AccountingDimensionConflictResolutionService._matched_dimension(
                organization=command.organization,
                conflict=conflict,
            )
            result = DimensionConflictResolutionResult(
                resolution_type="ignore",
                affected_dimension=dimension,
                resolved=True,
                message="Dimension conflict ignored by explicit user decision.",
                metadata=metadata,
            )
            AccountingDimensionConflictResolutionService._record_audit(command, conflict, result)
            return result

    @staticmethod
    def _keep_local(command, conflict, metadata):
        dimension = AccountingDimensionConflictResolutionService._matched_dimension(
            organization=command.organization,
            conflict=conflict,
        )
        return DimensionConflictResolutionResult(
            resolution_type=AccountingDimensionConflictResolutionService.KEEP_LOCAL,
            affected_dimension=dimension,
            resolved=True,
            message="Kept local accounting dimension cache unchanged.",
            metadata=metadata,
        )

    @staticmethod
    def _accept_incoming(command, conflict, metadata):
        values = AccountingDimensionConflictResolutionService._incoming_values(conflict)
        if not values["code"] or not values["name"]:
            return DimensionConflictResolutionResult(
                resolution_type=AccountingDimensionConflictResolutionService.ACCEPT_INCOMING,
                affected_dimension=None,
                resolved=False,
                message="Incoming conflict data is not sufficient to update the local cache.",
                metadata=metadata,
            )

        dimension = AccountingDimensionConflictResolutionService._matched_dimension(
            organization=command.organization,
            conflict=conflict,
        )

        if dimension is None:
            dimension = AccountingDimension.objects.create(
                organization=command.organization,
                provider=values["provider"],
                dimension_type=values["dimension_type"],
                code=values["code"],
                external_id=values["external_id"],
                name=values["name"],
                is_active=True,
                raw_data=values["raw_data"],
            )
        else:
            dimension.provider = values["provider"]
            dimension.dimension_type = values["dimension_type"]
            dimension.code = values["code"]
            dimension.external_id = values["external_id"]
            dimension.name = values["name"]
            dimension.is_active = True
            dimension.raw_data = values["raw_data"]
            dimension.save()

        return DimensionConflictResolutionResult(
            resolution_type=AccountingDimensionConflictResolutionService.ACCEPT_INCOMING,
            affected_dimension=dimension,
            resolved=True,
            message="Accepted incoming dimension data into the local cache.",
            metadata=metadata,
        )

    @staticmethod
    def _mark_inactive(command, conflict, metadata):
        dimension = AccountingDimensionConflictResolutionService._matched_dimension(
            organization=command.organization,
            conflict=conflict,
        )
        if dimension:
            dimension.is_active = False
            dimension.save(update_fields=["is_active", "updated_at"])

        return DimensionConflictResolutionResult(
            resolution_type=AccountingDimensionConflictResolutionService.MARK_INACTIVE,
            affected_dimension=dimension,
            resolved=True,
            message="Matched local accounting dimension marked inactive.",
            metadata=metadata,
        )

    @staticmethod
    def _manual_review_required(command, conflict, metadata):
        dimension = AccountingDimensionConflictResolutionService._matched_dimension(
            organization=command.organization,
            conflict=conflict,
        )
        return DimensionConflictResolutionResult(
            resolution_type=AccountingDimensionConflictResolutionService.MANUAL_REVIEW_REQUIRED,
            affected_dimension=dimension,
            resolved=False,
            message="Conflict left unresolved for manual review.",
            metadata=metadata,
        )

    @staticmethod
    def _matched_dimension(*, organization, conflict):
        queryset = AccountingDimension.objects.filter(organization=organization)
        dimension_type = conflict.get("dimension_type")
        if dimension_type:
            queryset = queryset.filter(dimension_type=dimension_type)

        for external_id in AccountingDimensionConflictResolutionService._external_id_candidates(conflict):
            dimension = queryset.filter(external_id=external_id).first()
            if dimension:
                return dimension

        for code in AccountingDimensionConflictResolutionService._code_candidates(conflict):
            dimension = queryset.filter(code=code).first()
            if dimension:
                return dimension

        return None

    @staticmethod
    def _incoming_values(conflict):
        raw_data = deepcopy(
            conflict.get("incoming_raw")
            or conflict.get("raw")
            or conflict.get("incoming")
            or {}
        )
        return {
            "provider": conflict.get("provider") or AccountingDimension.Provider.MERIT,
            "dimension_type": conflict.get("dimension_type") or AccountingDimension.DimensionType.PROJECT,
            "code": conflict.get("incoming_code") or conflict.get("code") or "",
            "external_id": conflict.get("incoming_external_id") or conflict.get("external_id"),
            "name": conflict.get("incoming_name") or conflict.get("name") or raw_data.get("Name") or raw_data.get("name") or "",
            "raw_data": raw_data,
        }

    @staticmethod
    def _external_id_candidates(conflict):
        candidates = [
            conflict.get("existing_external_id"),
            conflict.get("external_id"),
            conflict.get("incoming_external_id"),
        ]
        candidates.extend(conflict.get("external_ids") or [])
        return [value for value in candidates if value]

    @staticmethod
    def _code_candidates(conflict):
        candidates = [
            conflict.get("existing_code"),
            conflict.get("code"),
            conflict.get("incoming_code"),
        ]
        return [value for value in candidates if value]

    @staticmethod
    def _record_audit(command, conflict, result):
        AuditService.record(
            event_type="accounting_dimension_conflict_resolved",
            message=result.message,
            organization=command.organization,
            actor=command.actor,
            object_type="AccountingDimension",
            object_id=str(result.affected_dimension.id) if result.affected_dimension else "",
            metadata={
                **deepcopy(result.metadata),
                "resolution_type": result.resolution_type,
                "resolved": result.resolved,
                "conflict": conflict,
            },
        )
