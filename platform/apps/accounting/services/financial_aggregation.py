from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal

from apps.accounting.models import (
    AccountingAccountClassification,
    AccountingGLAllocation,
)

from .commands import (
    AggregateProjectFinancialsCommand,
    ProjectFinancialAggregationResult,
    ProjectFinancialCategoryTotal,
    ProjectFinancialMonth,
)


ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")
RESULT_COST_CATEGORIES = {
    AccountingAccountClassification.Category.MATERIAL_COST,
    AccountingAccountClassification.Category.SUBCONTRACTOR_COST,
    AccountingAccountClassification.Category.LABOR_COST,
    AccountingAccountClassification.Category.EQUIPMENT_COST,
    AccountingAccountClassification.Category.TRANSPORT_COST,
    AccountingAccountClassification.Category.OTHER_DIRECT_COST,
}


class AccountClassificationService:
    """Read-only exact account-code classification lookup."""

    @classmethod
    def get_classification(cls, organization, integration, account_code):
        mappings = cls._mapping_cache(organization, [integration] if integration else [])
        return cls._lookup_from_cache(mappings, integration, account_code)

    @classmethod
    def classify_entry(cls, entry):
        return cls.get_classification(entry.organization, entry.integration, entry.account_code)

    @classmethod
    def preload(cls, organization, integrations):
        return cls._mapping_cache(organization, integrations)

    @classmethod
    def lookup_from_cache(cls, cache, integration, account_code):
        return cls._lookup_from_cache(cache, integration, account_code)

    @staticmethod
    def unclassified(account_code=""):
        return {
            "account_code": account_code or "",
            "account_name": "",
            "category": AccountingAccountClassification.Category.UNCLASSIFIED,
            "reporting_sign": Decimal("1"),
            "include_in_project_result": True,
            "classification": None,
        }

    @staticmethod
    def _mapping_cache(organization, integrations):
        integration_ids = {integration.id for integration in integrations if integration}
        queryset = AccountingAccountClassification.objects.filter(
            organization=organization,
            is_active=True,
        ).filter(integration__isnull=True)
        if integration_ids:
            queryset = AccountingAccountClassification.objects.filter(
                organization=organization,
                is_active=True,
            ).filter(integration__isnull=True) | AccountingAccountClassification.objects.filter(
                organization=organization,
                is_active=True,
                integration_id__in=integration_ids,
            )

        cache = {"integration": {}, "organization": {}}
        for classification in queryset.select_related("integration"):
            item = {
                "account_code": classification.account_code,
                "account_name": classification.account_name,
                "category": classification.category,
                "reporting_sign": classification.reporting_sign,
                "include_in_project_result": classification.include_in_project_result,
                "classification": classification,
            }
            if classification.integration_id:
                cache["integration"][(classification.integration_id, classification.account_code)] = item
            else:
                cache["organization"][classification.account_code] = item
        return cache

    @staticmethod
    def _lookup_from_cache(cache, integration, account_code):
        code = account_code or ""
        if integration:
            mapped = cache["integration"].get((integration.id, code))
            if mapped:
                return mapped
        return cache["organization"].get(code) or AccountClassificationService.unclassified(code)


