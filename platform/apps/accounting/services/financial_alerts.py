import calendar
import hashlib
import json
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Min
from django.utils import timezone

from apps.accounting.models import (
    AccountingGLAllocation,
    FinancialAlert,
    FinancialAlertBasis,
    FinancialAlertCandidateScope,
    FinancialAlertEvaluationRun,
    FinancialAlertEvaluationRunStatus,
    FinancialAlertRule,
    FinancialAlertSeverity,
    FinancialAlertStatus,
    FinancialAlertType,
)
from apps.core.services import AuditService
from apps.projects.models import Project

from .commands import (
    AcknowledgeFinancialAlertCommand,
    AggregateProjectFinancialsCommand,
    BuildManagementFinancialsCommand,
    DismissFinancialAlertCommand,
    EvaluateFinancialAlertsCommand,
    FinancialAlertActionResult,
    FinancialAlertEvaluationResult,
    FinancialAlertFact,
)
from .financial_aggregation import ProjectFinancialAggregationService
from .management_financials import ProjectManagementFinancialService


ZERO = Decimal("0")
FINGERPRINT_VERSION = 1


class FinancialAlertFingerprintService:
    @classmethod
    def build_lifetime_negative(cls, *, organization, project, basis, rule=None):
        return cls.build(
            organization=organization,
            project=project,
            alert_type=FinancialAlertType.PROJECT_LIFETIME_NEGATIVE,
            basis=basis,
            rule=rule,
            period_key="lifetime",
        )

    @classmethod
    def build_current_month_negative(cls, *, organization, project, basis, evaluation_date, rule=None):
        return cls.build(
            organization=organization,
            project=project,
            alert_type=FinancialAlertType.PROJECT_CURRENT_MONTH_NEGATIVE,
            basis=basis,
            rule=rule,
            period_key=cls._month_key(evaluation_date),
        )

    @classmethod
    def build_current_month_no_revenue(cls, *, organization, project, evaluation_date, rule=None):
        return cls.build(
            organization=organization,
            project=project,
            alert_type=FinancialAlertType.PROJECT_CURRENT_MONTH_NO_REVENUE,
            basis=FinancialAlertBasis.ACCOUNTING,
            rule=rule,
            period_key=cls._month_key(evaluation_date),
        )

    @staticmethod
    def build(*, organization, project, alert_type, basis, rule=None, period_key=""):
        payload = {
            "alert_type": str(alert_type),
            "basis": str(basis),
            "fingerprint_version": FINGERPRINT_VERSION,
            "organization_id": organization.id,
            "period_key": str(period_key or ""),
            "project_id": project.id,
            "rule_identity": f"rule:{rule.id}" if rule and rule.id else "rule:default",
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _month_key(value):
        value = FinancialAlertFactBuilder.coerce_date(value, "evaluation_date")
        return f"{value.year:04d}-{value.month:02d}"


class FinancialAlertRuleService:
    DEFAULTS = [
        {
            "alert_type": FinancialAlertType.PROJECT_LIFETIME_NEGATIVE,
            "name": "Project lifetime result is negative",
            "financial_basis": FinancialAlertBasis.MANAGEMENT,
            "severity": FinancialAlertSeverity.CRITICAL,
            "threshold_amount": ZERO,
            "candidate_scope": FinancialAlertCandidateScope.ALL_WITH_ACTIVITY,
        },
        {
            "alert_type": FinancialAlertType.PROJECT_CURRENT_MONTH_NEGATIVE,
            "name": "Project current-month result is negative",
            "financial_basis": FinancialAlertBasis.MANAGEMENT,
            "severity": FinancialAlertSeverity.WARNING,
            "threshold_amount": ZERO,
            "candidate_scope": FinancialAlertCandidateScope.ACTIVE_PROJECTS_WITH_MONTH_ACTIVITY,
        },
        {
            "alert_type": FinancialAlertType.PROJECT_CURRENT_MONTH_NO_REVENUE,
            "name": "No project revenue recorded for current month",
            "financial_basis": FinancialAlertBasis.ACCOUNTING,
            "severity": FinancialAlertSeverity.WARNING,
            "threshold_amount": ZERO,
            "candidate_scope": FinancialAlertCandidateScope.ACTIVE_PROJECTS_WITH_MONTH_ACTIVITY,
        },
    ]

    @classmethod
    def get_applicable_rules(cls, organization, alert_types=None):
        queryset = FinancialAlertRule.objects.filter(organization=organization, is_active=True)
        if alert_types:
            queryset = queryset.filter(alert_type__in=alert_types)
        return list(queryset.order_by("alert_type", "id"))

    @staticmethod
    def validate_rule(rule):
        rule.full_clean()
        return rule

    @classmethod
    def create_default_rules(cls, organization, actor=None):
        rules = []
        for defaults in cls.DEFAULTS:
            rule = FinancialAlertRule.objects.filter(
                organization=organization,
                alert_type=defaults["alert_type"],
            ).first()
            if not rule:
                rule = FinancialAlertRule.objects.create(organization=organization, **defaults)
            rules.append(rule)
        if actor:
            AuditService.record(
                organization=organization,
                actor=actor,
                event_type="financial_alert_default_rules_created",
                object_type="Organization",
                object_id=str(organization.id),
                metadata={"rule_count": len(rules)},
            )
        return rules


class FinancialAlertCandidateService:
    @classmethod
    def select_candidates(cls, *, organization, rule, evaluation_date, project_ids=None):
        projects = Project.objects.filter(organization=organization)
        if rule.candidate_scope == FinancialAlertCandidateScope.SELECTED_PROJECTS and not project_ids:
            return []
        if project_ids:
            projects = projects.filter(id__in=project_ids)

        if rule.project_status_scope:
            projects = projects.filter(status__in=rule.project_status_scope)
        elif rule.candidate_scope in {
            FinancialAlertCandidateScope.ACTIVE_PROJECTS,
            FinancialAlertCandidateScope.ACTIVE_PROJECTS_WITH_MONTH_ACTIVITY,
        }:
            projects = projects.filter(status=Project.Status.ACTIVE)

        if rule.candidate_scope == FinancialAlertCandidateScope.SELECTED_PROJECTS:
            return list(projects.order_by("code", "id"))

        if rule.candidate_scope == FinancialAlertCandidateScope.ACTIVE_PROJECTS:
            return list(projects.order_by("code", "id"))

        if rule.candidate_scope == FinancialAlertCandidateScope.ACTIVE_PROJECTS_WITH_MONTH_ACTIVITY:
            start, end = FinancialAlertFactBuilder.month_bounds(evaluation_date)
            active_ids = cls._project_ids_with_activity(organization, start, end)
            return list(projects.filter(id__in=active_ids).order_by("code", "id"))

        if rule.candidate_scope == FinancialAlertCandidateScope.ALL_WITH_ACTIVITY:
            active_ids = cls._project_ids_with_activity(organization, None, None)
            return list(projects.filter(id__in=active_ids).order_by("code", "id"))

        return list(projects.order_by("code", "id"))

    @staticmethod
    def _project_ids_with_activity(organization, period_start, period_end):
        allocations = AccountingGLAllocation.objects.filter(
            organization=organization,
            project__isnull=False,
            entry__batch__batch_date__isnull=False,
        )
        if period_start and period_end:
            allocations = allocations.filter(entry__batch__batch_date__gte=period_start, entry__batch__batch_date__lte=period_end)
        return allocations.values_list("project_id", flat=True).distinct()


class FinancialAlertFactBuilder:
    def __init__(self, aggregation_service=None, management_service=None):
        self.aggregation_service = aggregation_service or ProjectFinancialAggregationService()
        self.management_service = management_service or ProjectManagementFinancialService

    def build_fact(self, *, project, rule, evaluation_date):
        if rule.alert_type == FinancialAlertType.PROJECT_LIFETIME_NEGATIVE:
            return self.build_lifetime_negative_fact(project=project, rule=rule, evaluation_date=evaluation_date)
        if rule.alert_type == FinancialAlertType.PROJECT_CURRENT_MONTH_NEGATIVE:
            return self.build_current_month_negative_fact(project=project, rule=rule, evaluation_date=evaluation_date)
        if rule.alert_type == FinancialAlertType.PROJECT_CURRENT_MONTH_NO_REVENUE:
            return self.build_current_month_no_revenue_fact(project=project, rule=rule, evaluation_date=evaluation_date)
        raise ValueError(f"Unsupported financial alert type: {rule.alert_type}")

    def build_lifetime_negative_fact(self, *, project, rule, evaluation_date):
        evaluation_date = self.coerce_date(evaluation_date, "evaluation_date")
        period_start = self._lifetime_start(project, evaluation_date)
        accounting = self._aggregate(project, rule, period_start, evaluation_date)
        return self._negative_fact(project, rule, accounting, period_start, evaluation_date, lifetime=True)

    def build_current_month_negative_fact(self, *, project, rule, evaluation_date):
        evaluation_date = self.coerce_date(evaluation_date, "evaluation_date")
        period_start, period_end = self.month_bounds(evaluation_date)
        period_end = min(period_end, evaluation_date)
        warnings = []
        if rule.grace_day and evaluation_date.day < rule.grace_day:
            warnings.append(f"grace_day_active:{rule.grace_day}")
            return self._skipped_fact(project, rule, period_start, period_end, warnings)
        accounting = self._aggregate(project, rule, period_start, period_end)
        fact = self._negative_fact(project, rule, accounting, period_start, period_end, lifetime=False)
        metadata = dict(fact.metadata)
        metadata.update(
            {
                "is_partial_month": period_end.day < calendar.monthrange(period_end.year, period_end.month)[1],
                "evaluation_day": evaluation_date.day,
                "month_end": self.month_bounds(evaluation_date)[1].isoformat(),
            }
        )
        return self._replace_fact(fact, metadata=metadata)

    def build_current_month_no_revenue_fact(self, *, project, rule, evaluation_date):
        evaluation_date = self.coerce_date(evaluation_date, "evaluation_date")
        period_start, period_end = self.month_bounds(evaluation_date)
        period_end = min(period_end, evaluation_date)
        accounting = self._aggregate(project, rule, period_start, period_end)
        threshold = self._threshold(rule)
        warnings = list(accounting.warnings)
        if accounting.data_quality_status == "mixed_currency":
            warnings.append("skipped_mixed_currency")
            return self._skipped_fact(project, rule, period_start, period_end, warnings, accounting=accounting)
        has_activity = (
            accounting.total_cost != ZERO
            or accounting.allocation_count > 0
            or accounting.unclassified_amount != ZERO
        )
        if not has_activity:
            warnings.append("skipped_no_current_month_activity")
            return self._skipped_fact(project, rule, period_start, period_end, warnings, accounting=accounting)

        condition_met = accounting.revenue == ZERO
        month_label = f"{period_start:%B %Y}"
        return FinancialAlertFact(
            project=project,
            alert_type=rule.alert_type,
            basis=FinancialAlertBasis.ACCOUNTING,
            period_start=period_start,
            period_end=period_end,
            currency=accounting.currency,
            accounting_amount=accounting.revenue,
            management_amount=None,
            evaluated_amount=accounting.revenue,
            threshold_amount=threshold,
            condition_met=condition_met,
            title=f"No project revenue recorded for {month_label}",
            message=(
                f"Project {project.code} has no trusted project revenue recorded for {month_label}. "
                "This does not prove that no sales invoice was issued."
            ),
            severity=rule.severity,
            data_quality_status=accounting.data_quality_status,
            warnings=warnings,
            metadata={
                "accounting_result": str(accounting.result),
                "activity_allocation_count": accounting.allocation_count,
                "activity_total_cost": str(accounting.total_cost),
                "activity_unclassified_amount": str(accounting.unclassified_amount),
                "wording_limitation": "This alert means no trusted project revenue is recorded; it does not prove invoice status.",
            },
        )

    def _negative_fact(self, project, rule, accounting, period_start, period_end, *, lifetime):
        warnings = list(accounting.warnings)
        if accounting.data_quality_status == "mixed_currency":
            warnings.append("skipped_mixed_currency")
            return self._skipped_fact(project, rule, period_start, period_end, warnings, accounting=accounting)
        if accounting.data_quality_status == "no_data":
            warnings.append("skipped_no_data")
            return self._skipped_fact(project, rule, period_start, period_end, warnings, accounting=accounting)

        management = self.management_service.build(BuildManagementFinancialsCommand(accounting_result=accounting))
        threshold = self._threshold(rule)
        evaluated = management.management_result if rule.financial_basis == FinancialAlertBasis.MANAGEMENT else accounting.result
        title = "Project lifetime result is negative" if lifetime else "Project current-month result is negative"
        basis_label = "management" if rule.financial_basis == FinancialAlertBasis.MANAGEMENT else "accounting"
        message = f"Project {project.code} has a {basis_label} result of {evaluated} {accounting.currency}."
        return FinancialAlertFact(
            project=project,
            alert_type=rule.alert_type,
            basis=rule.financial_basis,
            period_start=period_start,
            period_end=period_end,
            currency=accounting.currency,
            accounting_amount=accounting.result,
            management_amount=management.management_result,
            evaluated_amount=evaluated,
            threshold_amount=threshold,
            condition_met=evaluated < threshold,
            title=title,
            message=message,
            severity=rule.severity,
            data_quality_status=accounting.data_quality_status,
            warnings=warnings + list(management.warnings),
            metadata={
                "accounting_revenue": str(accounting.revenue),
                "accounting_total_cost": str(accounting.total_cost),
                "management_total_cost": str(management.management_total_cost),
                "allocation_count": accounting.allocation_count,
            },
        )

    def _aggregate(self, project, rule, period_start, period_end):
        return self.aggregation_service.aggregate(
            AggregateProjectFinancialsCommand(
                project=project,
                period_start=period_start,
                period_end=period_end,
                currency=rule.currency or None,
                metadata={"source": "financial_alert_fact_builder", "alert_type": rule.alert_type},
            )
        )

    @staticmethod
    def _threshold(rule):
        return rule.threshold_amount if rule.threshold_amount is not None else ZERO

    @staticmethod
    def _skipped_fact(project, rule, period_start, period_end, warnings, accounting=None):
        return FinancialAlertFact(
            project=project,
            alert_type=rule.alert_type,
            basis=rule.financial_basis,
            period_start=period_start,
            period_end=period_end,
            currency=accounting.currency if accounting else rule.currency,
            accounting_amount=accounting.result if accounting else None,
            management_amount=None,
            evaluated_amount=None,
            threshold_amount=rule.threshold_amount,
            condition_met=False,
            title="Financial alert evaluation skipped",
            message=f"Project {project.code} financial alert evaluation was skipped.",
            severity=rule.severity,
            data_quality_status=accounting.data_quality_status if accounting else "",
            warnings=list(warnings),
            metadata={"skipped": True},
        )

    @staticmethod
    def _replace_fact(fact, **changes):
        data = {
            "project": fact.project,
            "alert_type": fact.alert_type,
            "basis": fact.basis,
            "period_start": fact.period_start,
            "period_end": fact.period_end,
            "currency": fact.currency,
            "accounting_amount": fact.accounting_amount,
            "management_amount": fact.management_amount,
            "evaluated_amount": fact.evaluated_amount,
            "threshold_amount": fact.threshold_amount,
            "condition_met": fact.condition_met,
            "title": fact.title,
            "message": fact.message,
            "severity": fact.severity,
            "data_quality_status": fact.data_quality_status,
            "warnings": fact.warnings,
            "metadata": fact.metadata,
        }
        data.update(changes)
        return FinancialAlertFact(**data)

    @staticmethod
    def _lifetime_start(project, evaluation_date):
        earliest = AccountingGLAllocation.objects.filter(
            project=project,
            organization=project.organization,
            entry__batch__batch_date__isnull=False,
        ).aggregate(value=Min("entry__batch__batch_date"))["value"]
        if earliest:
            return earliest
        if project.start_date:
            return project.start_date
        if project.created_at:
            return project.created_at.date()
        return evaluation_date

    @staticmethod
    def month_bounds(value):
        value = FinancialAlertFactBuilder.coerce_date(value, "evaluation_date")
        return date(value.year, value.month, 1), date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])

    @staticmethod
    def coerce_date(value, field_name):
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


