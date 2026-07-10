from copy import deepcopy

from django.db import transaction
from django.utils import timezone

from apps.accounting.connectors import MeritAPIClient
from apps.accounting.models import AccountingDimension
from apps.core.services import AuditService

from .commands import SyncAccountingDimensionsCommand, SyncAccountingDimensionsResult


class AccountingDimensionSyncService:
    """Synchronize accounting dimensions from provider DTOs into local cache.

    API calls stay inside the connector. This service owns persistence,
    conflict detection and audit records for the local dimension cache.
    """

    @staticmethod
    def sync(command: SyncAccountingDimensionsCommand) -> SyncAccountingDimensionsResult:
        metadata = deepcopy(command.metadata or {})
        integration = command.integration
        organization = integration.organization

        with transaction.atomic():
            AuditService.record(
                event_type="accounting_dimension_sync_started",
                message=f"Started accounting dimension sync for {integration.display_name}.",
                organization=organization,
                actor=command.actor,
                object_type="AccountingIntegration",
                object_id=str(integration.id),
                metadata=metadata,
            )

            dtos = MeritAPIClient(integration).list_dimensions()
            conflicts = AccountingDimensionSyncService._detect_conflicts(integration, dtos)
            synced_at = timezone.now()
            created_count = 0
            updated_count = 0
            unchanged_count = 0
            synced_dimensions = []
            conflict_keys = AccountingDimensionSyncService._conflict_keys(conflicts)

            for dto in dtos:
                if AccountingDimensionSyncService._dto_key(dto) in conflict_keys:
                    continue

                dimension, status = AccountingDimensionSyncService._sync_one_dimension(
                    integration=integration,
                    dto=dto,
                    synced_at=synced_at,
                )
                synced_dimensions.append(dimension)
                if status == "created":
                    created_count += 1
                elif status == "unchanged":
                    unchanged_count += 1
                else:
                    updated_count += 1

            archived_count = AccountingDimensionSyncService._archive_missing_dimensions(
                integration=integration,
                dtos=dtos,
                synced_at=synced_at,
            )

            result = SyncAccountingDimensionsResult(
                integration=integration,
                created_count=created_count,
                updated_count=updated_count,
                unchanged_count=unchanged_count,
                archived_count=archived_count,
                conflict_count=len(conflicts),
                dimensions=synced_dimensions,
                conflicts=conflicts,
                metadata=metadata,
            )

            AuditService.record(
                event_type="accounting_dimension_sync_completed",
                message=f"Completed accounting dimension sync for {integration.display_name}.",
                organization=organization,
                actor=command.actor,
                object_type="AccountingIntegration",
                object_id=str(integration.id),
                metadata={
                    **metadata,
                    "created_count": created_count,
                    "updated_count": updated_count,
                    "unchanged_count": unchanged_count,
                    "archived_count": archived_count,
                    "conflict_count": len(conflicts),
                    "conflicts": deepcopy(conflicts),
                },
            )

            return result

    @staticmethod
    def _sync_one_dimension(*, integration, dto, synced_at):
        lookup = {
            "organization": integration.organization,
            "provider": integration.provider,
            "dimension_type": dto.dimension_type,
        }
        dimension = None
        if dto.external_id:
            dimension = AccountingDimension.objects.filter(
                **lookup,
                integration=integration,
                external_id=dto.external_id,
            ).first()
        if dimension is None and dto.code:
            dimension = AccountingDimension.objects.filter(**lookup, code=dto.code).first()

        values = {
            "organization": integration.organization,
            "integration": integration,
            "provider": integration.provider,
            "external_id": dto.external_id or None,
            "code": dto.code,
            "name": dto.name,
            "dimension_type": dto.dimension_type,
            "is_active": dto.active,
            "raw_data": deepcopy(dto.raw or {}),
            "last_synced_at": synced_at,
        }

        if dimension is None:
            return AccountingDimension.objects.create(**values), "created"

        status = "unchanged" if AccountingDimensionSyncService._dimension_matches_values(dimension, values) else "updated"

        for field, value in values.items():
            setattr(dimension, field, value)
        dimension.save()
        return dimension, status

    @staticmethod
    def _dimension_matches_values(dimension, values) -> bool:
        return (
            dimension.integration == values["integration"]
            and dimension.external_id == values["external_id"]
            and dimension.code == values["code"]
            and dimension.name == values["name"]
            and dimension.dimension_type == values["dimension_type"]
            and dimension.is_active == values["is_active"]
            and dimension.raw_data == values["raw_data"]
        )

    @staticmethod
    def _archive_missing_dimensions(*, integration, dtos, synced_at):
        incoming_external_ids = {dto.external_id for dto in dtos if dto.external_id}
        incoming_keys = {(dto.dimension_type, dto.code) for dto in dtos if dto.code}
        archived_count = 0
        queryset = AccountingDimension.objects.filter(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            last_synced_at__isnull=False,
            is_active=True,
        )

        for dimension in queryset:
            if dimension.external_id:
                is_missing = dimension.external_id not in incoming_external_ids
            else:
                is_missing = (dimension.dimension_type, dimension.code) not in incoming_keys
            if not is_missing:
                continue

            dimension.is_active = False
            dimension.last_synced_at = synced_at
            dimension.save(update_fields=["is_active", "last_synced_at", "updated_at"])
            archived_count += 1
        return archived_count

    @staticmethod
    def _detect_conflicts(integration, dtos):
        conflicts = []
        seen_codes = {}

        for dto in dtos:
            code_key = (dto.dimension_type, dto.code)
            if dto.code and code_key in seen_codes and seen_codes[code_key] != dto.external_id:
                conflicts.append(
                    {
                        "type": "duplicate_incoming_code",
                        "code": dto.code,
                        "dimension_type": dto.dimension_type,
                        "external_ids": [seen_codes[code_key], dto.external_id],
                    }
                )
            elif dto.code:
                seen_codes[code_key] = dto.external_id

            if dto.code:
                existing_by_code = AccountingDimension.objects.filter(
                    organization=integration.organization,
                    provider=integration.provider,
                    dimension_type=dto.dimension_type,
                    code=dto.code,
                ).exclude(external_id__in=[dto.external_id or None]).first()
                if existing_by_code:
                    conflicts.append(
                        {
                            "type": "same_code_different_external_id",
                            "code": dto.code,
                            "dimension_type": dto.dimension_type,
                            "existing_external_id": existing_by_code.external_id,
                            "incoming_external_id": dto.external_id,
                        }
                    )

            if dto.external_id:
                existing_by_external_id = AccountingDimension.objects.filter(
                    organization=integration.organization,
                    integration=integration,
                    external_id=dto.external_id,
                ).exclude(code=dto.code).first()
                if existing_by_external_id:
                    conflicts.append(
                        {
                            "type": "same_external_id_different_code",
                            "external_id": dto.external_id,
                            "existing_code": existing_by_external_id.code,
                            "incoming_code": dto.code,
                            "dimension_type": dto.dimension_type,
                        }
                    )

        return conflicts

    @staticmethod
    def _conflict_keys(conflicts):
        keys = set()
        for conflict in conflicts:
            dimension_type = conflict.get("dimension_type")
            code = conflict.get("code")
            if conflict["type"] == "duplicate_incoming_code":
                for external_id in conflict.get("external_ids", []):
                    keys.add((dimension_type, code, external_id))
            elif conflict["type"] == "same_code_different_external_id":
                keys.add((dimension_type, code, conflict.get("incoming_external_id")))
            elif conflict["type"] == "same_external_id_different_code":
                keys.add((dimension_type, conflict.get("incoming_code"), conflict.get("external_id")))
        return keys

    @staticmethod
    def _dto_key(dto):
        return (dto.dimension_type, dto.code, dto.external_id)
