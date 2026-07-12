from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.accounting.models import (
    AccountingGLAllocation,
    AccountingGLBatch,
    AccountingGLEntry,
    AccountingIntegration,
)
from apps.accounting.services import (
    GeneralLedgerSyncService,
    GeneralLedgerVerificationService,
    SyncGeneralLedgerCommand,
    VerifyGeneralLedgerCommand,
)
from apps.projects.models import Project


class Command(BaseCommand):
    help = "Verify persisted Merit general-ledger sync results for a bounded period."

    def add_arguments(self, parser):
        parser.add_argument("integration_id", type=int)
        parser.add_argument("--start", required=True)
        parser.add_argument("--end", required=True)
        parser.add_argument("--run-sync", action="store_true")
        parser.add_argument("--repeat-sync", action="store_true")
        parser.add_argument("--show-unlinked", action="store_true")
        parser.add_argument("--sample-size", type=int, default=10)
        parser.add_argument("--debug", action="store_true")

    def handle(self, *args, **options):
        integration = self._get_integration(options["integration_id"])
        period_start, period_end = self._parse_period(options["start"], options["end"])
        if options["repeat_sync"] and not options["run_sync"]:
            raise CommandError("--repeat-sync requires --run-sync.")

        if not integration.is_active:
            self.stdout.write(self.style.WARNING("warning: integration is inactive; read-only verification will continue."))

        try:
            first_sync = None
            second_sync = None
            idempotency = None
            if options["run_sync"]:
                first_sync = self._run_sync(integration, period_start, period_end, options["debug"])
                if options["repeat_sync"]:
                    before = self._identity_snapshot(integration, period_start, period_end)
                    second_sync = self._run_sync(integration, period_start, period_end, options["debug"])
                    after = self._identity_snapshot(integration, period_start, period_end)
                    idempotency = self._compare_snapshots(before, after, second_sync)

            result = GeneralLedgerVerificationService.verify(
                VerifyGeneralLedgerCommand(
                    integration=integration,
                    period_start=period_start,
                    period_end=period_end,
                    sample_size=options["sample_size"],
                    metadata={"source": "verify_general_ledger_sync_command"},
                )
            )
        except Exception as exc:
            raise CommandError(self._safe_error(integration, "GL verification failed", exc, debug=options["debug"])) from exc

        self._print_report(result, first_sync=first_sync, second_sync=second_sync, idempotency=idempotency, show_unlinked=options["show_unlinked"])

        if result.critical_errors:
            raise CommandError("Critical GL verification errors were found.")
        if idempotency and idempotency["critical_errors"]:
            raise CommandError("GL idempotency verification failed.")

    def _get_integration(self, integration_id):
        try:
            return AccountingIntegration.objects.get(id=integration_id)
        except AccountingIntegration.DoesNotExist as exc:
            raise CommandError(f"AccountingIntegration not found: {integration_id}") from exc

    def _parse_period(self, start_value, end_value):
        try:
            period_start = date.fromisoformat(start_value)
            period_end = date.fromisoformat(end_value)
        except ValueError as exc:
            raise CommandError("Dates must use YYYY-MM-DD format.") from exc
        if period_end < period_start:
            raise CommandError("End date cannot be before start date.")
        return period_start, period_end

    def _run_sync(self, integration, period_start, period_end, debug):
        try:
            result = GeneralLedgerSyncService().sync(
                SyncGeneralLedgerCommand(
                    integration=integration,
                    period_start=period_start,
                    period_end=period_end,
                    mode="manual",
                    date_type="document_date",
                    metadata={"source": "verify_general_ledger_sync_command"},
                )
            )
        except Exception as exc:
            raise CommandError(self._safe_error(integration, "GL sync failed", exc, debug=debug)) from exc
        return result

    def _identity_snapshot(self, integration, period_start, period_end):
        batch_ids = dict(
            AccountingGLBatch.objects.filter(
                integration=integration,
                batch_date__gte=period_start,
                batch_date__lte=period_end,
            ).values_list("external_id", "id")
        )
        entry_ids = dict(
            AccountingGLEntry.objects.filter(batch_id__in=batch_ids.values()).values_list("external_id", "id")
        )
        allocation_ids = dict(
            AccountingGLAllocation.objects.filter(entry_id__in=entry_ids.values()).values_list("external_id", "id")
        )
        return {
            "batch_count": len(batch_ids),
            "entry_count": len(entry_ids),
            "allocation_count": len(allocation_ids),
            "batch_ids": batch_ids,
            "entry_ids": entry_ids,
            "allocation_ids": allocation_ids,
            "project_count": Project.objects.filter(organization=integration.organization).count(),
        }

    def _compare_snapshots(self, before, after, second_sync):
        critical_errors = []
        warnings = []
        for key in ["batch_count", "entry_count", "allocation_count", "project_count"]:
            if before[key] != after[key]:
                critical_errors.append(f"{key} changed from {before[key]} to {after[key]} after identical repeat sync.")
        for key in ["batch_ids", "entry_ids", "allocation_ids"]:
            if before[key] != after[key]:
                critical_errors.append(f"{key} changed after identical repeat sync.")
        if second_sync and second_sync.updated_count:
            warnings.append("Second sync updated existing rows; source data may have changed, so idempotency is partly inconclusive.")
        return {"critical_errors": critical_errors, "warnings": warnings}

    def _print_report(self, result, *, first_sync=None, second_sync=None, idempotency=None, show_unlinked=False):
        metadata = result.metadata
        self.stdout.write("General ledger verification")
        self.stdout.write(f"integration_id: {result.integration.id}")
        self.stdout.write(f"display_name: {result.integration.display_name}")
        self.stdout.write(f"provider: {result.integration.provider}")
        self.stdout.write(f"active: {result.integration.is_active}")
        self.stdout.write(f"period_start: {result.period_start}")
        self.stdout.write(f"period_end: {result.period_end}")

        if first_sync:
            self.stdout.write("sync_result:")
            self.stdout.write(f"  created_count: {first_sync.created_count}")
            self.stdout.write(f"  updated_count: {first_sync.updated_count}")
            self.stdout.write(f"  unchanged_count: {first_sync.unchanged_count}")
            self.stdout.write(f"  failed_count: {first_sync.failed_count}")
        if second_sync:
            self.stdout.write("repeat_sync_result:")
            self.stdout.write(f"  created_count: {second_sync.created_count}")
            self.stdout.write(f"  updated_count: {second_sync.updated_count}")
            self.stdout.write(f"  unchanged_count: {second_sync.unchanged_count}")
            self.stdout.write(f"  failed_count: {second_sync.failed_count}")

        self._print_mapping("sync_state", metadata["sync_state"])
        self._print_mapping("latest_matching_sync_run", metadata["sync_run"])

        self.stdout.write("cache_counts:")
        self.stdout.write(f"  gl_batches: {result.batch_count}")
        self.stdout.write(f"  gl_entries: {result.entry_count}")
        self.stdout.write(f"  gl_allocations: {result.allocation_count}")

        self._print_mapping("link_quality", metadata["link_quality"])
        self._print_mapping("data_quality", metadata["data_quality"])
        self.stdout.write("diagnostic_source_totals:")
        for key, value in metadata["financial_totals"].items():
            self.stdout.write(f"  {key}: {self._format_value(value)}")
        if metadata["financial_totals"]["currency_count"] > 1:
            self.stdout.write(self.style.WARNING("warning: mixed currencies present; totals are not directly comparable."))

        self._print_mapping("allocation_coverage", metadata["allocation_coverage"])
        self._print_mapping("source_identity_checks", metadata["identity"])
        if idempotency:
            self._print_mapping("idempotency", idempotency)

        self._print_samples("project_linked_allocations", metadata["samples"]["project_linked"])
        if show_unlinked:
            self._print_samples("unlinked_allocations", metadata["samples"]["unlinked"])

        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(f"warning: {warning}"))
        for error in result.critical_errors:
            self.stdout.write(self.style.ERROR(f"critical: {error}"))

    def _print_mapping(self, title, mapping):
        self.stdout.write(f"{title}:")
        if not mapping:
            self.stdout.write("  none")
            return
        for key, value in mapping.items():
            self.stdout.write(f"  {key}: {self._format_value(value)}")

    def _print_samples(self, title, rows):
        self.stdout.write(f"{title}:")
        if not rows:
            self.stdout.write("  none")
            return
        for row in rows:
            bits = [f"{key}={self._format_value(value)}" for key, value in row.items()]
            self.stdout.write("  " + "; ".join(bits))

    def _format_value(self, value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, list):
            return ", ".join(str(item) for item in value) if value else "none"
        return str(value)

    def _safe_error(self, integration, prefix, exc, *, debug=False):
        if not debug:
            return f"{prefix}. Check integration configuration and local sync data."
        value = f"{prefix}: {exc.__class__.__name__}: {exc}"
        for secret_value in [integration.api_id, integration.encrypted_secret_placeholder]:
            if secret_value:
                value = value.replace(secret_value, "[redacted]")
        return value