class FinancialAlertLifecycleService:
    def __init__(self, fingerprint_service=None):
        self.fingerprint_service = fingerprint_service or FinancialAlertFingerprintService

    def transition(self, *, fact, rule, evaluation_time, dry_run=False):
        fingerprint = self._fingerprint(fact, rule)
        existing = FinancialAlert.objects.filter(organization=fact.project.organization, fingerprint=fingerprint).first()
        if fact.metadata.get("skipped"):
            return "skipped", existing
        if dry_run:
            if fact.condition_met and not existing:
                return "opened", None
            if fact.condition_met and existing and existing.status == FinancialAlertStatus.RESOLVED:
                return "reopened", existing
            if not fact.condition_met and existing and existing.status in {FinancialAlertStatus.OPEN, FinancialAlertStatus.ACKNOWLEDGED}:
                return "resolved", existing
            return "unchanged", existing

        with transaction.atomic():
            if fact.condition_met:
                return self._open_update_or_reopen(fact, rule, fingerprint, existing, evaluation_time)
            if existing and existing.status in {FinancialAlertStatus.OPEN, FinancialAlertStatus.ACKNOWLEDGED}:
                return self._resolve(existing, fact, evaluation_time)
            if existing:
                existing.last_evaluated_at = evaluation_time
                existing.save(update_fields=["last_evaluated_at", "updated_at"])
            return "unchanged", existing

    def _open_update_or_reopen(self, fact, rule, fingerprint, existing, evaluation_time):
        values = self._alert_values(fact, rule, evaluation_time)
        if not existing:
            alert = FinancialAlert.objects.create(fingerprint=fingerprint, **values)
            self._audit("financial_alert_opened", alert)
            return "opened", alert
        if existing.status == FinancialAlertStatus.DISMISSED:
            existing.last_evaluated_at = evaluation_time
            existing.last_detected_at = evaluation_time
            existing.metadata = self._metadata(fact)
            existing.save(update_fields=["last_evaluated_at", "last_detected_at", "metadata", "updated_at"])
            return "unchanged", existing
        if existing.status == FinancialAlertStatus.RESOLVED:
            for field, value in values.items():
                if field not in {"organization", "project", "first_detected_at"}:
                    setattr(existing, field, value)
            existing.status = FinancialAlertStatus.OPEN
            existing.resolved_at = None
            existing.resolution_reason = ""
            existing.save()
            self._audit("financial_alert_reopened", existing)
            return "reopened", existing

        changed = self._apply_refresh(existing, values)
        existing.last_detected_at = evaluation_time
        existing.last_evaluated_at = evaluation_time
        existing.save()
        return ("updated" if changed else "unchanged"), existing

    def _resolve(self, alert, fact, evaluation_time):
        alert.status = FinancialAlertStatus.RESOLVED
        alert.resolved_at = evaluation_time
        alert.last_evaluated_at = evaluation_time
        alert.resolution_reason = "condition_cleared"
        alert.metadata = self._metadata(fact)
        alert.save()
        self._audit("financial_alert_resolved", alert)
        return "resolved", alert

    def _fingerprint(self, fact, rule):
        if fact.alert_type == FinancialAlertType.PROJECT_LIFETIME_NEGATIVE:
            return self.fingerprint_service.build_lifetime_negative(
                organization=fact.project.organization,
                project=fact.project,
                basis=fact.basis,
                rule=rule,
            )
        if fact.alert_type == FinancialAlertType.PROJECT_CURRENT_MONTH_NEGATIVE:
            return self.fingerprint_service.build_current_month_negative(
                organization=fact.project.organization,
                project=fact.project,
                basis=fact.basis,
                evaluation_date=fact.period_start,
                rule=rule,
            )
        return self.fingerprint_service.build_current_month_no_revenue(
            organization=fact.project.organization,
            project=fact.project,
            evaluation_date=fact.period_start,
            rule=rule,
        )

    @staticmethod
    def _alert_values(fact, rule, evaluation_time):
        return {
            "organization": fact.project.organization,
            "project": fact.project,
            "rule": rule,
            "alert_type": fact.alert_type,
            "financial_basis": fact.basis,
            "severity": fact.severity,
            "status": FinancialAlertStatus.OPEN,
            "fingerprint_version": FINGERPRINT_VERSION,
            "title": fact.title,
            "message": fact.message,
            "period_start": fact.period_start,
            "period_end": fact.period_end,
            "currency": fact.currency or "",
            "accounting_amount": fact.accounting_amount,
            "management_amount": fact.management_amount,
            "evaluated_amount": fact.evaluated_amount,
            "threshold_amount": fact.threshold_amount,
            "data_quality_status": fact.data_quality_status or "",
            "first_detected_at": evaluation_time,
            "last_detected_at": evaluation_time,
            "last_evaluated_at": evaluation_time,
            "metadata": FinancialAlertLifecycleService._metadata(fact),
        }

    @staticmethod
    def _metadata(fact):
        metadata = deepcopy(fact.metadata or {})
        metadata["warnings"] = list(fact.warnings)
        return metadata

    @staticmethod
    def _apply_refresh(alert, values):
        changed = False
        fields = [
            "severity",
            "title",
            "message",
            "period_start",
            "period_end",
            "currency",
            "accounting_amount",
            "management_amount",
            "evaluated_amount",
            "threshold_amount",
            "data_quality_status",
            "metadata",
        ]
        for field in fields:
            value = values[field]
            if getattr(alert, field) != value:
                setattr(alert, field, value)
                changed = True
        return changed

    @staticmethod
    def _audit(event_type, alert):
        AuditService.record(
            organization=alert.organization,
            event_type=event_type,
            object_type="FinancialAlert",
            object_id=str(alert.id),
            message=alert.title,
            metadata={
                "alert_type": alert.alert_type,
                "project_id": alert.project_id,
                "status": alert.status,
            },
        )


