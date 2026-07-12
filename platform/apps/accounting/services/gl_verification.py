from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Count, Q, Sum

from apps.accounting.models import (
    AccountingGLAllocation,
    AccountingGLBatch,
    AccountingGLEntry,
    AccountingSyncRun,
    AccountingSyncState,
)

from .commands import GeneralLedgerVerificationResult, VerifyGeneralLedgerCommand


ZERO = Decimal("0")


class GeneralLedgerVerificationService:
    """Read-only diagnostics for persisted GL sync results.

    This service never calls Merit and never mutates cache rows. It inspects
    the existing GL cache, sync state and run history so operators can verify
    real sync results safely before financial aggregation exists.
    """

    @classmethod
    def verify(cls, command: VerifyGeneralLedgerCommand) -> GeneralLedgerVerificationResult:
        metadata = deepcopy(command.metadata or {})
        period_start = cls._coerce_date(command.period_start, "period_start")
        period_end = cls._coerce_date(command.period_end, "period_end")
        if period_end < period_start:
            raise ValueError("Verification period_end cannot be before period_start.")

        integration = command.integration
        batches = AccountingGLBatch.objects.filter(
            integration=integration,
            batch_date__gte=period_start,
            batch_date__lte=period_end,
        ).select_related("organization", "integration")
        entries = AccountingGLEntry.objects.filter(batch__in=batches).select_related("batch", "organization", "integration")
        allocations = AccountingGLAllocation.objects.filter(entry__batch__in=batches).select_related(
            "entry",
            "entry__batch",
            "organization",
            "integration",
            "project",
            "accounting_dimension",
        )

        sync_state = AccountingSyncState.objects.filter(
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
        ).first()
        sync_run = cls._latest_matching_run(integration, period_start, period_end)

        batch_count = batches.count()
        entry_count = entries.count()
        allocation_count = allocations.count()
        linked_project_count = allocations.filter(project__isnull=False).count()
        linked_dimension_count = allocations.filter(accounting_dimension__isnull=False).count()
        linked_both_count = allocations.filter(project__isnull=False, accounting_dimension__isnull=False).count()
        linked_neither_count = allocations.filter(project__isnull=True, accounting_dimension__isnull=True).count()
        blank_dimension_codes = allocations.filter(Q(dimension_code="") | Q(dimension_code__isnull=True)).count()
        zero_amount_allocations = allocations.filter(amount=ZERO).count()
        unlinked_codes = list(
            allocations.filter(project__isnull=True)
            .exclude(dimension_code="")
            .values_list("dimension_code", flat=True)
            .distinct()
            .order_by("dimension_code")
        )

        total_debit = cls._sum(entries, "debit_amount")
        total_credit = cls._sum(entries, "credit_amount")
        total_allocation = cls._sum(allocations, "amount")
        batch_total_amount = cls._sum(batches.exclude(total_amount__isnull=True), "total_amount")
        balance_difference = total_debit - total_credit

        entry_with_allocations = entries.annotate(allocation_count=Count("allocations")).filter(allocation_count__gt=0)
        entry_without_allocations = entries.annotate(allocation_count=Count("allocations")).filter(allocation_count=0)
        entries_with_allocations_count = entry_with_allocations.count()
        entries_without_allocations_count = entry_without_allocations.count()
        coverage_percentage = cls._percentage(entries_with_allocations_count, entry_count)
        project_link_percentage = cls._percentage(linked_project_count, allocation_count)

        warnings = []
        critical_errors = []
        if balance_difference != ZERO:
            warnings.append(f"Debit and credit totals differ by {balance_difference}.")

        currency_values = cls._currency_values(entries, batches)
        if len(currency_values) > 1:
            warnings.append("Multiple currencies are present; diagnostic totals are not normalized.")

        data_quality = {
            "batches_missing_batch_date": AccountingGLBatch.objects.filter(integration=integration, batch_date__isnull=True).count(),
            "batches_missing_external_id": batches.filter(external_id="").count(),
            "entries_missing_account_code": entries.filter(account_code="").count(),
            "entries_with_debit_and_credit": entries.exclude(debit_amount=ZERO).exclude(credit_amount=ZERO).count(),
            "entries_with_zero_debit_and_credit": entries.filter(debit_amount=ZERO, credit_amount=ZERO).count(),
            "allocation_organization_mismatches": allocations.exclude(organization_id=integration.organization_id).count(),
            "batch_organization_mismatches": batches.exclude(organization_id=integration.organization_id).count(),
            "entry_organization_mismatches": entries.exclude(organization_id=integration.organization_id).count(),
            "project_organization_mismatches": allocations.filter(project__isnull=False).exclude(project__organization_id=integration.organization_id).count(),
            "dimension_organization_mismatches": allocations.filter(accounting_dimension__isnull=False).exclude(
                accounting_dimension__organization_id=integration.organization_id
            ).count(),
        }
        if data_quality["batches_missing_external_id"]:
            critical_errors.append("GL batches with missing external_id were found.")
        if data_quality["allocation_organization_mismatches"] or data_quality["batch_organization_mismatches"] or data_quality["entry_organization_mismatches"]:
            critical_errors.append("GL cache rows with mismatching organization were found.")
        if data_quality["project_organization_mismatches"] or data_quality["dimension_organization_mismatches"]:
            critical_errors.append("Linked Project or AccountingDimension belongs to a different organization.")

        identity = cls._identity_checks(integration, batches, entries, allocations)
        for key, value in identity.items():
            if key.endswith("_duplicates") and value:
                critical_errors.append(f"Duplicate source identity detected: {key}={value}.")

        unlinked_by_count, unlinked_by_amount = cls._top_unlinked_codes(allocations)
        samples = cls._samples(allocations, max(0, int(command.sample_size)))

        result_metadata = {
            "input_metadata": metadata,
            "sync_state": cls._sync_state_summary(sync_state),
            "sync_run": cls._sync_run_summary(sync_run),
            "link_quality": {
                "linked_project_count": linked_project_count,
                "linked_dimension_count": linked_dimension_count,
                "linked_both_count": linked_both_count,
                "linked_neither_count": linked_neither_count,
                "blank_dimension_codes": blank_dimension_codes,
                "zero_amount_allocations": zero_amount_allocations,
                "distinct_unlinked_dimension_codes": unlinked_codes,
            },
            "data_quality": data_quality,
            "financial_totals": {
                "total_debit": total_debit,
                "total_credit": total_credit,
                "balance_difference": balance_difference,
                "total_allocation_amount": total_allocation,
                "batch_total_amount_sum": batch_total_amount,
                "currency_count": len(currency_values),
                "currencies": sorted(currency_values),
                "account_code_count": entries.exclude(account_code="").values("account_code").distinct().count(),
                "dimension_code_count": allocations.exclude(dimension_code="").values("dimension_code").distinct().count(),
            },
            "allocation_coverage": {
                "entries_with_allocations_count": entries_with_allocations_count,
                "entries_without_allocations_count": entries_without_allocations_count,
                "entries_with_allocations_amount": cls._entry_activity_sum(entry_with_allocations),
                "entries_without_allocations_amount": cls._entry_activity_sum(entry_without_allocations),
                "allocation_coverage_percentage": coverage_percentage,
                "project_link_percentage": project_link_percentage,
                "top_unlinked_codes_by_count": unlinked_by_count,
                "top_unlinked_codes_by_absolute_amount": unlinked_by_amount,
            },
            "identity": identity,
            "samples": samples,
        }

        return GeneralLedgerVerificationResult(
            integration=integration,
            period_start=period_start,
            period_end=period_end,
            sync_state=sync_state,
            sync_run=sync_run,
            batch_count=batch_count,
            entry_count=entry_count,
            allocation_count=allocation_count,
            linked_project_count=linked_project_count,
            unlinked_allocation_count=allocation_count - linked_project_count,
            distinct_unlinked_codes=unlinked_codes,
            total_debit=total_debit,
            total_credit=total_credit,
            balance_difference=balance_difference,
            warnings=warnings,
            critical_errors=critical_errors,
            metadata=result_metadata,
        )

    @staticmethod
    def _latest_matching_run(integration, period_start, period_end):
        return (
            AccountingSyncRun.objects.filter(
                integration=integration,
                source_type=AccountingSyncState.SourceType.GL,
                requested_period_start=period_start,
                requested_period_end=period_end,
            )
            .order_by("-started_at", "-id")
            .first()
        )

    @staticmethod
    def _sum(queryset, field_name):
        return queryset.aggregate(total=Sum(field_name))["total"] or ZERO

    @staticmethod
    def _entry_activity_sum(queryset):
        totals = queryset.aggregate(debit=Sum("debit_amount"), credit=Sum("credit_amount"))
        return (totals["debit"] or ZERO) + (totals["credit"] or ZERO)

    @staticmethod
    def _percentage(value, total):
        if not total:
            return ZERO
        return (Decimal(value) / Decimal(total) * Decimal("100")).quantize(Decimal("0.01"))

    @staticmethod
    def _currency_values(entries, batches):
        currencies = set(batches.exclude(currency_code="").values_list("currency_code", flat=True))
        currencies.update(entries.exclude(debit_currency="").values_list("debit_currency", flat=True))
        currencies.update(entries.exclude(credit_currency="").values_list("credit_currency", flat=True))
        return {currency for currency in currencies if currency}

    @staticmethod
    def _identity_checks(integration, batches, entries, allocations):
        batch_duplicates = (
            batches.values("integration_id", "external_id")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
            .count()
        )
        entry_duplicates = (
            entries.values("batch_id", "external_id")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
            .count()
        )
        allocation_duplicates = (
            allocations.values("entry_id", "external_id")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
            .count()
        )
        deterministic_entry_ids = entries.filter(external_id__startswith="generated:").count()
        deterministic_allocation_ids = allocations.filter(external_id__startswith="generated:").count()
        missing_raw_identity = (
            batches.filter(raw_data={}).count()
            + entries.filter(raw_data={}).count()
            + allocations.filter(raw_data={}).count()
        )
        return {
            "batch_duplicates": batch_duplicates,
            "entry_duplicates": entry_duplicates,
            "allocation_duplicates": allocation_duplicates,
            "deterministic_fallback_identities": deterministic_entry_ids + deterministic_allocation_ids,
            "missing_raw_source_identity": missing_raw_identity,
        }

    @staticmethod
    def _top_unlinked_codes(allocations):
        unlinked = allocations.filter(project__isnull=True).exclude(dimension_code="")
        by_count = list(
            unlinked.values("dimension_code")
            .annotate(count=Count("id"))
            .order_by("-count", "dimension_code")[:10]
        )
        amount_counter = defaultdict(Decimal)
        for code, amount in unlinked.values_list("dimension_code", "amount"):
            amount_counter[code] += abs(amount or ZERO)
        by_amount = [
            {"dimension_code": code, "absolute_amount": amount}
            for code, amount in sorted(amount_counter.items(), key=lambda item: (-item[1], item[0]))[:10]
        ]
        return by_count, by_amount

    @staticmethod
    def _samples(allocations, sample_size):
        project_linked = []
        unlinked = []
        for allocation in allocations.filter(project__isnull=False).order_by("entry__batch__batch_date", "id")[:sample_size]:
            project_linked.append(GeneralLedgerVerificationService._allocation_sample(allocation, linked=True))
        for allocation in allocations.filter(project__isnull=True).order_by("entry__batch__batch_date", "id")[:sample_size]:
            unlinked.append(GeneralLedgerVerificationService._allocation_sample(allocation, linked=False))
        return {"project_linked": project_linked, "unlinked": unlinked}

    @staticmethod
    def _allocation_sample(allocation, *, linked):
        reason = ""
        if not linked:
            if not allocation.dimension_code:
                reason = "blank dimension code"
            elif not allocation.accounting_dimension_id:
                reason = "no AccountingDimension match"
            elif allocation.accounting_dimension.organization_id != allocation.organization_id:
                reason = "organization mismatch"
            else:
                reason = "no exact Project.code match"
        return {
            "project_code": allocation.project.code if allocation.project_id else "",
            "project_name": allocation.project.name if allocation.project_id else "",
            "dimension_code": allocation.dimension_code,
            "dimension_name": allocation.dimension_name,
            "amount": allocation.amount,
            "account_code": allocation.entry.account_code,
            "batch_date": allocation.entry.batch.batch_date,
            "batch_external_id": allocation.entry.batch.external_id,
            "reason": reason,
        }

    @staticmethod
    def _sync_state_summary(sync_state):
        if not sync_state:
            return None
        return {
            "source_type": sync_state.source_type,
            "status": sync_state.sync_status,
            "last_successful_sync_at": sync_state.last_successful_sync_at,
            "last_completed_period_start": sync_state.last_completed_period_start,
            "last_completed_period_end": sync_state.last_completed_period_end,
            "last_error_present": bool(sync_state.last_error),
        }

    @staticmethod
    def _sync_run_summary(sync_run):
        if not sync_run:
            return None
        return {
            "id": sync_run.id,
            "mode": sync_run.mode,
            "status": sync_run.status,
            "started_at": sync_run.started_at,
            "completed_at": sync_run.completed_at,
            "discovered_count": sync_run.discovered_count,
            "created_count": sync_run.created_count,
            "updated_count": sync_run.updated_count,
            "unchanged_count": sync_run.unchanged_count,
            "failed_count": sync_run.failed_count,
            "safe_error_present": bool(sync_run.safe_error),
        }

    @staticmethod
    def _coerce_date(value, field_name):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value.strip()[:10])
            except ValueError as exc:
                raise ValueError(f"{field_name} must be a date or ISO date string.") from exc
        raise ValueError(f"{field_name} must be a date or ISO date string.")
