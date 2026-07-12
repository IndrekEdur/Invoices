from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.accounting.models import AccountingIntegration
from apps.accounting.services import GeneralLedgerSyncService, SyncGeneralLedgerCommand


class Command(BaseCommand):
    help = "Synchronize Merit general-ledger data for a bounded date range."

    def add_arguments(self, parser):
        parser.add_argument("integration_id", type=int)
        parser.add_argument("--start", required=True)
        parser.add_argument("--end", required=True)
        parser.add_argument(
            "--mode",
            default="manual",
            choices=["manual", "incremental", "initial_backfill", "period_resync", "other"],
        )
        parser.add_argument("--date-type", default="document_date", choices=["document_date", "changed_date"])
        parser.add_argument("--without-lines", action="store_true")
        parser.add_argument("--without-cost-allocations", action="store_true")
        parser.add_argument("--debug", action="store_true")

    def handle(self, *args, **options):
        integration_id = options["integration_id"]
        debug = options["debug"]

        try:
            integration = AccountingIntegration.objects.get(id=integration_id)
        except AccountingIntegration.DoesNotExist as exc:
            raise CommandError(f"AccountingIntegration not found: {integration_id}") from exc

        try:
            period_start = date.fromisoformat(options["start"])
            period_end = date.fromisoformat(options["end"])
        except ValueError as exc:
            raise CommandError("Dates must use YYYY-MM-DD format.") from exc

        try:
            result = GeneralLedgerSyncService().sync(
                SyncGeneralLedgerCommand(
                    integration=integration,
                    period_start=period_start,
                    period_end=period_end,
                    mode=options["mode"],
                    date_type=options["date_type"],
                    with_lines=not options["without_lines"],
                    with_cost_allocations=not options["without_cost_allocations"],
                    initial_import=options["mode"] == "initial_backfill",
                    metadata={"source": "sync_general_ledger_command"},
                )
            )
        except Exception as exc:
            raise CommandError(self._safe_error(integration, "GL sync failed", exc, debug=debug)) from exc

        self.stdout.write(f"integration_id: {integration.id}")
        self.stdout.write(f"provider: {integration.provider}")
        self.stdout.write(f"period_start: {result.period_start}")
        self.stdout.write(f"period_end: {result.period_end}")
        self.stdout.write(f"requested_chunk_count: {result.requested_chunk_count}")
        self.stdout.write(f"completed_chunk_count: {result.completed_chunk_count}")
        self.stdout.write(f"discovered_batch_count: {result.discovered_batch_count}")
        self.stdout.write(f"created_count: {result.created_count}")
        self.stdout.write(f"updated_count: {result.updated_count}")
        self.stdout.write(f"unchanged_count: {result.unchanged_count}")
        self.stdout.write(f"failed_count: {result.failed_count}")
        self.stdout.write(f"synced: {result.synced}")
        self.stdout.write(f"partial: {result.partial}")

    def _safe_error(self, integration, prefix, exc, *, debug=False):
        if not debug:
            return f"{prefix}. Check integration configuration and try again."
        value = f"{prefix}: {exc.__class__.__name__}: {exc}"
        for secret_value in [integration.api_id, integration.encrypted_secret_placeholder]:
            if secret_value:
                value = value.replace(secret_value, "[redacted]")
        return value