class FinancialAlertEvaluationService:
    def __init__(
        self,
        rule_service=None,
        candidate_service=None,
        fact_builder=None,
        lifecycle_service=None,
    ):
        self.rule_service = rule_service or FinancialAlertRuleService
        self.candidate_service = candidate_service or FinancialAlertCandidateService
        self.fact_builder = fact_builder or FinancialAlertFactBuilder()
        self.lifecycle_service = lifecycle_service or FinancialAlertLifecycleService()

    def evaluate(self, command: EvaluateFinancialAlertsCommand) -> FinancialAlertEvaluationResult:
        metadata = deepcopy(command.metadata or {})
        evaluation_date = FinancialAlertFactBuilder.coerce_date(command.evaluation_date, "evaluation_date")
        alert_types = list(command.alert_types or [])
        rules = self.rule_service.get_applicable_rules(command.organization, alert_types=alert_types or None)
        evaluation_run = None
        if not command.dry_run:
            evaluation_run = FinancialAlertEvaluationRun.objects.create(
                organization=command.organization,
                evaluation_date=evaluation_date,
                requested_project_count=len(command.project_ids or []),
                evaluated_rule_count=len(rules),
                metadata=metadata,
            )

        counters = {
            "opened": 0,
            "updated": 0,
            "reopened": 0,
            "resolved": 0,
            "unchanged": 0,
            "skipped": 0,
            "failed": 0,
        }
        warnings = []
        alert_ids = []
        evaluated_project_ids = set()
        successful = 0

        for rule in rules:
            candidates = self.candidate_service.select_candidates(
                organization=command.organization,
                rule=rule,
                evaluation_date=evaluation_date,
                project_ids=command.project_ids,
            )
            for project in candidates:
                try:
                    fact = self.fact_builder.build_fact(project=project, rule=rule, evaluation_date=evaluation_date)
                    transition, alert = self.lifecycle_service.transition(
                        fact=fact,
                        rule=rule,
                        evaluation_time=timezone.now(),
                        dry_run=command.dry_run,
                    )
                    counters[transition] += 1
                    warnings.extend(fact.warnings)
                    if alert:
                        alert_ids.append(alert.id)
                    evaluated_project_ids.add(project.id)
                    successful += 1
                except Exception as exc:
                    counters["failed"] += 1
                    warnings.append(self._safe_error(exc))

        status = self._run_status(successful, counters["failed"])
        if evaluation_run:
            evaluation_run.status = status
            evaluation_run.completed_at = timezone.now()
            evaluation_run.evaluated_project_count = len(evaluated_project_ids)
            evaluation_run.opened_count = counters["opened"]
            evaluation_run.updated_count = counters["updated"]
            evaluation_run.reopened_count = counters["reopened"]
            evaluation_run.resolved_count = counters["resolved"]
            evaluation_run.unchanged_count = counters["unchanged"]
            evaluation_run.skipped_count = counters["skipped"]
            evaluation_run.failed_count = counters["failed"]
            evaluation_run.safe_error = "; ".join(warnings[:3]) if counters["failed"] else ""
            evaluation_run.save()

        return FinancialAlertEvaluationResult(
            evaluation_run=evaluation_run,
            evaluated_projects=len(evaluated_project_ids),
            evaluated_rules=len(rules),
            opened_count=counters["opened"],
            updated_count=counters["updated"],
            reopened_count=counters["reopened"],
            resolved_count=counters["resolved"],
            unchanged_count=counters["unchanged"],
            skipped_count=counters["skipped"],
            failed_count=counters["failed"],
            warnings=warnings,
            alert_ids=sorted(set(alert_ids)),
            dry_run=command.dry_run,
            metadata=metadata,
        )

    @staticmethod
    def _run_status(successful, failed):
        if failed and successful:
            return FinancialAlertEvaluationRunStatus.PARTIAL
        if failed:
            return FinancialAlertEvaluationRunStatus.FAILED
        return FinancialAlertEvaluationRunStatus.COMPLETED

    @staticmethod
    def _safe_error(exc):
        return f"{exc.__class__.__name__}: {str(exc)[:200]}"


