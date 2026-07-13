from copy import deepcopy
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounting.models import (
    AccountingAccountClassification,
    AccountingGLEntry,
)
from apps.core.services import AuditService

from .commands import SaveAccountingAccountClassificationCommand


class AccountingAccountClassificationManagementService:
    """Create and update exact-code GL account classifications with audit."""

    @classmethod
    def save(cls, command: SaveAccountingAccountClassificationCommand):
        metadata = deepcopy(command.metadata or {})
        cls._validate_command(command)
        reporting_sign = cls._reporting_sign(command.reporting_sign)

        with transaction.atomic():
            existing = AccountingAccountClassification.objects.filter(
                organization=command.organization,
                integration=command.integration,
                account_code=command.account_code,
            ).first()
            old_values = cls._audit_values(existing)

            classification, _created = AccountingAccountClassification.objects.update_or_create(
                organization=command.organization,
                integration=command.integration,
                account_code=command.account_code,
                defaults={
                    "account_name": command.account_name or "",
                    "category": command.category,
                    "reporting_sign": reporting_sign,
                    "include_in_project_result": command.include_in_project_result,
                    "is_active": command.is_active,
                    "notes": command.notes or "",
                    "metadata": metadata,
                },
            )

            AuditService.record(
                event_type="accounting_account_classification_saved",
                message=f"GL account classification saved for {classification.account_code}.",
                organization=command.organization,
                actor=command.actor,
                object_type="AccountingAccountClassification",
                object_id=str(classification.id),
                metadata={
                    "account_code": classification.account_code,
                    "old": old_values,
                    "new": cls._audit_values(classification),
                    "source": metadata.get("source", "account_classification_settings"),
                },
            )
            return classification

    @staticmethod
    def _validate_command(command):
        if not command.organization:
            raise ValueError("Organization is required for account classification.")
        if not command.integration:
            raise ValueError("Integration is required for account classification.")
        if command.integration.organization_id != command.organization.id:
            raise ValueError("Integration must belong to the selected organization.")
        if command.category not in AccountingAccountClassification.Category.values:
            raise ValidationError("Choose a valid account classification category.")
        AccountingAccountClassificationManagementService._reporting_sign(command.reporting_sign)
        account_exists = AccountingGLEntry.objects.filter(
            organization=command.organization,
            integration=command.integration,
            account_code=command.account_code,
        ).exists()
        if not account_exists:
            raise ValueError("Account code must exist in imported GL data before it can be classified.")

    @staticmethod
    def _reporting_sign(value):
        try:
            sign = Decimal(str(value))
        except (InvalidOperation, TypeError):
            raise ValidationError("Reporting sign must be 1 or -1.")
        if sign not in {Decimal("1"), Decimal("-1")}:
            raise ValidationError("Reporting sign must be 1 or -1.")
        return sign

    @staticmethod
    def _audit_values(classification):
        if not classification:
            return {}
        return {
            "category": classification.category,
            "reporting_sign": str(classification.reporting_sign),
            "include_in_project_result": classification.include_in_project_result,
            "is_active": classification.is_active,
        }
