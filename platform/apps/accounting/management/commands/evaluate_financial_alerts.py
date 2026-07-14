from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounting.models import FinancialAlertType
from apps.accounting.services import EvaluateFinancialAlertsCommand, FinancialAlertEvaluationService
from apps.core.models import Organization
from apps.projects.models import Project


class Command(BaseCommand):
    help = "Evaluate persisted project financial alerts."

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True, type=int)
        parser.add_argument("--date")
        parser.add_argument("--project", action="append", type=int, default=[])
        parser.add_argument("--alert-type", action="append", choices=[choice[0] for choice in FinancialAlertType.choices], default=[])
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--debug", action="store_true")

    def handle(self, *args, **options):
        debug = options["debug"]
        try:
            organization = Organization.objects.get(id=options["organization"])
        except Organization.DoesNotExist as exc:
            raise CommandError(f"Organization not found: {options['organization']}") from exc

        evaluation_date = timezone.localdate()
        if options["date"]:
            try:
                evaluation_date = date.fromisoformat(options["date"])
            except ValueError as exc:
                raise CommandError("Date must use YYYY-MM-DD format.") from exc

        project_ids = options["project"] or None
        if project_ids:
            found = set(Project.objects.filter(organization=organization, id__in=project_ids).values_list("id", flat=True))
            missing = sorted(set(project_ids) - found)
            if missing:
                raise CommandError(f"Project not found for organization: {missing[0]}")

        try:
            result = FinancialAlertEvaluationService().evaluate(
                EvaluateFinancialAlertsCommand(
                    organization=organization,
                    evaluation_date=evaluation_date,
                    project_ids=project_ids,
                    alert_types=options["alert_type"] or None,
                    dry_run=options["dry_run"],
                    metadata={"source": "evaluate_financial_alerts_command"},
                )
            )
        except Exception as exc:
            raise CommandError(self._safe_error("Financial alert evaluation failed", exc, debug=debug)) from exc

        self.stdout.write(f"organization_id: {organization.id}")
        self.stdout.write(f"evaluation_date: {evaluation_date}")
        self.stdout.write(f"dry_run: {result.dry_run}")
        self.stdout.write(f"projects: {result.evaluated_projects}")
        self.stdout.write(f"rules: {result.evaluated_rules}")
        self.stdout.write(f"opened: {result.opened_count}")
        self.stdout.write(f"updated: {result.updated_count}")
        self.stdout.write(f"reopened: {result.reopened_count}")
        self.stdout.write(f"resolved: {result.resolved_count}")
        self.stdout.write(f"unchanged: {result.unchanged_count}")
        self.stdout.write(f"skipped: {result.skipped_count}")
        self.stdout.write(f"failed: {result.failed_count}")

    @staticmethod
    def _safe_error(prefix, exc, *, debug=False):
        if not debug:
            return f"{prefix}. Check financial alert configuration and try again."
        return f"{prefix}: {exc.__class__.__name__}: {exc}"