class FinancialAlertActionService:
    """Controlled user lifecycle actions for persisted financial alerts.

    This service does not evaluate alerts, call Merit, or recalculate project
    financials. It only records explicit human review decisions against already
    persisted alert rows.
    """

    @classmethod
    @transaction.atomic
    def acknowledge(cls, command: AcknowledgeFinancialAlertCommand) -> FinancialAlertActionResult:
        metadata = deepcopy(command.metadata or {})
        alert = FinancialAlert.objects.select_for_update().get(pk=command.alert.pk)
        previous_status = alert.status

        if alert.status == FinancialAlertStatus.ACKNOWLEDGED:
            return FinancialAlertActionResult(
                alert=alert,
                previous_status=previous_status,
                new_status=alert.status,
                changed=False,
                message="Financial alert was already acknowledged.",
                metadata=metadata,
            )
        if alert.status != FinancialAlertStatus.OPEN:
            raise ValueError("Only open financial alerts can be acknowledged.")

        alert.status = FinancialAlertStatus.ACKNOWLEDGED
        alert.acknowledged_at = timezone.now()
        alert.acknowledged_by = command.actor
        alert.save(update_fields=["status", "acknowledged_at", "acknowledged_by", "updated_at"])

        cls._audit(
            alert=alert,
            actor=command.actor,
            event_type="financial_alert_acknowledged",
            message="Financial alert acknowledged.",
            metadata={**metadata, "previous_status": previous_status, "new_status": alert.status},
        )
        return FinancialAlertActionResult(
            alert=alert,
            previous_status=previous_status,
            new_status=alert.status,
            changed=True,
            message="Financial alert acknowledged.",
            metadata=metadata,
        )

    @classmethod
    @transaction.atomic
    def dismiss(cls, command: DismissFinancialAlertCommand) -> FinancialAlertActionResult:
        reason = (command.reason or "").strip()
        if not reason:
            raise ValueError("Dismissal reason is required.")

        metadata = deepcopy(command.metadata or {})
        alert = FinancialAlert.objects.select_for_update().get(pk=command.alert.pk)
        previous_status = alert.status

        if alert.status == FinancialAlertStatus.DISMISSED:
            return FinancialAlertActionResult(
                alert=alert,
                previous_status=previous_status,
                new_status=alert.status,
                changed=False,
                message="Financial alert was already dismissed.",
                metadata=metadata,
            )
        if alert.status not in {FinancialAlertStatus.OPEN, FinancialAlertStatus.ACKNOWLEDGED}:
            raise ValueError("Only open or acknowledged financial alerts can be dismissed.")

        alert.status = FinancialAlertStatus.DISMISSED
        alert.dismissed_at = timezone.now()
        alert.dismissed_by = command.actor
        alert.resolution_reason = reason[:255]
        alert.save(update_fields=["status", "dismissed_at", "dismissed_by", "resolution_reason", "updated_at"])

        cls._audit(
            alert=alert,
            actor=command.actor,
            event_type="financial_alert_dismissed",
            message="Financial alert dismissed.",
            metadata={
                **metadata,
                "previous_status": previous_status,
                "new_status": alert.status,
                "reason": alert.resolution_reason,
            },
        )
        return FinancialAlertActionResult(
            alert=alert,
            previous_status=previous_status,
            new_status=alert.status,
            changed=True,
            message="Financial alert dismissed.",
            metadata=metadata,
        )

    @staticmethod
    def _audit(*, alert, actor, event_type, message, metadata):
        AuditService.record(
            event_type=event_type,
            message=message,
            organization=alert.organization,
            actor=actor,
            object_type="FinancialAlert",
            object_id=str(alert.id),
            metadata={
                **metadata,
                "alert_id": alert.id,
                "project_id": alert.project_id,
                "project_code": alert.project.code,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
            },
        )
