from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.accounting.services import AggregateProjectFinancialsCommand, ProjectFinancialAggregationService
from apps.projects.models import Project


class Command(BaseCommand):
    help = "Print a read-only project financial summary from the local GL cache."

    def add_arguments(self, parser):
        parser.add_argument("project_id", type=int)
        parser.add_argument("--start", required=True)
        parser.add_argument("--end", required=True)
        parser.add_argument("--currency")
        parser.add_argument("--exclude-overhead", action="store_true")
        parser.add_argument("--show-unclassified", action="store_true")
        parser.add_argument("--debug", action="store_true")

    def handle(self, *args, **options):
        try:
            project = Project.objects.get(id=options["project_id"])
        except Project.DoesNotExist as exc:
            raise CommandError(f"Project not found: {options['project_id']}") from exc

        try:
            period_start = date.fromisoformat(options["start"])
            period_end = date.fromisoformat(options["end"])
        except ValueError as exc:
            raise CommandError("Dates must use YYYY-MM-DD format.") from exc

        try:
            result = ProjectFinancialAggregationService().aggregate(
                AggregateProjectFinancialsCommand(
                    project=project,
                    period_start=period_start,
                    period_end=period_end,
                    currency=options["currency"],
                    include_overhead=not options["exclude_overhead"],
                    metadata={"source": "project_financial_summary_command"},
                )
            )
        except Exception as exc:
            if options["debug"]:
                raise CommandError(f"Project financial summary failed: {exc.__class__.__name__}: {exc}") from exc
            raise CommandError("Project financial summary failed. Check period and local GL cache data.") from exc

        self.stdout.write(f"project: {project.code} {project.name}")
        self.stdout.write(f"period_start: {result.period_start}")
        self.stdout.write(f"period_end: {result.period_end}")
        self.stdout.write(f"currency: {result.currency or 'not_available'}")
        self.stdout.write("months:")
        for month in result.months:
            self.stdout.write(
                f"  {month.year}-{month.month:02d}: revenue={month.revenue} "
                f"cost={month.total_cost} result={month.result} margin={month.margin}"
            )
        self.stdout.write("period_totals:")
        self.stdout.write(f"  revenue: {result.revenue}")
        self.stdout.write(f"  total_cost: {result.total_cost}")
        self.stdout.write(f"  result: {result.result}")
        self.stdout.write(f"  margin: {result.margin}")
        self.stdout.write(f"  unclassified_amount: {result.unclassified_amount}")
        self.stdout.write(f"  unclassified_allocation_count: {result.unclassified_allocation_count}")
        self.stdout.write("source_counts:")
        self.stdout.write(f"  batches: {result.source_batch_count}")
        self.stdout.write(f"  entries: {result.source_entry_count}")
        self.stdout.write(f"  allocations: {result.allocation_count}")
        self.stdout.write(f"data_quality_status: {result.data_quality_status}")
        if result.warnings:
            self.stdout.write("warnings:")
            for warning in result.warnings:
                self.stdout.write(f"  {warning}")
        if options["show_unclassified"]:
            self.stdout.write("unclassified:")
            self.stdout.write(f"  amount: {result.unclassified_amount}")
            self.stdout.write(f"  count: {result.unclassified_allocation_count}")
