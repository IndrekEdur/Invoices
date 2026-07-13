from copy import deepcopy
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.projects.models import Project, ProjectParty
from apps.core.services import AuditService

from .commands import (
    AggregateProjectFinancialsCommand,
    CreateManagementAllocationVersionCommand,
    GenerateManagementAllocationProposalResult,
)
from .financial_aggregation import ProjectFinancialAggregationService
from ..models import (
    AccountingGLEntry,
    AllocationStrategy,
    ManagementAllocationRule,
    ManagementAllocationEntry,
    ManagementAllocationPeriod,
    ManagementAllocationVersion,
    ManagementCostPool,
    ManagementCostPoolAccount,
    PeriodStatus,
    VersionStatus,
)

ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")
CURRENCY_QUANT = Decimal("0.01")
PERCENT_QUANT = Decimal("0.0001")


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
            metadata=deepcopy(command.version_metadata or {}),
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


class ManagementAllocationProposalService:
    """Generate draft management allocation versions from explicit project selections."""

    def __init__(
        self,
        project_financial_aggregation_service=None,
        allocation_version_service=None,
        audit_service=None,
    ):
        self.project_financial_aggregation_service = (
            project_financial_aggregation_service or ProjectFinancialAggregationService()
        )
        self.allocation_version_service = allocation_version_service or ManagementAllocationVersionService
        self.audit_service = audit_service or AuditService

    @transaction.atomic
    def generate(self, command):
        metadata = deepcopy(command.metadata or {})
        pool = ManagementCostPool.objects.select_for_update().get(pk=command.pool.pk)
        self._validate_period_input(command.year, command.month)
        if not pool.is_active:
            raise ValueError("Inactive management cost pools cannot generate allocation proposals.")
        if not command.project_ids:
            raise ValueError("Management allocation proposal requires at least one selected project.")

        period, _created = ManagementAllocationPeriod.objects.select_for_update().get_or_create(
            organization=pool.organization,
            year=command.year,
            month=command.month,
            defaults={"status": PeriodStatus.DRAFT},
        )
        if period.status == PeriodStatus.ARCHIVED:
            raise ValueError("Archived management allocation periods cannot receive new proposals.")

        projects = self._selected_projects(pool.organization, command.project_ids)
        strategy, strategy_rule = self._resolve_strategy(pool, command.strategy)
        warnings = []
        if ManagementAllocationVersion.objects.filter(
            period=period,
            pool=pool,
            status=VersionStatus.DRAFT,
        ).exists():
            warnings.append({"code": "existing_draft_version", "message": "Another draft version already exists."})

        period_start = date(command.year, command.month, 1)
        period_end = date(command.year, command.month, monthrange(command.year, command.month)[1])
        source_amount, source_origin, source_diagnostics = self._source_amount(command, pool, period_start, period_end)
        if source_amount == ZERO:
            warnings.append({"code": "zero_source_amount", "message": "Source amount is zero."})

        weights = self._weights_for_strategy(
            strategy=strategy,
            command=command,
            pool=pool,
            projects=projects,
            period_start=period_start,
            period_end=period_end,
            source_amount=source_amount,
            strategy_rule=strategy_rule,
            warnings=warnings,
        )
        entry_payloads, balancing = self._balanced_entries(projects, weights, source_amount)
        total_percentage = sum(item["percentage"] for item in entry_payloads)
        allocated_amount = sum(item["amount"] for item in entry_payloads)
        unallocated_amount = source_amount - allocated_amount

        version_metadata = {
            "strategy": strategy,
            "source_amount_origin": source_origin,
            "source_amount": str(source_amount),
            "selected_project_ids": [project.id for project in projects],
            "selected_project_codes": [project.code for project in projects],
            "generated_at": timezone.now().isoformat(),
            "project_manager_id": command.project_manager_id,
            "calculation_diagnostics": {
                "source": source_diagnostics,
                "warnings": deepcopy(warnings),
                "balancing": balancing,
                "strategy_rule_id": strategy_rule.id if strategy_rule else None,
            },
            "input_metadata": metadata,
        }
        next_version_number = self._next_version_number(period, pool)
        version = self.allocation_version_service.create_version(
            CreateManagementAllocationVersionCommand(
                period=period,
                pool=pool,
                version_number=next_version_number,
                created_by=command.actor,
                reason=command.reason,
                version_metadata=version_metadata,
                metadata={"generated_by": "ManagementAllocationProposalService"},
            )
        )

        entries = [
            ManagementAllocationEntry.objects.create(
                version=version,
                project=item["project"],
                percentage=item["percentage"],
                amount=item["amount"],
                manual_override=item["manual_override"],
                notes=item["notes"],
            )
            for item in entry_payloads
        ]
        self.validate_proposal(version, source_amount=source_amount)

        audit_metadata = {
            "pool_id": pool.id,
            "pool_name": pool.name,
            "period": period.period_label,
            "version_number": version.version_number,
            "strategy": strategy,
            "source_amount": str(source_amount),
            "source_amount_origin": source_origin,
            "selected_project_ids": [project.id for project in projects],
            "selected_project_codes": [project.code for project in projects],
            "total_percentage": str(total_percentage),
            "allocated_amount": str(allocated_amount),
            "warnings": deepcopy(warnings),
        }
        self.audit_service.record(
            event_type="management_allocation_proposal_generated",
            message=f"Management allocation proposal generated for {pool.name} {period.period_label}",
            organization=pool.organization,
            actor=command.actor,
            object_type="ManagementAllocationVersion",
            object_id=str(version.id),
            metadata=audit_metadata,
        )
        return GenerateManagementAllocationProposalResult(
            period=period,
            pool=pool,
            version=version,
            entries=entries,
            strategy=strategy,
            source_amount=source_amount,
            allocated_amount=allocated_amount,
            unallocated_amount=unallocated_amount,
            total_percentage=total_percentage,
            project_count=len(projects),
            warnings=warnings,
            created=True,
            metadata={
                "source_amount_origin": source_origin,
                "source_diagnostics": source_diagnostics,
                "balancing": balancing,
            },
        )

    @staticmethod
    def validate_proposal(version, *, source_amount):
        entries = list(version.entries.select_related("project", "version__period"))
        project_ids = [entry.project_id for entry in entries]
        if len(project_ids) != len(set(project_ids)):
            raise ValueError("Management allocation proposal contains duplicate project entries.")
        for entry in entries:
            if entry.project.organization_id != version.period.organization_id:
                raise ValueError("Management allocation proposal contains a project from another organization.")
            if entry.percentage < ZERO or entry.percentage > ONE_HUNDRED:
                raise ValueError("Management allocation proposal contains invalid percentages.")
        if sum(entry.amount for entry in entries) != source_amount:
            raise ValueError("Management allocation proposal amounts do not balance to source amount.")
        if source_amount != ZERO and sum(entry.percentage for entry in entries) != ONE_HUNDRED:
            raise ValueError("Management allocation proposal percentages do not total 100.")
        if not version.metadata.get("source_amount_origin"):
            raise ValueError("Management allocation proposal lacks source amount traceability metadata.")

    @staticmethod
    def _validate_period_input(year, month):
        if int(year) < 2000:
            raise ValueError("Management allocation year must be 2000 or later.")
        if int(month) < 1 or int(month) > 12:
            raise ValueError("Management allocation month must be between 1 and 12.")

    @staticmethod
    def _selected_projects(organization, project_ids):
        unique_ids = list(dict.fromkeys(project_ids))
        projects = list(
            Project.objects.filter(organization=organization, id__in=unique_ids).order_by("code", "id")
        )
        if len(projects) != len(unique_ids):
            raise ValueError("Selected management allocation projects must belong to the pool organization.")
        return projects

    @staticmethod
    def _resolve_strategy(pool, command_strategy):
        if command_strategy:
            if command_strategy not in AllocationStrategy.values:
                raise ValueError("Unsupported management allocation strategy.")
            return command_strategy, None
        rule = pool.allocation_rules.filter(is_active=True).order_by("id").first()
        strategy = rule.strategy if rule else pool.default_strategy
        if strategy not in AllocationStrategy.values:
            raise ValueError("Unsupported management allocation strategy.")
        return strategy, rule

    @staticmethod
    def _source_amount(command, pool, period_start, period_end):
        if command.source_amount is not None:
            return (
                Decimal(str(command.source_amount)),
                "manual",
                {"manually_supplied": True},
            )

        account_codes = list(
            ManagementCostPoolAccount.objects.filter(pool=pool, is_active=True).values_list("account_code", flat=True)
        )
        if not account_codes:
            return (
                ZERO,
                "gl_pool_accounts",
                {"mapped_account_codes": [], "entry_count": 0, "missing_active_pool_account_mappings": True},
            )
        entries = AccountingGLEntry.objects.filter(
            organization=pool.organization,
            account_code__in=account_codes,
            batch__batch_date__gte=period_start,
            batch__batch_date__lte=period_end,
            batch__organization=pool.organization,
        )
        total = ZERO
        for entry in entries:
            total += (entry.debit_amount or ZERO) - (entry.credit_amount or ZERO)
        return (
            total,
            "gl_pool_accounts",
            {
                "mapped_account_codes": sorted(account_codes),
                "entry_count": entries.count(),
                "amount_semantics": "debit_amount_minus_credit_amount",
            },
        )

    def _weights_for_strategy(
        self,
        *,
        strategy,
        command,
        pool,
        projects,
        period_start,
        period_end,
        source_amount,
        strategy_rule,
        warnings,
    ):
        if strategy == AllocationStrategy.REVENUE:
            return self._revenue_weights(projects, period_start, period_end, warnings)
        if strategy == AllocationStrategy.EQUAL:
            return self._equal_weights(projects)
        if strategy == AllocationStrategy.MANUAL_PERCENT:
            return self._manual_percentage_weights(projects, command.manual_percentages or {})
        if strategy == AllocationStrategy.MANUAL_AMOUNT:
            return self._manual_amount_weights(projects, source_amount, command.manual_amounts or {})
        if strategy == AllocationStrategy.PROJECT_MANAGER:
            self._validate_project_manager(command.project_manager_id, projects)
            basis = "revenue"
            if strategy_rule and strategy_rule.configuration.get("basis"):
                basis = strategy_rule.configuration["basis"]
            if basis == "equal":
                return self._equal_weights(projects, manual_context={"project_manager_id": command.project_manager_id})
            if basis == "revenue":
                return self._revenue_weights(projects, period_start, period_end, warnings)
            raise ValueError("Unsupported project manager allocation basis.")
        raise ValueError("Unsupported management allocation strategy.")

    def _revenue_weights(self, projects, period_start, period_end, warnings):
        revenues = {}
        total_positive = ZERO
        for project in projects:
            result = self.project_financial_aggregation_service.aggregate(
                AggregateProjectFinancialsCommand(project=project, period_start=period_start, period_end=period_end)
            )
            revenue = Decimal(str(result.revenue))
            if revenue > ZERO:
                revenues[project.id] = revenue
                total_positive += revenue
            else:
                revenues[project.id] = ZERO
                code = "zero_revenue_project" if revenue == ZERO else "negative_revenue_project_excluded"
                warnings.append({"code": code, "project_id": project.id, "project_code": project.code})
        if total_positive == ZERO:
            raise ValueError("Revenue allocation requires positive selected-project revenue.")
        return [
            {
                "project": project,
                "weight": revenues[project.id] / total_positive,
                "manual_override": False,
                "notes": "Generated from positive revenue weighting.",
            }
            for project in projects
        ]

    @staticmethod
    def _equal_weights(projects, manual_context=None):
        weight = Decimal("1") / Decimal(len(projects))
        notes = "Generated equal split."
        if manual_context:
            notes = f"{notes} Project manager scope."
        return [{"project": project, "weight": weight, "manual_override": False, "notes": notes} for project in projects]

    @staticmethod
    def _manual_percentage_weights(projects, manual_percentages):
        normalized = {int(key): Decimal(str(value)) for key, value in manual_percentages.items()}
        project_ids = {project.id for project in projects}
        if not set(normalized).issubset(project_ids):
            raise ValueError("Manual percentages contain an unknown project.")
        weights = []
        total = ZERO
        for project in projects:
            percent = normalized.get(project.id, ZERO)
            if percent < ZERO:
                raise ValueError("Manual percentages cannot be negative.")
            total += percent
            weights.append(
                {
                    "project": project,
                    "weight": percent / ONE_HUNDRED,
                    "manual_override": True,
                    "notes": "Generated from manual percentage seed.",
                }
            )
        if total != ONE_HUNDRED:
            raise ValueError("Manual percentages must total exactly 100.")
        return weights

    @staticmethod
    def _manual_amount_weights(projects, source_amount, manual_amounts):
        normalized = {int(key): Decimal(str(value)) for key, value in manual_amounts.items()}
        project_ids = {project.id for project in projects}
        if not set(normalized).issubset(project_ids):
            raise ValueError("Manual amounts contain an unknown project.")
        amounts = {project.id: normalized.get(project.id, ZERO) for project in projects}
        if source_amount >= ZERO and any(amount < ZERO for amount in amounts.values()):
            raise ValueError("Manual negative amounts require a negative source amount.")
        if sum(amounts.values()) != source_amount:
            raise ValueError("Manual amounts must total exactly to source amount.")
        if source_amount == ZERO:
            return [
                {
                    "project": project,
                    "weight": ZERO,
                    "manual_override": True,
                    "manual_amount": amounts[project.id],
                    "notes": "Generated from manual amount seed.",
                }
                for project in projects
            ]
        return [
            {
                "project": project,
                "weight": amounts[project.id] / source_amount,
                "manual_override": True,
                "manual_amount": amounts[project.id],
                "notes": "Generated from manual amount seed.",
            }
            for project in projects
        ]

    @staticmethod
    def _validate_project_manager(project_manager_id, projects):
        if not project_manager_id:
            raise ValueError("Project manager allocation requires project_manager_id.")
        try:
            manager = ProjectParty.objects.get(
                id=project_manager_id,
                role=ProjectParty.Role.PROJECT_MANAGER,
                is_active=True,
            )
        except ProjectParty.DoesNotExist as exc:
            raise ValueError("Project manager allocation requires an active project manager relation.") from exc
        relation_filter = {
            "organization": manager.organization,
            "role": ProjectParty.Role.PROJECT_MANAGER,
            "is_active": True,
        }
        if manager.email:
            relation_filter["email"] = manager.email
        else:
            relation_filter["name"] = manager.name
        managed_project_ids = set(
            ProjectParty.objects.filter(**relation_filter).values_list("project_id", flat=True)
        )
        project_ids = {project.id for project in projects}
        if not project_ids.issubset(managed_project_ids):
            raise ValueError("Selected projects must be related to the selected project manager.")

    @staticmethod
    def _balanced_entries(projects, weights, source_amount):
        payloads = []
        allocated = ZERO
        percentage_total = ZERO
        manual_amount_mode = any("manual_amount" in item for item in weights)
        for index, item in enumerate(weights):
            if manual_amount_mode:
                amount = item.get("manual_amount", ZERO).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
            else:
                amount = (source_amount * item["weight"]).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
            if source_amount == ZERO:
                percentage = ZERO if manual_amount_mode else (item["weight"] * ONE_HUNDRED).quantize(PERCENT_QUANT)
            else:
                percentage = (item["weight"] * ONE_HUNDRED).quantize(PERCENT_QUANT)
            payloads.append(
                {
                    "project": item["project"],
                    "amount": amount,
                    "percentage": percentage,
                    "manual_override": item["manual_override"],
                    "notes": item["notes"],
                }
            )
            allocated += amount
            percentage_total += percentage
        if payloads:
            amount_remainder = source_amount - allocated
            percentage_remainder = (ONE_HUNDRED - percentage_total) if source_amount != ZERO else ZERO
            payloads[-1]["amount"] += amount_remainder
            payloads[-1]["percentage"] += percentage_remainder
        return payloads, {
            "amount_remainder_project_id": payloads[-1]["project"].id if payloads else None,
            "currency_precision": str(CURRENCY_QUANT),
            "percentage_precision": str(PERCENT_QUANT),
        }

    @staticmethod
    def _next_version_number(period, pool):
        list(ManagementAllocationVersion.objects.select_for_update().filter(period=period, pool=pool))
        latest = (
            ManagementAllocationVersion.objects.filter(period=period, pool=pool)
            .aggregate(max_version=Max("version_number"))
            .get("max_version")
            or 0
        )
        return latest + 1