class ProjectFinancialAggregationService:
    def __init__(self, classification_service=None):
        self.classification_service = classification_service or AccountClassificationService

    def aggregate(self, command: AggregateProjectFinancialsCommand) -> ProjectFinancialAggregationResult:
        metadata = deepcopy(command.metadata or {})
        period_start = self._coerce_date(command.period_start, "period_start")
        period_end = self._coerce_date(command.period_end, "period_end")
        if period_end < period_start:
            raise ValueError("Project financial period_end cannot be before period_start.")

        project = command.project
        warnings = []
        missing_batch_date_count = AccountingGLAllocation.objects.filter(
            project=project,
            organization=project.organization,
            entry__batch__batch_date__isnull=True,
        ).count()
        if missing_batch_date_count:
            warnings.append(f"missing_batch_date:{missing_batch_date_count}")

        dimension_only_count = AccountingGLAllocation.objects.filter(
            project__isnull=True,
            organization=project.organization,
            dimension_code=project.code,
            entry__batch__batch_date__gte=period_start,
            entry__batch__batch_date__lte=period_end,
        ).count()
        if dimension_only_count:
            warnings.append(f"dimension_code_matches_project_without_project_fk:{dimension_only_count}")

        allocations = (
            AccountingGLAllocation.objects.filter(
                project=project,
                organization=project.organization,
                entry__batch__batch_date__gte=period_start,
                entry__batch__batch_date__lte=period_end,
                entry__organization=project.organization,
                entry__batch__organization=project.organization,
                integration__organization=project.organization,
            )
            .select_related("entry", "entry__batch", "integration", "project")
            .order_by("entry__batch__batch_date", "id")
        )

        currencies_found = sorted({currency for currency in allocations.values_list("entry__batch__currency_code", flat=True) if currency})
        if command.currency:
            allocations = allocations.filter(entry__batch__currency_code=command.currency)
            currency = command.currency
        elif len(currencies_found) == 1:
            currency = currencies_found[0]
        elif len(currencies_found) > 1:
            currency = ""
            warnings.append("mixed_currency")
            allocations = allocations.none()
        else:
            currency = ""

        integrations = {allocation.integration_id: allocation.integration for allocation in allocations}.values()
        classification_cache = self.classification_service.preload(project.organization, integrations)
        month_buckets = {month: [] for month in self.split_months(period_start, period_end)}
        totals = self._empty_totals()
        source_batch_ids = set()
        source_entry_ids = set()
        source_sync_run_ids = set()
        category_details = defaultdict(lambda: {"amount": ZERO, "allocations": 0, "entries": set(), "account_codes": set()})
        unclassified_allocation_count = 0

        for allocation in allocations:
            batch = allocation.entry.batch
            month_key = self._month_interval_for_date(month_buckets, batch.batch_date)
            if month_key is None:
                continue

            classification = self.classification_service._lookup_from_cache(
                classification_cache,
                allocation.integration,
                allocation.entry.account_code,
            )
            normalized_amount = (allocation.amount or ZERO) * classification["reporting_sign"]
            category = classification["category"]
            source_batch_ids.add(batch.id)
            source_entry_ids.add(allocation.entry_id)
            if allocation.raw_data.get("sync_run_id"):
                source_sync_run_ids.add(allocation.raw_data["sync_run_id"])

            self._apply_amount(
                totals,
                category_details,
                category,
                normalized_amount,
                allocation,
                classification,
                command.include_overhead,
            )
            month_buckets[month_key].append((allocation, classification, normalized_amount))
            if category == AccountingAccountClassification.Category.UNCLASSIFIED or not classification["classification"]:
                unclassified_allocation_count += 1

        months = [
            self._build_month(interval, values, command.include_overhead)
            for interval, values in month_buckets.items()
        ]
        allocation_count = sum(month.allocation_count for month in months)
        source_sync_runs = self._sync_run_ids(source_batch_ids)
        source_sync_run_ids.update(source_sync_runs)
        data_quality_status = self._data_quality_status(
            allocation_count,
            totals["unclassified_amount"],
            bool(command.currency),
            currencies_found,
        )
        if totals["unclassified_amount"]:
            warnings.append("unclassified_amount_present")

        return ProjectFinancialAggregationResult(
            project=project,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
            months=months,
            revenue=totals["revenue"],
            total_cost=totals["total_cost"],
            result=totals["revenue"] - totals["total_cost"],
            margin=self._margin(totals["revenue"], totals["revenue"] - totals["total_cost"]),
            classified_amount=totals["classified_amount"],
            unclassified_amount=totals["unclassified_amount"],
            excluded_amount=totals["excluded_amount"],
            allocation_count=allocation_count,
            unclassified_allocation_count=unclassified_allocation_count,
            source_batch_count=len(source_batch_ids),
            source_entry_count=len(source_entry_ids),
            source_sync_run_ids=sorted(source_sync_run_ids),
            warnings=warnings,
            data_quality_status=data_quality_status,
            metadata={
                "input_metadata": metadata,
                "currencies_found": currencies_found,
                "category_totals": self._category_totals(category_details),
                "missing_batch_date_count": missing_batch_date_count,
                "dimension_only_match_count": dimension_only_count,
            },
        )

    @staticmethod
    def split_months(period_start, period_end):
        start = ProjectFinancialAggregationService._coerce_date(period_start, "period_start")
        end = ProjectFinancialAggregationService._coerce_date(period_end, "period_end")
        if end < start:
            raise ValueError("period_end cannot be before period_start.")

        current = start
        intervals = []
        while current <= end:
            next_month = date(current.year + (current.month // 12), (current.month % 12) + 1, 1)
            month_end = min(next_month - timedelta(days=1), end)
            intervals.append((current, month_end))
            current = month_end + timedelta(days=1)
        return intervals

    @staticmethod
    def _apply_amount(totals, category_details, category, amount, allocation, classification, include_overhead):
        detail = category_details[category]
        detail["amount"] += amount
        detail["allocations"] += 1
        detail["entries"].add(allocation.entry_id)
        detail["account_codes"].add(allocation.entry.account_code)

        if category == AccountingAccountClassification.Category.UNCLASSIFIED or not classification["classification"]:
            totals["unclassified_amount"] += amount
            return
        if category == AccountingAccountClassification.Category.EXCLUDED or not classification["include_in_project_result"]:
            totals["excluded_amount"] += amount
            return

        if category == AccountingAccountClassification.Category.REVENUE:
            totals["revenue"] += amount
            totals["classified_amount"] += amount
            return

        cost_categories = set(RESULT_COST_CATEGORIES)
        if include_overhead:
            cost_categories.add(AccountingAccountClassification.Category.OVERHEAD)
        if category in cost_categories:
            totals["total_cost"] += amount
            totals["classified_amount"] += amount

    @classmethod
    def _build_month(cls, interval, values, include_overhead):
        totals = cls._empty_totals()
        category_details = defaultdict(lambda: {"amount": ZERO, "allocations": 0, "entries": set(), "account_codes": set()})
        unclassified_count = 0
        warnings = []
        for allocation, classification, amount in values:
            category = classification["category"]
            cls._apply_amount(totals, category_details, category, amount, allocation, classification, include_overhead)
            if category == AccountingAccountClassification.Category.UNCLASSIFIED or not classification["classification"]:
                unclassified_count += 1
        if totals["unclassified_amount"]:
            warnings.append("unclassified_amount_present")
        result = totals["revenue"] - totals["total_cost"]
        return ProjectFinancialMonth(
            year=interval[0].year,
            month=interval[0].month,
            period_start=interval[0],
            period_end=interval[1],
            revenue=totals["revenue"],
            material_cost=category_details[AccountingAccountClassification.Category.MATERIAL_COST]["amount"],
            subcontractor_cost=category_details[AccountingAccountClassification.Category.SUBCONTRACTOR_COST]["amount"],
            labor_cost=category_details[AccountingAccountClassification.Category.LABOR_COST]["amount"],
            equipment_cost=category_details[AccountingAccountClassification.Category.EQUIPMENT_COST]["amount"],
            transport_cost=category_details[AccountingAccountClassification.Category.TRANSPORT_COST]["amount"],
            other_direct_cost=category_details[AccountingAccountClassification.Category.OTHER_DIRECT_COST]["amount"],
            overhead=category_details[AccountingAccountClassification.Category.OVERHEAD]["amount"] if include_overhead else ZERO,
            total_cost=totals["total_cost"],
            result=result,
            margin=cls._margin(totals["revenue"], result),
            classified_amount=totals["classified_amount"],
            unclassified_amount=totals["unclassified_amount"],
            excluded_amount=totals["excluded_amount"],
            allocation_count=len(values),
            unclassified_allocation_count=unclassified_count,
            warnings=warnings,
            category_totals=cls._category_totals(category_details),
            metadata={},
        )

    @staticmethod
    def _category_totals(category_details):
        return {
            category: ProjectFinancialCategoryTotal(
                category=category,
                amount=details["amount"],
                allocation_count=details["allocations"],
                entry_count=len(details["entries"]),
                source_account_codes=sorted(details["account_codes"]),
            )
            for category, details in category_details.items()
        }

    @staticmethod
    def _empty_totals():
        return {
            "revenue": ZERO,
            "total_cost": ZERO,
            "classified_amount": ZERO,
            "unclassified_amount": ZERO,
            "excluded_amount": ZERO,
        }

    @staticmethod
    def _margin(revenue, result):
        if revenue == ZERO:
            return None
        return (result / revenue * ONE_HUNDRED).quantize(Decimal("0.01"))

    @staticmethod
    def _month_interval_for_date(month_buckets, value):
        for interval in month_buckets:
            if interval[0] <= value <= interval[1]:
                return interval
        return None

    @staticmethod
    def _sync_run_ids(batch_ids):
        if not batch_ids:
            return set()
        return set(
            AccountingGLAllocation.objects.filter(entry__batch_id__in=batch_ids)
            .exclude(raw_data__sync_run_id__isnull=True)
            .values_list("raw_data__sync_run_id", flat=True)
        )

    @staticmethod
    def _data_quality_status(allocation_count, unclassified_amount, explicit_currency, currencies_found):
        if len(currencies_found) > 1 and not explicit_currency:
            return "mixed_currency"
        if allocation_count == 0:
            return "no_data"
        if unclassified_amount:
            return "unclassified"
        return "complete"

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
