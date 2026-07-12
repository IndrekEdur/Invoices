import hashlib
import json
from copy import deepcopy
from datetime import date, datetime, time
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounting.models import AccountingDimension, AccountingGLAllocation, AccountingGLBatch, AccountingGLEntry
from apps.projects.models import Project

from .commands import GLCacheUpsertResult, UpsertGLAllocationCommand, UpsertGLBatchCommand, UpsertGLEntryCommand


class GeneralLedgerCacheService:
    """Persist Merit GL DTOs into normalized local read-model tables.

    This service performs no API calls and no aggregation. Source disappearance
    is intentionally not treated as deletion; future sync tasks may mark stale
    records explicitly after period resync rules exist.
    """

    @staticmethod
    def upsert_batch(command: UpsertGLBatchCommand) -> GLCacheUpsertResult:
        metadata = deepcopy(command.metadata or {})
        integration = command.integration
        dto = command.dto
        if not dto.external_id:
            raise ValueError("GL batch external_id is required.")

        with transaction.atomic():
            now = timezone.now()
            values = GeneralLedgerCacheService._batch_values(integration, dto, synced_at=now)
            batch = AccountingGLBatch.objects.filter(integration=integration, external_id=dto.external_id).first()

            if batch is None:
                batch = AccountingGLBatch.objects.create(**values)
                return GLCacheUpsertResult(batch, True, False, False, metadata)

            GeneralLedgerCacheService._validate_integration_organization(integration, batch.organization)
            changed = GeneralLedgerCacheService._apply_changes(batch, values, exclude=("first_synced_at", "last_synced_at"))
            batch.last_synced_at = now
            batch.save()
            return GLCacheUpsertResult(batch, False, changed, not changed, metadata)

    @staticmethod
    def upsert_entry(command: UpsertGLEntryCommand) -> GLCacheUpsertResult:
        metadata = deepcopy(command.metadata or {})
        batch = command.batch
        dto = command.dto
        GeneralLedgerCacheService._validate_integration_organization(batch.integration, batch.organization)
        external_id = dto.entry_id or GeneralLedgerCacheService._fallback_identity(
            "gl-entry",
            batch.external_id,
            command.sequence,
            dto.account_code,
            dto.debit_amount,
            dto.credit_amount,
            dto.memo,
            dto.raw,
        )

        with transaction.atomic():
            now = timezone.now()
            values = GeneralLedgerCacheService._entry_values(batch, dto, external_id, command.sequence, synced_at=now)
            entry = AccountingGLEntry.objects.filter(
                integration=batch.integration,
                batch=batch,
                external_id=external_id,
            ).first()

            if entry is None:
                entry = AccountingGLEntry.objects.create(**values)
                return GLCacheUpsertResult(entry, True, False, False, metadata)

            GeneralLedgerCacheService._validate_batch_entry_organization(batch, entry)
            changed = GeneralLedgerCacheService._apply_changes(entry, values, exclude=("first_synced_at", "last_synced_at"))
            entry.last_synced_at = now
            entry.save()
            return GLCacheUpsertResult(entry, False, changed, not changed, metadata)

    @staticmethod
    def upsert_allocation(command: UpsertGLAllocationCommand) -> GLCacheUpsertResult:
        metadata = deepcopy(command.metadata or {})
        entry = command.entry
        dto = command.dto
        GeneralLedgerCacheService._validate_entry_relationship(entry)
        external_id = GeneralLedgerCacheService._allocation_identity(entry, dto, command.sequence)

        with transaction.atomic():
            now = timezone.now()
            values = GeneralLedgerCacheService._allocation_values(
                entry,
                dto,
                external_id,
                synced_at=now,
            )
            allocation = AccountingGLAllocation.objects.filter(entry=entry, external_id=external_id).first()

            if allocation is None:
                allocation = AccountingGLAllocation.objects.create(**values)
                return GLCacheUpsertResult(allocation, True, False, False, metadata)

            GeneralLedgerCacheService._validate_entry_allocation_organization(entry, allocation)
            changed = GeneralLedgerCacheService._apply_changes(
                allocation,
                values,
                exclude=("first_synced_at", "last_synced_at"),
            )
            allocation.last_synced_at = now
            allocation.save()
            return GLCacheUpsertResult(allocation, False, changed, not changed, metadata)

    @staticmethod
    def persist_batch_tree(integration, batch_dto, sync_run=None, metadata=None):
        tree_metadata = deepcopy(metadata or {})

        with transaction.atomic():
            batch_result = GeneralLedgerCacheService.upsert_batch(
                UpsertGLBatchCommand(integration=integration, dto=batch_dto, sync_run=sync_run, metadata=tree_metadata)
            )
            entry_results = []
            allocation_results = []
            for entry_sequence, entry_dto in enumerate(batch_dto.entries or (), start=1):
                entry_result = GeneralLedgerCacheService.upsert_entry(
                    UpsertGLEntryCommand(
                        batch=batch_result.object,
                        dto=entry_dto,
                        sequence=entry_sequence,
                        sync_run=sync_run,
                        metadata=tree_metadata,
                    )
                )
                entry_results.append(entry_result)
                for allocation_sequence, allocation_dto in enumerate(entry_dto.cost_allocations or (), start=1):
                    allocation_results.append(
                        GeneralLedgerCacheService.upsert_allocation(
                            UpsertGLAllocationCommand(
                                entry=entry_result.object,
                                dto=allocation_dto,
                                sequence=allocation_sequence,
                                sync_run=sync_run,
                                metadata=tree_metadata,
                            )
                        )
                    )

            all_results = [batch_result, *entry_results, *allocation_results]
            return {
                "batch_result": batch_result,
                "entry_results": entry_results,
                "allocation_results": allocation_results,
                "created_count": sum(1 for result in all_results if result.created),
                "updated_count": sum(1 for result in all_results if result.updated),
                "unchanged_count": sum(1 for result in all_results if result.unchanged),
                "metadata": tree_metadata,
            }

    @staticmethod
    def _batch_values(integration, dto, *, synced_at):
        return {
            "organization": integration.organization,
            "integration": integration,
            "external_id": str(dto.external_id),
            "batch_code": str(dto.batch_code or ""),
            "number": str(dto.number or ""),
            "source_document_id": str(dto.source_document_id or ""),
            "document": str(dto.document or ""),
            "batch_date": GeneralLedgerCacheService._as_date(dto.batch_date),
            "currency_code": str(dto.currency_code or ""),
            "currency_rate": dto.currency_rate,
            "total_amount": dto.total_amount,
            "price_includes_vat": dto.price_includes_vat,
            "source_changed_at": GeneralLedgerCacheService._as_datetime(dto.changed_at),
            "raw_data": GeneralLedgerCacheService._json_safe_copy(dto.raw or {}),
            "source_created_at": None,
            "first_synced_at": synced_at,
            "last_synced_at": synced_at,
        }

    @staticmethod
    def _entry_values(batch, dto, external_id, sequence, *, synced_at):
        return {
            "organization": batch.organization,
            "integration": batch.integration,
            "batch": batch,
            "external_id": external_id,
            "source_entry_id": str(dto.entry_id or ""),
            "sequence": sequence,
            "account_code": str(dto.account_code or ""),
            "account_name": str(dto.account_name or ""),
            "memo": str(dto.memo or ""),
            "department_code": str(dto.department_code or ""),
            "debit_amount": dto.debit_amount or Decimal("0"),
            "debit_currency": str(dto.debit_currency or ""),
            "credit_amount": dto.credit_amount or Decimal("0"),
            "credit_currency": str(dto.credit_currency or ""),
            "type_id": str(dto.type_id or ""),
            "tax_id": str(dto.tax_id or ""),
            "tax_percent": dto.tax_percent,
            "raw_data": GeneralLedgerCacheService._json_safe_copy(dto.raw or {}),
            "first_synced_at": synced_at,
            "last_synced_at": synced_at,
        }

    @staticmethod
    def _allocation_values(entry, dto, external_id, *, synced_at):
        dimension_code = str(dto.code or "")
        accounting_dimension = GeneralLedgerCacheService._find_accounting_dimension(entry, dimension_code)
        project = GeneralLedgerCacheService._find_project(entry, dimension_code)
        GeneralLedgerCacheService._validate_optional_links(entry, accounting_dimension, project)
        return {
            "organization": entry.organization,
            "integration": entry.integration,
            "entry": entry,
            "external_id": external_id,
            "source_type": str(dto.source_type or ""),
            "dimension_code": dimension_code,
            "dimension_name": str(dto.name or ""),
            "dimension_type": str(dto.source_type or ""),
            "multiplier": dto.multiplier,
            "amount": dto.amount or Decimal("0"),
            "accounting_dimension": accounting_dimension,
            "project": project,
            "raw_data": GeneralLedgerCacheService._json_safe_copy(dto.raw or {}),
            "first_synced_at": synced_at,
            "last_synced_at": synced_at,
        }

    @staticmethod
    def _allocation_identity(entry, dto, sequence):
        provider_parts = [dto.batch_id, dto.entry_id, sequence, dto.source_type, dto.code, dto.multiplier]
        if all(value not in {None, ""} for value in provider_parts):
            return GeneralLedgerCacheService._fallback_identity("gl-allocation-provider", *provider_parts, sequence)
        return GeneralLedgerCacheService._fallback_identity(
            "gl-allocation",
            entry.external_id,
            sequence,
            dto.source_type,
            dto.code,
            dto.amount,
            dto.multiplier,
            dto.raw,
        )

    @staticmethod
    def _fallback_identity(prefix, *parts):
        payload = json.dumps([str(part) for part in parts], ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
        return f"{prefix}:{digest}"

    @staticmethod
    def _apply_changes(instance, values, *, exclude=()):
        changed = False
        for field, value in values.items():
            if field in exclude:
                continue
            current = getattr(instance, field)
            if current != value:
                setattr(instance, field, value)
                changed = True
        return changed

    @staticmethod
    def _find_accounting_dimension(entry, dimension_code):
        if not dimension_code:
            return None
        return AccountingDimension.objects.filter(
            organization=entry.organization,
            provider=entry.integration.provider,
            dimension_type=AccountingDimension.DimensionType.PROJECT,
            code=dimension_code,
        ).first()

    @staticmethod
    def _find_project(entry, dimension_code):
        if not dimension_code:
            return None
        return Project.objects.filter(organization=entry.organization, code=dimension_code).first()

    @staticmethod
    def _validate_integration_organization(integration, organization):
        if integration.organization_id != organization.id:
            raise ValueError("GL cache organization must match integration organization.")

    @staticmethod
    def _validate_batch_entry_organization(batch, entry):
        if entry.organization_id != batch.organization_id or entry.integration_id != batch.integration_id:
            raise ValueError("GL entry organization and integration must match batch.")

    @staticmethod
    def _validate_entry_relationship(entry):
        if entry.organization_id != entry.batch.organization_id or entry.integration_id != entry.batch.integration_id:
            raise ValueError("GL entry organization and integration must match its batch.")

    @staticmethod
    def _validate_entry_allocation_organization(entry, allocation):
        if allocation.organization_id != entry.organization_id or allocation.integration_id != entry.integration_id:
            raise ValueError("GL allocation organization and integration must match entry.")

    @staticmethod
    def _validate_optional_links(entry, accounting_dimension, project):
        if accounting_dimension and accounting_dimension.organization_id != entry.organization_id:
            raise ValueError("Linked accounting dimension must belong to the same organization.")
        if project and project.organization_id != entry.organization_id:
            raise ValueError("Linked project must belong to the same organization.")

    @staticmethod
    def _json_safe_copy(value):
        return json.loads(json.dumps(deepcopy(value), ensure_ascii=False, default=str))

    @staticmethod
    def _as_date(value):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return None

    @staticmethod
    def _as_datetime(value):
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, time.min, tzinfo=timezone.get_current_timezone())
        return None
