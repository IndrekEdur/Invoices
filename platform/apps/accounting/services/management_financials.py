from collections import defaultdict
from copy import deepcopy
from decimal import Decimal

from django.db.models import Q

from apps.accounting.models import ManagementAllocationEntry, VersionStatus

from .commands import (
    ManagementAllocationBreakdownItem,
    ManagementFinancialMonth,
    ManagementFinancialResult,
)


ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")


class ProjectManagementFinancialService:
    """Combine direct project accounting aggregates with approved management allocations."""

    @classmethod
    def build(cls, command) -> ManagementFinancialResult:
        accounting_result = command.accounting_result
        metadata = deepcopy(command.metadata or {})
        incoming_entries = cls._approved_entries(accounting_result)
        outgoing_entries = cls._approved_outgoing_entries(accounting_result)
        incoming_breakdown = cls._breakdown(incoming_entries, direction="in")
        outgoing_breakdown = cls._breakdown(outgoing_entries, direction="out")
        allocated_in = sum((item.amount for item in incoming_breakdown), ZERO)
        allocated_out = sum((item.amount for item in outgoing_breakdown), ZERO)
        net_management_allocation = allocated_in - allocated_out
        monthly_incoming_breakdowns = cls._monthly_breakdowns(incoming_entries, direction="in")
        monthly_outgoing_breakdowns = cls._monthly_breakdowns(outgoing_entries, direction="out")
        months = [
            cls._month(
                month,
                monthly_incoming_breakdowns.get((month.year, month.month), []),
                monthly_outgoing_breakdowns.get((month.year, month.month), []),
            )
            for month in accounting_result.months
        ]
        management_total_cost = accounting_result.total_cost + net_management_allocation
        management_result = accounting_result.revenue - management_total_cost
        warnings = cls._warnings(accounting_result, incoming_entries, incoming_breakdown)
        return ManagementFinancialResult(
            project=accounting_result.project,
            period_start=accounting_result.period_start,
            period_end=accounting_result.period_end,
            currency=accounting_result.currency,
            months=months,
            direct_revenue=accounting_result.revenue,
            direct_cost=accounting_result.total_cost,
            allocated_management_cost=allocated_in,
            management_cost_allocated_in=allocated_in,
            management_cost_allocated_out=allocated_out,
            net_management_allocation=net_management_allocation,
            management_total_cost=management_total_cost,
            accounting_result=accounting_result.result,
            management_result=management_result,
            accounting_margin=accounting_result.margin,
            management_margin=cls._margin(accounting_result.revenue, management_result),
            allocation_breakdown=incoming_breakdown,
            warnings=warnings,
            metadata={
                "input_metadata": metadata,
                "allocation_entry_count": len(incoming_entries),
                "allocated_out_entry_count": len(outgoing_entries),
                "approved_version_ids": sorted({entry.version_id for entry in incoming_entries + outgoing_entries}),
                "allocated_out_breakdown": outgoing_breakdown,
            },
        )

    @staticmethod
    def _approved_entries(accounting_result):
        month_filters = Q()
        for month in accounting_result.months:
            month_filters |= Q(version__period__year=month.year, version__period__month=month.month)
        if not month_filters:
            return []
        return list(
            ManagementAllocationEntry.objects.filter(
                project=accounting_result.project,
                project__organization=accounting_result.project.organization,
                version__status=VersionStatus.APPROVED,
                version__period__organization=accounting_result.project.organization,
            )
            .filter(month_filters)
            .select_related("version", "version__period", "version__pool", "version__source_project", "project")
            .order_by(
                "version__period__year",
                "version__period__month",
                "version__pool__display_order",
                "version__pool__name",
                "version__source_project__code",
                "id",
            )
        )

    @classmethod
    def _approved_outgoing_entries(cls, accounting_result):
        month_filters = Q()
        for month in accounting_result.months:
            month_filters |= Q(version__period__year=month.year, version__period__month=month.month)
        if not month_filters:
            return []
        return list(
            ManagementAllocationEntry.objects.filter(
                version__source_project=accounting_result.project,
                version__status=VersionStatus.APPROVED,
                version__period__organization=accounting_result.project.organization,
            )
            .filter(month_filters)
            .select_related("version", "version__period", "version__pool", "version__source_project", "project")
            .order_by("version__period__year", "version__period__month", "project__code", "id")
        )

    @classmethod
    def _breakdown(cls, entries, *, direction="in"):
        total = sum((entry.amount for entry in entries), ZERO)
        grouped = defaultdict(lambda: {"amount": ZERO, "entries": []})
        for entry in entries:
            grouped[entry.version_id]["amount"] += entry.amount or ZERO
            grouped[entry.version_id]["entries"].append(entry)
        items = []
        for version_id, data in grouped.items():
            first = data["entries"][0]
            percentage = ZERO
            if total:
                percentage = (data["amount"] / total * ONE_HUNDRED).quantize(Decimal("0.01"))
            items.append(
                ManagementAllocationBreakdownItem(
                    pool=first.version.pool,
                    version=first.version,
                    period=first.version.period,
                    amount=data["amount"],
                    percentage_of_total=percentage,
                    source_version=f"v{first.version.version_number}",
                    approved_at=first.version.approved_at,
                    direction=direction,
                    metadata={
                        "entry_ids": [entry.id for entry in data["entries"]],
                        "manual_override": any(entry.manual_override for entry in data["entries"]),
                        "source_type": first.version.source_type,
                        "source_identifier": first.version.source_identifier,
                    },
                )
            )
        return sorted(
            items,
            key=lambda item: (
                item.period.year,
                item.period.month,
                item.pool.display_order if item.pool else 9999,
                item.pool.name if item.pool else item.version.source_display_name,
                item.version.id,
            ),
        )

    @classmethod
    def _monthly_breakdowns(cls, entries, *, direction="in"):
        grouped = defaultdict(list)
        for item in cls._breakdown(entries, direction=direction):
            grouped[(item.period.year, item.period.month)].append(item)
        return grouped

    @classmethod
    def _month(cls, month, incoming_breakdown, outgoing_breakdown):
        allocated_in = sum((item.amount for item in incoming_breakdown), ZERO)
        allocated_out = sum((item.amount for item in outgoing_breakdown), ZERO)
        net_management_allocation = allocated_in - allocated_out
        management_total_cost = month.total_cost + net_management_allocation
        management_result = month.revenue - management_total_cost
        warnings = list(month.warnings)
        if not incoming_breakdown and not outgoing_breakdown:
            warnings.append("no_approved_management_allocations")
        return ManagementFinancialMonth(
            year=month.year,
            month=month.month,
            period_start=month.period_start,
            period_end=month.period_end,
            direct_revenue=month.revenue,
            direct_cost=month.total_cost,
            allocated_management_cost=allocated_in,
            management_cost_allocated_in=allocated_in,
            management_cost_allocated_out=allocated_out,
            net_management_allocation=net_management_allocation,
            management_total_cost=management_total_cost,
            accounting_result=month.result,
            management_result=management_result,
            accounting_margin=month.margin,
            management_margin=cls._margin(month.revenue, management_result),
            warnings=warnings,
            allocation_breakdown=incoming_breakdown,
            metadata={"allocated_out_breakdown": outgoing_breakdown},
        )

    @staticmethod
    def _warnings(accounting_result, entries, breakdown):
        warnings = []
        approved_months = {(entry.version.period.year, entry.version.period.month) for entry in entries}
        result_months = {(month.year, month.month) for month in accounting_result.months}
        missing_months = sorted(result_months - approved_months)
        if not entries:
            warnings.append("no_approved_management_allocations")
        elif missing_months:
            warnings.append(
                "missing_approved_management_allocations:"
                + ",".join(f"{year:04d}-{month:02d}" for year, month in missing_months)
            )
        draft_exists = ManagementAllocationEntry.objects.filter(
            project=accounting_result.project,
            project__organization=accounting_result.project.organization,
            version__status=VersionStatus.DRAFT,
            version__period__organization=accounting_result.project.organization,
            version__pool__organization=accounting_result.project.organization,
        ).filter(
            Q(version__period__year__gt=accounting_result.period_start.year)
            | Q(version__period__year=accounting_result.period_start.year, version__period__month__gte=accounting_result.period_start.month),
            Q(version__period__year__lt=accounting_result.period_end.year)
            | Q(version__period__year=accounting_result.period_end.year, version__period__month__lte=accounting_result.period_end.month),
        ).exists()
        if draft_exists:
            warnings.append("draft_management_allocation_exists")
        if "mixed_currency" in accounting_result.warnings:
            warnings.append("mixed_currency")
        if not breakdown:
            return warnings
        pool_count = len({item.pool.id for item in breakdown if item.pool})
        if pool_count < 1:
            warnings.append("cost_pool_not_applicable")
        return warnings

    @staticmethod
    def _margin(revenue, result):
        if revenue == ZERO:
            return None
        return (result / revenue * ONE_HUNDRED).quantize(Decimal("0.01"))
