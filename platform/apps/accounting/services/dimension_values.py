from copy import deepcopy

from django.db import transaction
from django.utils import timezone

from apps.accounting.connectors import MeritAPIClient
from apps.accounting.models import AccountingDimension
from apps.core.services import AuditService

from .commands import CreateAccountingDimensionValueCommand, CreateAccountingDimensionValueResult


class AccountingDimensionValueService:
    """Create or update a Merit dimension value and align the local cache.

    The connector owns external HTTP calls. This service owns local persistence
    after a successful external response and records an audit event.
    """

    @staticmethod
    def create(command: CreateAccountingDimensionValueCommand) -> CreateAccountingDimensionValueResult:
        if command.dimension_id is None:
            raise ValueError("dimension_id is required to create a Merit dimension value.")

        metadata = deepcopy(command.metadata or {})
        integration = command.integration

        with transaction.atomic():
            dto = MeritAPIClient(integration).create_dimension_value(
                code=command.code,
                name=command.name,
                dimension_type=command.dimension_type,
                dimension_id=command.dimension_id,
                external_id=command.external_id,
                end_date=command.end_date,
            )
            dimension, created, updated = AccountingDimensionValueService._upsert_dimension(
                integration=integration,
                dto=dto,
                command=command,
                synced_at=timezone.now(),
            )

            AuditService.record(
                event_type="accounting_dimension_value_created",
                message=f"Created or updated accounting dimension value {dimension.code} {dimension.name}.",
                organization=integration.organization,
                actor=command.actor,
                object_type="AccountingDimension",
                object_id=str(dimension.id),
                metadata={
                    **metadata,
                    "created": created,
                    "updated": updated,
                    "dimension_type": dimension.dimension_type,
                    "external_id": dimension.external_id,
                },
            )

            return CreateAccountingDimensionValueResult(
                dimension=dimension,
                dto=dto,
                created=created,
                updated=updated,
                metadata=metadata,
            )

    @staticmethod
    def _upsert_dimension(*, integration, dto, command, synced_at):
        dimension_type = command.dimension_type
        code = dto.code or command.code
        name = dto.name or command.name
        external_id = dto.external_id or command.external_id
        raw_data = deepcopy(dto.raw or {})

        lookup = {
            "organization": integration.organization,
            "provider": integration.provider,
            "dimension_type": dimension_type,
        }
        dimension = None
        if external_id:
            dimension = AccountingDimension.objects.filter(
                **lookup,
                integration=integration,
                external_id=external_id,
            ).first()
        if dimension is None:
            dimension = AccountingDimension.objects.filter(**lookup, code=code).first()

        values = {
            "organization": integration.organization,
            "integration": integration,
            "provider": integration.provider,
            "external_id": external_id or None,
            "code": code,
            "name": name,
            "dimension_type": dimension_type,
            "is_active": dto.active,
            "raw_data": raw_data,
            "last_synced_at": synced_at,
        }

        if dimension is None:
            return AccountingDimension.objects.create(**values), True, False

        updated = not AccountingDimensionValueService._dimension_matches_values(dimension, values)
        for field, value in values.items():
            setattr(dimension, field, value)
        dimension.save()
        return dimension, False, updated

    @staticmethod
    def _dimension_matches_values(dimension, values):
        return (
            dimension.integration == values["integration"]
            and dimension.external_id == values["external_id"]
            and dimension.code == values["code"]
            and dimension.name == values["name"]
            and dimension.dimension_type == values["dimension_type"]
            and dimension.is_active == values["is_active"]
            and dimension.raw_data == values["raw_data"]
        )
