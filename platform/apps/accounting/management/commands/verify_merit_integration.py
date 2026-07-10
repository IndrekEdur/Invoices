from django.core.management.base import BaseCommand, CommandError

from apps.accounting.connectors import MeritAPIClient
from apps.accounting.models import AccountingIntegration
from apps.accounting.services import AccountingDimensionSyncService, SyncAccountingDimensionsCommand


class Command(BaseCommand):
    help = "Safely verify a Merit accounting integration without exposing secrets."

    def add_arguments(self, parser):
        parser.add_argument("integration_id", type=int)
        parser.add_argument("--sync-dimensions", action="store_true")
        parser.add_argument("--debug", action="store_true")

    def handle(self, *args, **options):
        integration_id = options["integration_id"]
        sync_dimensions = options["sync_dimensions"]
        debug = options["debug"]

        try:
            integration = AccountingIntegration.objects.get(id=integration_id)
        except AccountingIntegration.DoesNotExist as exc:
            raise CommandError(f"AccountingIntegration not found: {integration_id}") from exc

        if integration.provider != AccountingIntegration.Provider.MERIT:
            raise CommandError("Only Merit integrations can be verified with this command.")

        self.stdout.write(f"integration_id: {integration.id}")
        self.stdout.write(f"provider: {integration.provider}")

        try:
            health = MeritAPIClient(integration).health()
        except Exception as exc:
            raise CommandError(self._safe_error("Merit health check failed", exc, debug=debug)) from exc

        self.stdout.write("health:")
        self.stdout.write(f"  healthy: {health.get('healthy')}")
        self.stdout.write(f"  provider: {health.get('provider')}")
        self.stdout.write(f"  mode: {health.get('mode', '')}")
        self.stdout.write(f"  response_time_ms: {health.get('response_time_ms', '')}")

        if not sync_dimensions:
            self.stdout.write("dimension_sync: skipped")
            return

        try:
            result = AccountingDimensionSyncService.sync(
                SyncAccountingDimensionsCommand(
                    integration=integration,
                    metadata={"source": "verify_merit_integration_command"},
                )
            )
        except Exception as exc:
            raise CommandError(self._safe_error("Merit dimension sync failed", exc, debug=debug)) from exc

        self.stdout.write("dimension_sync:")
        self.stdout.write(f"  created_count: {result.created_count}")
        self.stdout.write(f"  updated_count: {result.updated_count}")
        self.stdout.write(f"  unchanged_count: {result.unchanged_count}")
        self.stdout.write(f"  archived_count: {result.archived_count}")
        self.stdout.write(f"  conflict_count: {result.conflict_count}")

    def _safe_error(self, prefix, exc, *, debug=False):
        if not debug:
            return f"{prefix}. Check integration configuration and try again."
        return f"{prefix}: {exc.__class__.__name__}: {exc}"
