from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from io import StringIO
from copy import deepcopy
from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from apps.accounting.connectors import (
    AccountingAPIError,
    AccountingAuthenticationError,
    AccountingConnectionError,
    AccountingRateLimitError,
    AccountingUnexpectedResponseError,
    MeritAuthentication,
    MeritAuthenticationService,
    MeritAPIClient,
)
from apps.accounting.dto import (
    MeritDimensionDTO,
    MeritDimensionValueDTO,
    MeritGLBatchDTO,
    MeritGLCostAllocationDTO,
    MeritGLDateType,
    MeritGLEntryDTO,
)
from apps.accounting.models import (
    AccountingAccountClassification,
    AccountingDimension,
    AccountingGLAllocation,
    AccountingGLBatch,
    AccountingGLEntry,
    AccountingIntegration,
    AccountingSyncRun,
    AccountingSyncState,
    AllocationSourceAmountBasis,
    AllocationSourceType,
    AllocationStrategy,
    ManagementAllocationEntry,
    ManagementAllocationPeriod,
    ManagementAllocationRule,
    ManagementAllocationVersion,
    ManagementCostPool,
    ManagementCostPoolAccount,
    PeriodStatus,
    VersionStatus,
)
from apps.accounting.secrets import SecretMissingError, SecretProvider
from apps.accounting.services import (
    AccountClassificationService,
    AccountingAccountClassificationManagementService,
    AggregateProjectFinancialsCommand,
    AccountingDimensionConflictResolutionService,
    AccountingDimensionValueService,
    AccountingDimensionSyncService,
    AccountingSyncStateService,
    ApproveManagementAllocationVersionCommand,
    BuildManagementFinancialsCommand,
    CreateAccountingDimensionValueCommand,
    CreateManagementAllocationRuleCommand,
    CreateManagementAllocationVersionCommand,
    CreateManagementCostPoolCommand,
    CompleteAccountingSyncRunCommand,
    FailAccountingSyncRunCommand,
    GeneralLedgerVerificationResult,
    GenerateManagementAllocationProposalCommand,
    GeneralLedgerCacheService,
    GeneralLedgerSyncService,
    GeneralLedgerVerificationService,
    GetOrCreateAccountingSyncStateCommand,
    GLCacheUpsertResult,
    IgnoreDimensionConflictCommand,
    ProjectCodeAllocationService,
    ProjectFinancialAggregationService,
    ResolveDimensionConflictCommand,
    SaveAccountingAccountClassificationCommand,
    ManagementAllocationVersionService,
    ManagementAllocationProposalService,
    ManagementCostPoolService,
    ProjectManagementFinancialService,
    SuggestNextProjectCodeCommand,
    StartAccountingSyncRunCommand,
    SyncAccountingDimensionsCommand,
    SyncAccountingDimensionsResult,
    SyncGeneralLedgerCommand,
    SyncGeneralLedgerResult,
    UpdateAccountingSyncProgressCommand,
    UpsertGLAllocationCommand,
    UpsertGLBatchCommand,
    UpsertGLEntryCommand,
    VerifyGeneralLedgerCommand,
)
from apps.core.models import AuditEvent
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.projects.models import Project, ProjectParty


def create_organization(name="Accounting Org"):
    return OrganizationService.create(CreateOrganizationCommand(name=name))


def create_merit_integration(organization=None):
    organization = organization or create_organization()
    return AccountingIntegration.objects.create(
        organization=organization,
        provider=AccountingIntegration.Provider.MERIT,
        display_name="Merit API",
        api_base_url="https://merit.example.test",
        api_id="api-id",
        encrypted_secret_placeholder="api-secret",
    )


class FakeHTTPResponse:
    def __init__(self, body, *, status=200, headers=None):
        self.body = body.encode("utf-8")
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.body


class StaticSecretProvider:
    def __init__(self, secret="provider-secret"):
        self.secret = secret
        self.calls = 0

    def get_secret(self, integration):
        self.calls += 1
        return self.secret


class TrackingSecretProvider:
    def __init__(self, secret="api-secret"):
        self.secret = secret
        self.calls = 0

    def get_secret(self, integration):
        self.calls += 1
        return self.secret


def http_error(status, body=""):
    return HTTPError(
        url="https://merit.example.test/api",
        code=status,
        msg="Error",
        hdrs={},
        fp=BytesIO(body.encode("utf-8")),
    )


class AccountingIntegrationTests(TestCase):
    def test_can_create_integration(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Merit Aktiva",
            api_base_url="https://api.merit.ee/",
            api_id="test-api-id",
            encrypted_secret_placeholder="not-a-real-secret",
        )

        self.assertEqual(integration.display_name, "Merit Aktiva")

    def test_default_provider_is_merit(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Default provider",
        )

        self.assertEqual(integration.provider, AccountingIntegration.Provider.MERIT)

    def test_organization_linked(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Linked organization",
        )

        self.assertEqual(integration.organization, organization)

    def test_is_active_defaults_true(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Active integration",
        )

        self.assertTrue(integration.is_active)

    def test_str_works(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Merit production",
        )

        self.assertEqual(str(integration), "Merit production (merit)")

    def test_last_sync_at_can_be_null(self):
        organization = create_organization()

        integration = AccountingIntegration.objects.create(
            organization=organization,
            display_name="Never synced",
        )

        self.assertIsNone(integration.last_sync_at)


class AccountingDimensionTests(TestCase):
    def test_can_create_accounting_dimension(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26124",
            name="Kanarbiku",
        )

        self.assertEqual(dimension.code, "26124")
        self.assertEqual(dimension.name, "Kanarbiku")

    def test_default_provider_is_merit(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26125",
            name="Default provider",
        )

        self.assertEqual(dimension.provider, AccountingDimension.Provider.MERIT)

    def test_default_dimension_type_is_project(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26126",
            name="Default type",
        )

        self.assertEqual(dimension.dimension_type, AccountingDimension.DimensionType.PROJECT)

    def test_is_active_defaults_true(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26127",
            name="Active dimension",
        )

        self.assertTrue(dimension.is_active)

    def test_organization_code_uniqueness_works(self):
        organization = create_organization()
        AccountingDimension.objects.create(
            organization=organization,
            code="26128",
            name="First dimension",
        )

        with self.assertRaises(IntegrityError):
            AccountingDimension.objects.create(
                organization=organization,
                code="26128",
                name="Duplicate dimension",
            )

    def test_external_id_can_be_null(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26129",
            name="No external id",
        )

        self.assertIsNone(dimension.external_id)

    def test_last_synced_at_can_be_null(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26130",
            name="Never synced",
        )

        self.assertIsNone(dimension.last_synced_at)

    def test_str_includes_code_and_name(self):
        organization = create_organization()

        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26131",
            name="Display name",
        )

        self.assertEqual(str(dimension), "26131 Display name")


class AccountingSyncStateModelTests(TestCase):
    def test_can_create_accounting_sync_state(self):
        integration = create_merit_integration()

        state = AccountingSyncState.objects.create(
            organization=integration.organization,
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
        )

        self.assertEqual(state.source_type, AccountingSyncState.SourceType.GL)
        self.assertEqual(state.organization, integration.organization)

    def test_state_defaults(self):
        integration = create_merit_integration()

        state = AccountingSyncState.objects.create(
            organization=integration.organization,
            integration=integration,
            source_type=AccountingSyncState.SourceType.SALES_INVOICES,
        )

        self.assertEqual(state.cursor_type, AccountingSyncState.CursorType.NONE)
        self.assertEqual(state.cursor_value, "")
        self.assertEqual(state.sync_status, AccountingSyncState.SyncStatus.IDLE)
        self.assertEqual(state.initial_import_status, AccountingSyncState.InitialImportStatus.NOT_STARTED)
        self.assertEqual(state.discovered_count, 0)
        self.assertEqual(state.metadata, {})

    def test_integration_source_uniqueness(self):
        integration = create_merit_integration()
        AccountingSyncState.objects.create(
            organization=integration.organization,
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
        )

        with self.assertRaises(IntegrityError):
            AccountingSyncState.objects.create(
                organization=integration.organization,
                integration=integration,
                source_type=AccountingSyncState.SourceType.GL,
            )

    def test_nullable_cursor_and_period_fields(self):
        integration = create_merit_integration()

        state = AccountingSyncState.objects.create(
            organization=integration.organization,
            integration=integration,
            source_type=AccountingSyncState.SourceType.PAYMENTS,
        )

        self.assertIsNone(state.cursor_datetime)
        self.assertIsNone(state.last_completed_period_start)
        self.assertIsNone(state.last_completed_period_end)

    def test_state_str_includes_integration_source_and_status(self):
        integration = create_merit_integration()
        state = AccountingSyncState.objects.create(
            organization=integration.organization,
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
        )

        self.assertIn("Merit API", str(state))
        self.assertIn("gl", str(state))
        self.assertIn("idle", str(state))

    def test_can_create_accounting_sync_run(self):
        state = self._state()

        run = AccountingSyncRun.objects.create(
            organization=state.organization,
            integration=state.integration,
            sync_state=state,
            source_type=state.source_type,
        )

        self.assertEqual(run.status, AccountingSyncRun.Status.RUNNING)
        self.assertEqual(run.mode, AccountingSyncRun.Mode.INCREMENTAL)
        self.assertIsNone(run.completed_at)

    def test_run_defaults_and_str(self):
        state = self._state()

        run = AccountingSyncRun.objects.create(
            organization=state.organization,
            integration=state.integration,
            sync_state=state,
            source_type=state.source_type,
        )

        self.assertEqual(run.cursor_before, "")
        self.assertEqual(run.cursor_after, "")
        self.assertEqual(run.discovered_count, 0)
        self.assertIn("Merit API", str(run))
        self.assertIn("gl", str(run))
        self.assertIn("running", str(run))

    def _state(self):
        integration = create_merit_integration()
        return AccountingSyncState.objects.create(
            organization=integration.organization,
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
        )


class AccountingSyncStateServiceTests(TestCase):
    def test_get_or_create_creates_state(self):
        integration = create_merit_integration()

        state = AccountingSyncStateService.get_or_create(
            GetOrCreateAccountingSyncStateCommand(
                integration=integration,
                source_type=AccountingSyncState.SourceType.GL,
                cursor_type=AccountingSyncState.CursorType.CHANGED_DATETIME,
            )
        )

        self.assertEqual(state.organization, integration.organization)
        self.assertEqual(state.cursor_type, AccountingSyncState.CursorType.CHANGED_DATETIME)

    def test_get_or_create_returns_existing_without_cursor_reset(self):
        integration = create_merit_integration()
        state = AccountingSyncStateService.get_or_create(
            GetOrCreateAccountingSyncStateCommand(integration=integration, source_type=AccountingSyncState.SourceType.GL)
        )
        state.cursor_value = "existing-cursor"
        state.discovered_count = 7
        state.save()

        returned = AccountingSyncStateService.get_or_create(
            GetOrCreateAccountingSyncStateCommand(
                integration=integration,
                source_type=AccountingSyncState.SourceType.GL,
                cursor_type=AccountingSyncState.CursorType.PERIOD,
            )
        )

        self.assertEqual(returned.id, state.id)
        self.assertEqual(returned.cursor_value, "existing-cursor")
        self.assertEqual(returned.discovered_count, 7)

    def test_gl_and_invoice_states_are_independent(self):
        integration = create_merit_integration()

        gl_state = AccountingSyncStateService.get_or_create(
            GetOrCreateAccountingSyncStateCommand(integration=integration, source_type=AccountingSyncState.SourceType.GL)
        )
        invoice_state = AccountingSyncStateService.get_or_create(
            GetOrCreateAccountingSyncStateCommand(
                integration=integration,
                source_type=AccountingSyncState.SourceType.PURCHASE_INVOICES,
            )
        )

        self.assertNotEqual(gl_state.id, invoice_state.id)
        self.assertEqual(AccountingSyncState.objects.count(), 2)

    def test_start_run_creates_running_run_and_records_cursor_before(self):
        state = self._state(cursor_value="before")

        run = AccountingSyncStateService.start_run(
            StartAccountingSyncRunCommand(
                sync_state=state,
                mode=AccountingSyncRun.Mode.INITIAL_BACKFILL,
                requested_period_start=date(2026, 7, 1),
                requested_period_end=date(2026, 7, 31),
                initial_import=True,
            )
        )
        state.refresh_from_db()

        self.assertEqual(state.sync_status, AccountingSyncState.SyncStatus.RUNNING)
        self.assertEqual(state.initial_import_status, AccountingSyncState.InitialImportStatus.RUNNING)
        self.assertEqual(run.status, AccountingSyncRun.Status.RUNNING)
        self.assertEqual(run.cursor_before, "before")
        self.assertEqual(run.requested_period_start, date(2026, 7, 1))

    def test_update_progress_updates_cursor_period_and_counters(self):
        state = self._state()
        run = AccountingSyncStateService.start_run(StartAccountingSyncRunCommand(sync_state=state))
        metadata = {"note": "progress"}
        cursor_metadata = {"high_watermark": "2026-07-12"}

        updated_state, updated_run = AccountingSyncStateService.update_progress(
            UpdateAccountingSyncProgressCommand(
                sync_state=state,
                sync_run=run,
                cursor_value="cursor-1",
                cursor_datetime=timezone.now(),
                completed_period_start=date(2026, 7, 1),
                completed_period_end=date(2026, 7, 31),
                discovered_increment=5,
                created_increment=2,
                updated_increment=1,
                unchanged_increment=1,
                skipped_increment=1,
                failed_increment=0,
                cursor_metadata=cursor_metadata,
                metadata=metadata,
            )
        )

        self.assertEqual(updated_state.cursor_value, "cursor-1")
        self.assertEqual(updated_state.last_completed_period_start, date(2026, 7, 1))
        self.assertEqual(updated_state.discovered_count, 5)
        self.assertEqual(updated_run.created_count, 2)
        self.assertEqual(updated_run.updated_count, 1)
        self.assertEqual(updated_state.cursor_metadata["high_watermark"], "2026-07-12")
        self.assertEqual(metadata, {"note": "progress"})
        self.assertEqual(cursor_metadata, {"high_watermark": "2026-07-12"})

    def test_update_progress_rejects_negative_increments(self):
        state = self._state()
        run = AccountingSyncStateService.start_run(StartAccountingSyncRunCommand(sync_state=state))

        with self.assertRaises(ValueError):
            AccountingSyncStateService.update_progress(
                UpdateAccountingSyncProgressCommand(sync_state=state, sync_run=run, discovered_increment=-1)
            )

    def test_complete_run_updates_successful_timestamps_and_cursor_after(self):
        state = self._state(cursor_value="before")
        run = AccountingSyncStateService.start_run(StartAccountingSyncRunCommand(sync_state=state))

        completed = AccountingSyncStateService.complete_run(
            CompleteAccountingSyncRunCommand(
                sync_state=state,
                sync_run=run,
                cursor_value="after",
                completed_period_start=date(2026, 7, 1),
                completed_period_end=date(2026, 7, 31),
                initial_import=True,
            )
        )
        state.refresh_from_db()

        self.assertEqual(state.sync_status, AccountingSyncState.SyncStatus.IDLE)
        self.assertEqual(state.initial_import_status, AccountingSyncState.InitialImportStatus.COMPLETED)
        self.assertEqual(state.cursor_value, "after")
        self.assertIsNotNone(state.last_successful_sync_at)
        self.assertEqual(completed.status, AccountingSyncRun.Status.COMPLETED)
        self.assertEqual(completed.cursor_after, "after")

    def test_fail_run_stores_safe_error_and_partial_status(self):
        integration = create_merit_integration()
        state = self._state(integration=integration)
        run = AccountingSyncStateService.start_run(StartAccountingSyncRunCommand(sync_state=state, initial_import=True))

        failed = AccountingSyncStateService.fail_run(
            FailAccountingSyncRunCommand(
                sync_state=state,
                sync_run=run,
                safe_error=f"Failure for {integration.api_id} with {integration.encrypted_secret_placeholder}",
                partial=True,
                initial_import=True,
            )
        )
        state.refresh_from_db()

        self.assertEqual(state.sync_status, AccountingSyncState.SyncStatus.FAILED)
        self.assertEqual(state.initial_import_status, AccountingSyncState.InitialImportStatus.FAILED)
        self.assertEqual(failed.status, AccountingSyncRun.Status.PARTIAL)
        self.assertNotIn(integration.api_id, state.last_error)
        self.assertNotIn(integration.encrypted_secret_placeholder, state.last_error)

    def test_pause_changes_state(self):
        state = self._state(
            sync_status=AccountingSyncState.SyncStatus.RUNNING,
            initial_import_status=AccountingSyncState.InitialImportStatus.RUNNING,
        )

        paused = AccountingSyncStateService.pause(state)

        self.assertEqual(paused.sync_status, AccountingSyncState.SyncStatus.PAUSED)
        self.assertEqual(paused.initial_import_status, AccountingSyncState.InitialImportStatus.PAUSED)

    def test_audit_events_created_for_start_complete_fail_pause(self):
        state = self._state()
        run = AccountingSyncStateService.start_run(StartAccountingSyncRunCommand(sync_state=state))
        AccountingSyncStateService.complete_run(CompleteAccountingSyncRunCommand(sync_state=state, sync_run=run))
        run = AccountingSyncStateService.start_run(StartAccountingSyncRunCommand(sync_state=state))
        AccountingSyncStateService.fail_run(FailAccountingSyncRunCommand(sync_state=state, sync_run=run, safe_error="safe"))
        AccountingSyncStateService.pause(state)

        self.assertEqual(
            AuditEvent.objects.filter(object_type="AccountingSyncState", object_id=str(state.id)).count(),
            5,
        )

    def test_invalid_source_type_handled(self):
        integration = create_merit_integration()

        with self.assertRaises(ValueError):
            AccountingSyncStateService.get_or_create(
                GetOrCreateAccountingSyncStateCommand(integration=integration, source_type="bank_payments")
            )

    def test_reversed_period_rejected(self):
        state = self._state()

        with self.assertRaises(ValueError):
            AccountingSyncStateService.start_run(
                StartAccountingSyncRunCommand(
                    sync_state=state,
                    requested_period_start=date(2026, 7, 31),
                    requested_period_end=date(2026, 7, 1),
                )
            )

    def test_completed_period_cannot_move_backwards_without_resync_mode(self):
        state = self._state()
        state.last_completed_period_start = date(2026, 7, 1)
        state.last_completed_period_end = date(2026, 7, 31)
        state.save()
        run = AccountingSyncStateService.start_run(StartAccountingSyncRunCommand(sync_state=state))

        with self.assertRaises(ValueError):
            AccountingSyncStateService.update_progress(
                UpdateAccountingSyncProgressCommand(
                    sync_state=state,
                    sync_run=run,
                    completed_period_start=date(2026, 6, 1),
                    completed_period_end=date(2026, 6, 30),
                )
            )

    def test_organization_isolation(self):
        first = self._state()
        second = self._state(integration=create_merit_integration(create_organization("Other Org")))

        self.assertNotEqual(first.organization_id, second.organization_id)
        self.assertEqual(AccountingSyncState.objects.filter(organization=first.organization).count(), 1)
        self.assertEqual(AccountingSyncState.objects.filter(organization=second.organization).count(), 1)

    def test_rollback_if_audit_fails(self):
        state = self._state()

        with patch("apps.accounting.services.sync_state.AuditService.record", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                AccountingSyncStateService.start_run(StartAccountingSyncRunCommand(sync_state=state))

        state.refresh_from_db()
        self.assertEqual(state.sync_status, AccountingSyncState.SyncStatus.IDLE)
        self.assertFalse(AccountingSyncRun.objects.exists())

    def test_no_merit_api_calls_and_no_financial_cache_created(self):
        state = self._state()

        with patch.object(MeritAPIClient, "request") as request_mock:
            AccountingSyncStateService.start_run(StartAccountingSyncRunCommand(sync_state=state))

        request_mock.assert_not_called()
        self.assertFalse(hasattr(AccountingSyncRun, "transaction"))
        self.assertFalse(hasattr(AccountingSyncState, "transaction"))

    def _state(self, integration=None, cursor_value="", **overrides):
        integration = integration or create_merit_integration()
        defaults = {
            "organization": integration.organization,
            "integration": integration,
            "source_type": AccountingSyncState.SourceType.GL,
            "cursor_value": cursor_value,
        }
        defaults.update(overrides)
        return AccountingSyncState.objects.create(**defaults)


class GeneralLedgerCacheModelTests(TestCase):
    def test_create_gl_batch_and_decimal_precision(self):
        integration = create_merit_integration()

        batch = AccountingGLBatch.objects.create(
            organization=integration.organization,
            integration=integration,
            external_id="glb-1",
            batch_date=date(2026, 7, 1),
            currency_rate=Decimal("1.23456789"),
            total_amount=Decimal("123.456789"),
        )

        self.assertEqual(batch.external_id, "glb-1")
        self.assertEqual(batch.currency_rate, Decimal("1.23456789"))
        self.assertEqual(batch.total_amount, Decimal("123.456789"))

    def test_gl_batch_unique_integration_external_id(self):
        integration = create_merit_integration()
        AccountingGLBatch.objects.create(
            organization=integration.organization,
            integration=integration,
            external_id="glb-1",
        )

        with self.assertRaises(IntegrityError):
            AccountingGLBatch.objects.create(
                organization=integration.organization,
                integration=integration,
                external_id="glb-1",
            )

    def test_gl_batch_nullable_source_fields_and_str(self):
        integration = create_merit_integration()

        batch = AccountingGLBatch.objects.create(
            organization=integration.organization,
            integration=integration,
            external_id="glb-2",
        )

        self.assertIsNone(batch.batch_date)
        self.assertIsNone(batch.source_changed_at)
        self.assertIn("glb-2", str(batch))

    def test_create_gl_entry_uniqueness_net_amount_and_str(self):
        batch = self._batch()

        entry = AccountingGLEntry.objects.create(
            organization=batch.organization,
            integration=batch.integration,
            batch=batch,
            external_id="entry-1",
            account_code="4000",
            memo="Revenue",
            debit_amount=Decimal("10.000000"),
            credit_amount=Decimal("3.250000"),
        )

        self.assertEqual(entry.net_amount, Decimal("6.750000"))
        self.assertIn("4000", str(entry))
        with self.assertRaises(IntegrityError):
            AccountingGLEntry.objects.create(
                organization=batch.organization,
                integration=batch.integration,
                batch=batch,
                external_id="entry-1",
            )

    def test_create_allocation_uniqueness_nullable_links_and_str(self):
        entry = self._entry()

        allocation = AccountingGLAllocation.objects.create(
            organization=entry.organization,
            integration=entry.integration,
            entry=entry,
            external_id="alloc-1",
            dimension_code="26124",
            dimension_name="Kanarbiku",
            amount=Decimal("50.000000"),
        )

        self.assertIsNone(allocation.project)
        self.assertIsNone(allocation.accounting_dimension)
        self.assertIn("26124", str(allocation))
        with self.assertRaises(IntegrityError):
            AccountingGLAllocation.objects.create(
                organization=entry.organization,
                integration=entry.integration,
                entry=entry,
                external_id="alloc-1",
            )

    def test_organization_scoping(self):
        first = self._batch()
        second = self._batch(integration=create_merit_integration(create_organization("Other GL Org")), external_id="glb-2")

        self.assertNotEqual(first.organization_id, second.organization_id)

    def _batch(self, integration=None, external_id="glb-1"):
        integration = integration or create_merit_integration()
        return AccountingGLBatch.objects.create(
            organization=integration.organization,
            integration=integration,
            external_id=external_id,
        )

    def _entry(self):
        batch = self._batch()
        return AccountingGLEntry.objects.create(
            organization=batch.organization,
            integration=batch.integration,
            batch=batch,
            external_id="entry-1",
        )


class AccountingAccountClassificationTests(TestCase):
    def test_create_classification_and_unique_constraints(self):
        integration = create_merit_integration()
        classification = AccountingAccountClassification.objects.create(
            organization=integration.organization,
            integration=integration,
            account_code="4000",
            account_name="Revenue",
            category=AccountingAccountClassification.Category.REVENUE,
            reporting_sign=Decimal("-1"),
        )

        self.assertEqual(classification.category, AccountingAccountClassification.Category.REVENUE)
        with self.assertRaises(Exception):
            AccountingAccountClassification.objects.create(
                organization=integration.organization,
                integration=integration,
                account_code="4000",
            )

    def test_reporting_sign_validation(self):
        integration = create_merit_integration()

        with self.assertRaises(Exception):
            AccountingAccountClassification.objects.create(
                organization=integration.organization,
                account_code="4000",
                reporting_sign=Decimal("2"),
            )

    def test_lookup_priority_fallback_inactive_and_isolation(self):
        integration = create_merit_integration()
        other_integration = create_merit_integration(create_organization("Other Class Org"))
        AccountingAccountClassification.objects.create(
            organization=integration.organization,
            account_code="4000",
            category=AccountingAccountClassification.Category.MATERIAL_COST,
        )
        AccountingAccountClassification.objects.create(
            organization=integration.organization,
            integration=integration,
            account_code="4000",
            category=AccountingAccountClassification.Category.REVENUE,
            reporting_sign=Decimal("-1"),
        )
        AccountingAccountClassification.objects.create(
            organization=integration.organization,
            integration=integration,
            account_code="5000",
            category=AccountingAccountClassification.Category.LABOR_COST,
            is_active=False,
        )
        AccountingAccountClassification.objects.create(
            organization=other_integration.organization,
            account_code="4000",
            category=AccountingAccountClassification.Category.SUBCONTRACTOR_COST,
        )

        exact = AccountClassificationService.get_classification(integration.organization, integration, "4000")
        fallback = AccountClassificationService.get_classification(integration.organization, integration, "4010")
        inactive = AccountClassificationService.get_classification(integration.organization, integration, "5000")

        self.assertEqual(exact["category"], AccountingAccountClassification.Category.REVENUE)
        self.assertEqual(fallback["category"], AccountingAccountClassification.Category.UNCLASSIFIED)
        self.assertEqual(inactive["category"], AccountingAccountClassification.Category.UNCLASSIFIED)

    def test_lookup_performs_no_writes(self):
        integration = create_merit_integration()
        count = AccountingAccountClassification.objects.count()

        AccountClassificationService.get_classification(integration.organization, integration, "4000")

        self.assertEqual(AccountingAccountClassification.objects.count(), count)


class AccountingAccountClassificationManagementServiceTests(TestCase):
    def _entry(self, integration, account_code="4000", account_name="Materials"):
        batch = AccountingGLBatch.objects.create(
            organization=integration.organization,
            integration=integration,
            external_id=f"batch-{account_code}",
            batch_date=date(2026, 6, 1),
            currency_code="EUR",
        )
        return AccountingGLEntry.objects.create(
            organization=integration.organization,
            integration=integration,
            batch=batch,
            external_id=f"entry-{account_code}",
            account_code=account_code,
            account_name=account_name,
            debit_amount=Decimal("100.000000"),
        )

    def _command(self, integration, **kwargs):
        defaults = {
            "organization": integration.organization,
            "integration": integration,
            "account_code": "4000",
            "account_name": "Materials",
            "category": AccountingAccountClassification.Category.MATERIAL_COST,
            "reporting_sign": "1",
            "include_in_project_result": True,
            "is_active": True,
            "notes": "Configured in settings",
        }
        defaults.update(kwargs)
        return SaveAccountingAccountClassificationCommand(**defaults)

    def test_save_creates_classification_and_audit_without_mutating_metadata(self):
        integration = create_merit_integration()
        self._entry(integration)
        metadata = {"source": "test"}

        classification = AccountingAccountClassificationManagementService.save(
            self._command(integration, metadata=metadata)
        )

        self.assertEqual(classification.category, AccountingAccountClassification.Category.MATERIAL_COST)
        self.assertEqual(metadata, {"source": "test"})
        self.assertTrue(AuditEvent.objects.filter(event_type="accounting_account_classification_saved").exists())

    def test_save_updates_existing_without_duplicate(self):
        integration = create_merit_integration()
        self._entry(integration)
        AccountingAccountClassificationManagementService.save(self._command(integration))

        updated = AccountingAccountClassificationManagementService.save(
            self._command(
                integration,
                category=AccountingAccountClassification.Category.EXCLUDED,
                reporting_sign="-1",
                include_in_project_result=False,
            )
        )

        self.assertEqual(AccountingAccountClassification.objects.count(), 1)
        self.assertEqual(updated.category, AccountingAccountClassification.Category.EXCLUDED)
        self.assertEqual(updated.reporting_sign, Decimal("-1"))
        self.assertFalse(updated.include_in_project_result)

    def test_save_rejects_missing_imported_account_and_bad_sign(self):
        integration = create_merit_integration()

        with self.assertRaises(ValueError):
            AccountingAccountClassificationManagementService.save(self._command(integration))

        self._entry(integration)
        with self.assertRaises(Exception):
            AccountingAccountClassificationManagementService.save(self._command(integration, reporting_sign="2"))

    def test_save_rejects_cross_organization_integration(self):
        integration = create_merit_integration()
        other = create_organization("Other Mapping Org")

        with self.assertRaises(ValueError):
            AccountingAccountClassificationManagementService.save(self._command(integration, organization=other))

    def test_saved_mapping_changes_project_aggregation_without_resync(self):
        integration = create_merit_integration()
        project = Project.objects.create(organization=integration.organization, code="26124", name="Kanarbiku")
        entry = self._entry(integration, account_code="5000", account_name="Materials")
        AccountingGLAllocation.objects.create(
            organization=integration.organization,
            integration=integration,
            entry=entry,
            external_id="alloc-5000",
            dimension_code=project.code,
            amount=Decimal("100.000000"),
            project=project,
        )

        before = ProjectFinancialAggregationService().aggregate(
            AggregateProjectFinancialsCommand(project=project, period_start=date(2026, 6, 1), period_end=date(2026, 6, 30))
        )
        AccountingAccountClassificationManagementService.save(
            self._command(integration, account_code="5000", account_name="Materials")
        )
        after = ProjectFinancialAggregationService().aggregate(
            AggregateProjectFinancialsCommand(project=project, period_start=date(2026, 6, 1), period_end=date(2026, 6, 30))
        )

        self.assertEqual(before.unclassified_amount, Decimal("100.000000"))
        self.assertEqual(before.total_cost, Decimal("0"))
        self.assertEqual(after.unclassified_amount, Decimal("0"))
        self.assertEqual(after.total_cost, Decimal("100.000000"))


class ProjectFinancialAggregationServiceTests(TestCase):
    def _integration(self):
        return create_merit_integration()

    def _project(self, integration=None, code="26124"):
        integration = integration or self._integration()
        return Project.objects.create(organization=integration.organization, code=code, name="Kanarbiku")

    def _classify(self, organization, account_code, category, *, integration=None, sign=Decimal("1"), include=True):
        return AccountingAccountClassification.objects.create(
            organization=organization,
            integration=integration,
            account_code=account_code,
            account_name=f"Account {account_code}",
            category=category,
            reporting_sign=sign,
            include_in_project_result=include,
        )

    def _allocation(
        self,
        project,
        *,
        integration=None,
        batch_date=date(2026, 6, 15),
        currency="EUR",
        account_code="4000",
        amount=Decimal("100.000000"),
        external_suffix="1",
        project_fk=True,
        raw_data=None,
    ):
        integration = integration or create_merit_integration(project.organization)
        batch = AccountingGLBatch.objects.create(
            organization=project.organization,
            integration=integration,
            external_id=f"glb-{external_suffix}",
            batch_date=batch_date,
            currency_code=currency,
            raw_data={"GLBId": f"glb-{external_suffix}"},
        )
        entry = AccountingGLEntry.objects.create(
            organization=project.organization,
            integration=integration,
            batch=batch,
            external_id=f"entry-{external_suffix}",
            account_code=account_code,
            account_name=f"Account {account_code}",
            raw_data={"EntryId": f"entry-{external_suffix}"},
        )
        return AccountingGLAllocation.objects.create(
            organization=project.organization,
            integration=integration,
            entry=entry,
            external_id=f"alloc-{external_suffix}",
            dimension_code=project.code,
            dimension_name=project.name,
            amount=amount,
            project=project if project_fk else None,
            raw_data=raw_data or {"Code": project.code},
        )

    def _aggregate(self, project, **kwargs):
        defaults = {
            "project": project,
            "period_start": date(2026, 6, 1),
            "period_end": date(2026, 6, 30),
        }
        defaults.update(kwargs)
        return ProjectFinancialAggregationService().aggregate(AggregateProjectFinancialsCommand(**defaults))

    def test_empty_project_returns_no_data_and_metadata_not_mutated(self):
        project = self._project()
        metadata = {"source": {"view": "test"}}

        result = self._aggregate(project, metadata=metadata)
        result.metadata["input_metadata"]["source"]["view"] = "changed"

        self.assertEqual(result.data_quality_status, "no_data")
        self.assertEqual(result.revenue, Decimal("0"))
        self.assertEqual(metadata, {"source": {"view": "test"}})

    def test_revenue_cost_result_margin_and_decimal_precision(self):
        integration = self._integration()
        project = self._project(integration)
        self._classify(project.organization, "3000", AccountingAccountClassification.Category.REVENUE, integration=integration, sign=Decimal("-1"))
        self._classify(project.organization, "5000", AccountingAccountClassification.Category.MATERIAL_COST, integration=integration)
        self._allocation(project, integration=integration, account_code="3000", amount=Decimal("-1000.123456"), external_suffix="rev")
        self._allocation(project, integration=integration, account_code="5000", amount=Decimal("250.123456"), external_suffix="cost")

        result = self._aggregate(project)

        self.assertEqual(result.revenue, Decimal("1000.123456"))
        self.assertEqual(result.total_cost, Decimal("250.123456"))
        self.assertEqual(result.result, Decimal("750.000000"))
        self.assertEqual(result.margin, Decimal("74.99"))

    def test_zero_revenue_margin_none_and_reversal_changes_totals(self):
        integration = self._integration()
        project = self._project(integration)
        self._classify(project.organization, "5000", AccountingAccountClassification.Category.MATERIAL_COST, integration=integration)
        self._allocation(project, integration=integration, account_code="5000", amount=Decimal("100.000000"), external_suffix="1")
        self._allocation(project, integration=integration, account_code="5000", amount=Decimal("-20.000000"), external_suffix="2")

        result = self._aggregate(project)

        self.assertEqual(result.total_cost, Decimal("80.000000"))
        self.assertIsNone(result.margin)

    def test_multiple_cost_categories_and_overhead_toggle(self):
        integration = self._integration()
        project = self._project(integration)
        self._classify(project.organization, "5100", AccountingAccountClassification.Category.SUBCONTRACTOR_COST, integration=integration)
        self._classify(project.organization, "5200", AccountingAccountClassification.Category.LABOR_COST, integration=integration)
        self._classify(project.organization, "5300", AccountingAccountClassification.Category.OVERHEAD, integration=integration)
        self._allocation(project, integration=integration, account_code="5100", amount=Decimal("100.000000"), external_suffix="sub")
        self._allocation(project, integration=integration, account_code="5200", amount=Decimal("50.000000"), external_suffix="labor")
        self._allocation(project, integration=integration, account_code="5300", amount=Decimal("25.000000"), external_suffix="overhead")

        included = self._aggregate(project)
        excluded = self._aggregate(project, include_overhead=False)

        self.assertEqual(included.total_cost, Decimal("175.000000"))
        self.assertEqual(excluded.total_cost, Decimal("150.000000"))
        self.assertEqual(included.months[0].subcontractor_cost, Decimal("100.000000"))
        self.assertEqual(included.months[0].labor_cost, Decimal("50.000000"))

    def test_unclassified_and_excluded_are_visible_but_excluded_from_result(self):
        integration = self._integration()
        project = self._project(integration)
        self._classify(project.organization, "9999", AccountingAccountClassification.Category.EXCLUDED, integration=integration)
        self._classify(project.organization, "8888", AccountingAccountClassification.Category.MATERIAL_COST, integration=integration, include=False)
        self._allocation(project, integration=integration, account_code="7777", amount=Decimal("10.000000"), external_suffix="unclassified")
        self._allocation(project, integration=integration, account_code="9999", amount=Decimal("20.000000"), external_suffix="excluded")
        self._allocation(project, integration=integration, account_code="8888", amount=Decimal("30.000000"), external_suffix="notincluded")

        result = self._aggregate(project)

        self.assertEqual(result.unclassified_amount, Decimal("10.000000"))
        self.assertEqual(result.excluded_amount, Decimal("50.000000"))
        self.assertEqual(result.total_cost, Decimal("0"))
        self.assertEqual(result.data_quality_status, "unclassified")

    def test_monthly_grouping_partial_year_boundary_and_leap_year(self):
        integration = self._integration()
        project = self._project(integration)
        self._classify(project.organization, "5000", AccountingAccountClassification.Category.MATERIAL_COST, integration=integration)
        self._allocation(project, integration=integration, batch_date=date(2025, 12, 31), account_code="5000", amount=Decimal("10.000000"), external_suffix="dec")
        self._allocation(project, integration=integration, batch_date=date(2026, 1, 1), account_code="5000", amount=Decimal("20.000000"), external_suffix="jan")
        self._allocation(project, integration=integration, batch_date=date(2024, 2, 29), account_code="5000", amount=Decimal("30.000000"), external_suffix="leap")

        boundary = ProjectFinancialAggregationService().aggregate(
            AggregateProjectFinancialsCommand(project=project, period_start=date(2025, 12, 15), period_end=date(2026, 1, 10))
        )
        leap_intervals = ProjectFinancialAggregationService.split_months(date(2024, 2, 10), date(2024, 3, 5))

        self.assertEqual([(month.year, month.month) for month in boundary.months], [(2025, 12), (2026, 1)])
        self.assertEqual(boundary.total_cost, Decimal("30.000000"))
        self.assertEqual(leap_intervals, [(date(2024, 2, 10), date(2024, 2, 29)), (date(2024, 3, 1), date(2024, 3, 5))])

    def test_missing_batch_date_warning(self):
        integration = self._integration()
        project = self._project(integration)
        self._classify(project.organization, "5000", AccountingAccountClassification.Category.MATERIAL_COST, integration=integration)
        self._allocation(project, integration=integration, account_code="5000", external_suffix="dated")
        batch = AccountingGLBatch.objects.create(
            organization=project.organization,
            integration=integration,
            external_id="missing-date",
            batch_date=None,
        )
        entry = AccountingGLEntry.objects.create(
            organization=project.organization,
            integration=integration,
            batch=batch,
            external_id="entry-missing",
            account_code="5000",
        )
        AccountingGLAllocation.objects.create(
            organization=project.organization,
            integration=integration,
            entry=entry,
            external_id="alloc-missing",
            dimension_code=project.code,
            amount=Decimal("5.000000"),
            project=project,
        )

        result = self._aggregate(project)

        self.assertIn("missing_batch_date:1", result.warnings)
        self.assertEqual(result.total_cost, Decimal("100.000000"))

    def test_allocation_correctness_and_project_fk_required(self):
        integration = self._integration()
        project = self._project(integration, "26124")
        other_project = Project.objects.create(organization=project.organization, code="26125", name="Other")
        self._classify(project.organization, "5000", AccountingAccountClassification.Category.MATERIAL_COST, integration=integration)
        batch = AccountingGLBatch.objects.create(
            organization=project.organization,
            integration=integration,
            external_id="shared-batch",
            batch_date=date(2026, 6, 10),
            currency_code="EUR",
        )
        entry = AccountingGLEntry.objects.create(
            organization=project.organization,
            integration=integration,
            batch=batch,
            external_id="shared-entry",
            account_code="5000",
        )
        AccountingGLAllocation.objects.create(organization=project.organization, integration=integration, entry=entry, external_id="a1", dimension_code="26124", amount=Decimal("40.000000"), project=project)
        AccountingGLAllocation.objects.create(organization=project.organization, integration=integration, entry=entry, external_id="a2", dimension_code="26125", amount=Decimal("60.000000"), project=other_project)
        AccountingGLAllocation.objects.create(organization=project.organization, integration=integration, entry=entry, external_id="a3", dimension_code="26124", amount=Decimal("999.000000"), project=None)

        result = self._aggregate(project)

        self.assertEqual(result.total_cost, Decimal("40.000000"))
        self.assertEqual(result.allocation_count, 1)
        self.assertIn("dimension_code_matches_project_without_project_fk:1", result.warnings)

    def test_currency_behavior(self):
        integration = self._integration()
        project = self._project(integration)
        self._classify(project.organization, "5000", AccountingAccountClassification.Category.MATERIAL_COST, integration=integration)
        self._allocation(project, integration=integration, currency="EUR", account_code="5000", amount=Decimal("10.000000"), external_suffix="eur")
        self._allocation(project, integration=integration, currency="USD", account_code="5000", amount=Decimal("20.000000"), external_suffix="usd")

        mixed = self._aggregate(project)
        eur = self._aggregate(project, currency="EUR")

        self.assertEqual(mixed.data_quality_status, "mixed_currency")
        self.assertIn("mixed_currency", mixed.warnings)
        self.assertEqual(eur.currency, "EUR")
        self.assertEqual(eur.total_cost, Decimal("10.000000"))
        self.assertEqual(eur.metadata["currencies_found"], ["EUR", "USD"])

    def test_traceability_source_counts_account_codes_and_sync_run_ids(self):
        integration = self._integration()
        project = self._project(integration)
        self._classify(project.organization, "5000", AccountingAccountClassification.Category.MATERIAL_COST, integration=integration)
        self._allocation(project, integration=integration, account_code="5000", external_suffix="1", raw_data={"sync_run_id": 123})
        self._allocation(project, integration=integration, account_code="5000", external_suffix="2", raw_data={"sync_run_id": 123})

        result = self._aggregate(project)
        category_total = result.metadata["category_totals"][AccountingAccountClassification.Category.MATERIAL_COST]

        self.assertEqual(result.source_batch_count, 2)
        self.assertEqual(result.source_entry_count, 2)
        self.assertEqual(result.allocation_count, 2)
        self.assertEqual(category_total.source_account_codes, ["5000"])
        self.assertEqual(result.source_sync_run_ids, [123])

    def test_no_database_writes_and_no_external_calls(self):
        integration = self._integration()
        project = self._project(integration)
        self._classify(project.organization, "5000", AccountingAccountClassification.Category.MATERIAL_COST, integration=integration)
        self._allocation(project, integration=integration, account_code="5000")
        counts = (
            AccountingGLBatch.objects.count(),
            AccountingGLEntry.objects.count(),
            AccountingGLAllocation.objects.count(),
            AccountingAccountClassification.objects.count(),
        )

        with patch.object(MeritAPIClient, "request") as request_mock:
            with patch.object(GeneralLedgerSyncService, "sync") as sync_mock:
                self._aggregate(project)

        request_mock.assert_not_called()
        sync_mock.assert_not_called()
        self.assertEqual(
            counts,
            (
                AccountingGLBatch.objects.count(),
                AccountingGLEntry.objects.count(),
                AccountingGLAllocation.objects.count(),
                AccountingAccountClassification.objects.count(),
            ),
        )


class ProjectManagementFinancialServiceTests(TestCase):
    def _setup_project(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        project = Project.objects.create(organization=organization, code="26124", name="Kanarbiku")
        AccountingAccountClassification.objects.create(
            organization=organization,
            integration=integration,
            account_code="3000",
            account_name="Revenue",
            category=AccountingAccountClassification.Category.REVENUE,
            reporting_sign=Decimal("-1"),
        )
        AccountingAccountClassification.objects.create(
            organization=organization,
            integration=integration,
            account_code="5000",
            account_name="Materials",
            category=AccountingAccountClassification.Category.MATERIAL_COST,
            reporting_sign=Decimal("1"),
        )
        self._allocation(project, integration, "3000", Decimal("-1000.000000"), "rev")
        self._allocation(project, integration, "5000", Decimal("250.000000"), "cost")
        return organization, integration, project

    def _allocation(self, project, integration, account_code, amount, suffix, batch_date=date(2026, 6, 15)):
        batch = AccountingGLBatch.objects.create(
            organization=project.organization,
            integration=integration,
            external_id=f"mgmt-batch-{suffix}",
            batch_date=batch_date,
            currency_code="EUR",
        )
        entry = AccountingGLEntry.objects.create(
            organization=project.organization,
            integration=integration,
            batch=batch,
            external_id=f"mgmt-entry-{suffix}",
            account_code=account_code,
            account_name=f"Account {account_code}",
        )
        return AccountingGLAllocation.objects.create(
            organization=project.organization,
            integration=integration,
            entry=entry,
            external_id=f"mgmt-allocation-{suffix}",
            dimension_code=project.code,
            dimension_name=project.name,
            amount=amount,
            project=project,
        )

    def _accounting_result(self, project, start=date(2026, 6, 1), end=date(2026, 6, 30)):
        return ProjectFinancialAggregationService().aggregate(
            AggregateProjectFinancialsCommand(project=project, period_start=start, period_end=end)
        )

    def _pool(self, organization, name="Office"):
        return ManagementCostPool.objects.create(organization=organization, name=name, default_strategy=AllocationStrategy.EQUAL)

    def _entry(self, project, amount, *, pool=None, status=VersionStatus.APPROVED, year=2026, month=6, version_number=1):
        pool = pool or self._pool(project.organization)
        period, _created = ManagementAllocationPeriod.objects.get_or_create(organization=project.organization, year=year, month=month)
        version = ManagementAllocationVersion.objects.create(
            period=period,
            pool=pool,
            version_number=version_number,
            status=status,
            approved_at=timezone.now() if status == VersionStatus.APPROVED else None,
            metadata={"source_amount": str(amount)},
        )
        return ManagementAllocationEntry.objects.create(
            version=version,
            project=project,
            percentage=Decimal("100.0000"),
            amount=Decimal(amount),
        )

    def _management_result(self, accounting_result):
        return ProjectManagementFinancialService.build(BuildManagementFinancialsCommand(accounting_result=accounting_result))

    def test_accounting_result_is_unchanged_and_management_result_adds_allocated_cost_once(self):
        organization, _integration, project = self._setup_project()
        self._entry(project, "125.000000", pool=self._pool(organization, "Office"))
        accounting = self._accounting_result(project)

        management = self._management_result(accounting)

        self.assertEqual(accounting.total_cost, Decimal("250.000000"))
        self.assertEqual(accounting.result, Decimal("750.000000"))
        self.assertEqual(management.direct_revenue, Decimal("1000.000000"))
        self.assertEqual(management.direct_cost, Decimal("250.000000"))
        self.assertEqual(management.allocated_management_cost, Decimal("125.000000"))
        self.assertEqual(management.management_total_cost, Decimal("375.000000"))
        self.assertEqual(management.accounting_result, Decimal("750.000000"))
        self.assertEqual(management.management_result, Decimal("625.000000"))

    def test_workspace_project_source_is_allocated_out_for_source_and_in_for_recipient(self):
        organization, _integration, source_project = self._setup_project()
        recipient = Project.objects.create(organization=organization, code="26125", name="Recipient")
        period = ManagementAllocationPeriod.objects.create(organization=organization, year=2026, month=6)
        version = ManagementAllocationVersion.objects.create(
            period=period,
            source_type=AllocationSourceType.WORKSPACE_PROJECT,
            source_project=source_project,
            source_amount_basis=AllocationSourceAmountBasis.PROJECT_DIRECT_COST,
            source_currency="EUR",
            source_period_start=date(2026, 6, 1),
            source_period_end=date(2026, 6, 30),
            version_number=1,
            status=VersionStatus.APPROVED,
            approved_at=timezone.now(),
            metadata={"source_amount": "100.000000"},
        )
        ManagementAllocationEntry.objects.create(
            version=version,
            project=recipient,
            percentage=Decimal("100.0000"),
            amount=Decimal("100.000000"),
        )

        source_management = self._management_result(self._accounting_result(source_project))
        recipient_management = self._management_result(self._accounting_result(recipient))

        self.assertEqual(source_management.management_cost_allocated_in, Decimal("0"))
        self.assertEqual(source_management.management_cost_allocated_out, Decimal("100.000000"))
        self.assertEqual(source_management.net_management_allocation, Decimal("-100.000000"))
        self.assertEqual(source_management.management_total_cost, Decimal("150.000000"))
        self.assertEqual(recipient_management.management_cost_allocated_in, Decimal("100.000000"))
        self.assertEqual(recipient_management.management_cost_allocated_out, Decimal("0"))
        self.assertEqual(recipient_management.management_total_cost, Decimal("100.000000"))

    def test_approved_only_draft_and_superseded_ignored(self):
        organization, _integration, project = self._setup_project()
        self._entry(project, "100.000000", pool=self._pool(organization, "Approved"), status=VersionStatus.APPROVED)
        self._entry(project, "999.000000", pool=self._pool(organization, "Draft"), status=VersionStatus.DRAFT)
        self._entry(project, "888.000000", pool=self._pool(organization, "Old"), status=VersionStatus.SUPERSEDED)

        management = self._management_result(self._accounting_result(project))

        self.assertEqual(management.allocated_management_cost, Decimal("100.000000"))
        self.assertEqual(len(management.allocation_breakdown), 1)

    def test_correct_month_matching(self):
        organization, _integration, project = self._setup_project()
        self._entry(project, "100.000000", pool=self._pool(organization, "June"), year=2026, month=6)
        self._entry(project, "200.000000", pool=self._pool(organization, "July"), year=2026, month=7)

        june = self._management_result(self._accounting_result(project, date(2026, 6, 1), date(2026, 6, 30)))
        both = self._management_result(self._accounting_result(project, date(2026, 6, 1), date(2026, 7, 31)))

        self.assertEqual(june.allocated_management_cost, Decimal("100.000000"))
        self.assertEqual(both.allocated_management_cost, Decimal("300.000000"))
        self.assertEqual(
            [(month.year, month.month, month.allocated_management_cost) for month in both.months],
            [(2026, 6, Decimal("100.000000")), (2026, 7, Decimal("200.000000"))],
        )

    def test_allocation_breakdown_traceability_and_margins(self):
        organization, _integration, project = self._setup_project()
        self._entry(project, "125.000000", pool=self._pool(organization, "Office"))
        self._entry(project, "75.000000", pool=self._pool(organization, "Accounting"))

        management = self._management_result(self._accounting_result(project))

        self.assertEqual(management.allocated_management_cost, Decimal("200.000000"))
        self.assertEqual(management.management_margin, Decimal("55.00"))
        self.assertEqual([item.pool.name for item in management.allocation_breakdown], ["Accounting", "Office"])
        self.assertEqual([item.percentage_of_total for item in management.allocation_breakdown], [Decimal("37.50"), Decimal("62.50")])
        self.assertTrue(management.allocation_breakdown[0].source_version.startswith("v"))
        self.assertIsNotNone(management.allocation_breakdown[0].approved_at)

    def test_warnings_and_organization_isolation(self):
        organization, _integration, project = self._setup_project()
        other_org = create_organization("Other management org")
        other_project = Project.objects.create(organization=other_org, code="26124", name="Other")
        self._entry(other_project, "999.000000", pool=self._pool(other_org))
        self._entry(project, "10.000000", pool=self._pool(organization, "Draft warning"), status=VersionStatus.DRAFT)

        management = self._management_result(self._accounting_result(project))

        self.assertEqual(management.allocated_management_cost, Decimal("0"))
        self.assertIn("no_approved_management_allocations", management.warnings)
        self.assertIn("draft_management_allocation_exists", management.warnings)

    def test_no_database_writes_and_no_proposal_recalculation(self):
        organization, _integration, project = self._setup_project()
        self._entry(project, "100.000000", pool=self._pool(organization))
        accounting = self._accounting_result(project)
        counts = (
            ManagementAllocationPeriod.objects.count(),
            ManagementAllocationVersion.objects.count(),
            ManagementAllocationEntry.objects.count(),
            AccountingGLAllocation.objects.count(),
            AuditEvent.objects.count(),
        )

        with patch("apps.accounting.services.management_allocations.ManagementAllocationProposalService.generate") as generate_mock:
            self._management_result(accounting)

        generate_mock.assert_not_called()
        self.assertEqual(
            counts,
            (
                ManagementAllocationPeriod.objects.count(),
                ManagementAllocationVersion.objects.count(),
                ManagementAllocationEntry.objects.count(),
                AccountingGLAllocation.objects.count(),
                AuditEvent.objects.count(),
            ),
        )


class ProjectFinancialSummaryCommandTests(TestCase):
    def test_command_outputs_empty_result_and_validates_inputs(self):
        project = Project.objects.create(organization=create_organization(), code="26124", name="Kanarbiku")
        output = StringIO()

        call_command("project_financial_summary", project.id, "--start", "2026-06-01", "--end", "2026-06-30", stdout=output)

        self.assertIn("project: 26124 Kanarbiku", output.getvalue())
        self.assertIn("data_quality_status: no_data", output.getvalue())
        with self.assertRaises(CommandError):
            call_command("project_financial_summary", 999999, "--start", "2026-06-01", "--end", "2026-06-30", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("project_financial_summary", project.id, "--start", "bad", "--end", "2026-06-30", stdout=StringIO())

    def test_command_prints_monthly_totals_unclassified_and_passes_currency(self):
        integration = create_merit_integration()
        project = Project.objects.create(organization=integration.organization, code="26124", name="Kanarbiku")
        batch = AccountingGLBatch.objects.create(organization=project.organization, integration=integration, external_id="glb", batch_date=date(2026, 6, 1), currency_code="EUR")
        entry = AccountingGLEntry.objects.create(organization=project.organization, integration=integration, batch=batch, external_id="entry", account_code="7777")
        AccountingGLAllocation.objects.create(organization=project.organization, integration=integration, entry=entry, external_id="alloc", dimension_code=project.code, amount=Decimal("12.000000"), project=project)
        output = StringIO()

        call_command(
            "project_financial_summary",
            project.id,
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-30",
            "--currency",
            "EUR",
            "--show-unclassified",
            stdout=output,
        )

        text = output.getvalue()
        self.assertIn("2026-06: revenue=0 cost=0 result=0 margin=None", text)
        self.assertIn("unclassified_amount: 12.000000", text)
        self.assertIn("currency: EUR", text)

    def test_command_does_not_write_or_call_api(self):
        project = Project.objects.create(organization=create_organization(), code="26124", name="Kanarbiku")
        counts = (AccountingGLBatch.objects.count(), AccountingGLEntry.objects.count(), AccountingGLAllocation.objects.count())

        with patch.object(MeritAPIClient, "request") as request_mock:
            call_command("project_financial_summary", project.id, "--start", "2026-06-01", "--end", "2026-06-30", stdout=StringIO())

        request_mock.assert_not_called()
        self.assertEqual(counts, (AccountingGLBatch.objects.count(), AccountingGLEntry.objects.count(), AccountingGLAllocation.objects.count()))


class GeneralLedgerCacheServiceTests(TestCase):
    def _batch_dto(self, external_id="glb-1", total_amount=Decimal("123.456789"), entries=()):
        return MeritGLBatchDTO(
            external_id=external_id,
            batch_code="GL",
            number="42",
            source_document_id="doc-1",
            document="Purchase invoice",
            batch_date=date(2026, 7, 1),
            currency_code="EUR",
            currency_rate=Decimal("1.00000000"),
            total_amount=total_amount,
            price_includes_vat=True,
            changed_at=datetime(2026, 7, 2, 10, 20, tzinfo=timezone.get_current_timezone()),
            entries=tuple(entries),
            raw={"GLBId": external_id, "TotalAmount": str(total_amount)},
        )

    def _entry_dto(self, entry_id="entry-1", memo="Project work", allocations=()):
        return MeritGLEntryDTO(
            account_code="4000",
            account_name="Revenue",
            memo=memo,
            department_code="D1",
            debit_amount=Decimal("0.000000"),
            debit_currency="EUR",
            credit_amount=Decimal("123.456789"),
            credit_currency="EUR",
            type_id="1",
            batch_id="glb-1",
            entry_id=entry_id,
            tax_id="tax-1",
            tax_percent=Decimal("22.0000"),
            cost_allocations=tuple(allocations),
            raw={"EntryId": entry_id, "Memo": memo},
        )

    def _allocation_dto(self, code="26124", amount=Decimal("123.456789"), multiplier=Decimal("1.00000000")):
        return MeritGLCostAllocationDTO(
            source_type="project",
            code=code,
            name="Kanarbiku",
            multiplier=multiplier,
            amount=amount,
            batch_id="glb-1",
            entry_id="entry-1",
            raw={"Code": code, "Amount": str(amount)},
        )

    def test_upsert_batch_creates_updates_and_detects_unchanged(self):
        integration = create_merit_integration()
        metadata = {"source": "test"}
        dto = self._batch_dto()

        created = GeneralLedgerCacheService.upsert_batch(
            UpsertGLBatchCommand(integration=integration, dto=dto, metadata=metadata)
        )
        unchanged = GeneralLedgerCacheService.upsert_batch(UpsertGLBatchCommand(integration=integration, dto=dto))
        updated = GeneralLedgerCacheService.upsert_batch(
            UpsertGLBatchCommand(integration=integration, dto=self._batch_dto(total_amount=Decimal("200.000000")))
        )

        self.assertTrue(created.created)
        self.assertTrue(unchanged.unchanged)
        self.assertTrue(updated.updated)
        self.assertEqual(AccountingGLBatch.objects.count(), 1)
        self.assertEqual(metadata, {"source": "test"})

    def test_upsert_batch_preserves_raw_input_and_synced_timestamps(self):
        integration = create_merit_integration()
        dto = self._batch_dto()
        original_raw = deepcopy(dto.raw)

        created = GeneralLedgerCacheService.upsert_batch(UpsertGLBatchCommand(integration=integration, dto=dto))
        first_synced_at = created.object.first_synced_at
        updated = GeneralLedgerCacheService.upsert_batch(
            UpsertGLBatchCommand(integration=integration, dto=self._batch_dto(total_amount=Decimal("200.000000")))
        )

        self.assertEqual(dto.raw, original_raw)
        self.assertEqual(updated.object.first_synced_at, first_synced_at)
        self.assertGreaterEqual(updated.object.last_synced_at, first_synced_at)
        self.assertEqual(updated.object.source_changed_at, self._batch_dto().changed_at)
        self.assertEqual(updated.object.total_amount, Decimal("200.000000"))

    def test_upsert_batch_does_not_call_api(self):
        integration = create_merit_integration()

        with patch.object(MeritAPIClient, "request") as request_mock:
            GeneralLedgerCacheService.upsert_batch(UpsertGLBatchCommand(integration=integration, dto=self._batch_dto()))

        request_mock.assert_not_called()

    def test_upsert_entry_provider_id_and_fallback_are_idempotent(self):
        batch = self._persisted_batch()

        provider_result = GeneralLedgerCacheService.upsert_entry(
            UpsertGLEntryCommand(batch=batch, dto=self._entry_dto(entry_id="entry-1"), sequence=1)
        )
        fallback_dto = self._entry_dto(entry_id="")
        fallback_first = GeneralLedgerCacheService.upsert_entry(
            UpsertGLEntryCommand(batch=batch, dto=fallback_dto, sequence=2)
        )
        fallback_second = GeneralLedgerCacheService.upsert_entry(
            UpsertGLEntryCommand(batch=batch, dto=fallback_dto, sequence=2)
        )

        self.assertEqual(provider_result.object.external_id, "entry-1")
        self.assertTrue(fallback_first.created)
        self.assertTrue(fallback_second.unchanged)
        self.assertEqual(AccountingGLEntry.objects.count(), 2)

    def test_upsert_entry_updates_changed_fields_and_preserves_precision(self):
        batch = self._persisted_batch()
        created = GeneralLedgerCacheService.upsert_entry(
            UpsertGLEntryCommand(batch=batch, dto=self._entry_dto(memo="Old"), sequence=1)
        )

        updated = GeneralLedgerCacheService.upsert_entry(
            UpsertGLEntryCommand(batch=batch, dto=self._entry_dto(memo="New"), sequence=1)
        )

        self.assertTrue(created.created)
        self.assertTrue(updated.updated)
        self.assertEqual(updated.object.memo, "New")
        self.assertEqual(updated.object.credit_amount, Decimal("123.456789"))

    def test_upsert_entry_invalid_organization_relationship_rejected(self):
        batch = self._persisted_batch()
        batch.organization = create_organization("Wrong Org")

        with self.assertRaises(ValueError):
            GeneralLedgerCacheService.upsert_entry(UpsertGLEntryCommand(batch=batch, dto=self._entry_dto()))

    def test_upsert_allocation_links_exact_dimension_and_project(self):
        entry = self._persisted_entry()
        AccountingDimension.objects.create(
            organization=entry.organization,
            integration=entry.integration,
            provider=entry.integration.provider,
            code="26124",
            name="Kanarbiku",
            dimension_type=AccountingDimension.DimensionType.PROJECT,
        )
        Project.objects.create(organization=entry.organization, code="26124", name="Kanarbiku")

        result = GeneralLedgerCacheService.upsert_allocation(
            UpsertGLAllocationCommand(entry=entry, dto=self._allocation_dto(), sequence=1)
        )

        self.assertIsNotNone(result.object.accounting_dimension)
        self.assertIsNotNone(result.object.project)
        self.assertEqual(result.object.project.code, "26124")

    def test_upsert_allocation_no_fuzzy_match_and_missing_project_remains_null(self):
        entry = self._persisted_entry()
        Project.objects.create(organization=entry.organization, code="26124X", name="Almost")

        result = GeneralLedgerCacheService.upsert_allocation(
            UpsertGLAllocationCommand(entry=entry, dto=self._allocation_dto(code="26124"), sequence=1)
        )

        self.assertIsNone(result.object.project)
        self.assertIsNone(result.object.accounting_dimension)

    def test_upsert_allocation_changed_amount_and_multiple_same_code_not_collapsed(self):
        entry = self._persisted_entry()
        first = GeneralLedgerCacheService.upsert_allocation(
            UpsertGLAllocationCommand(entry=entry, dto=self._allocation_dto(amount=Decimal("50.000000")), sequence=1)
        )
        second = GeneralLedgerCacheService.upsert_allocation(
            UpsertGLAllocationCommand(entry=entry, dto=self._allocation_dto(amount=Decimal("50.000000")), sequence=2)
        )
        updated = GeneralLedgerCacheService.upsert_allocation(
            UpsertGLAllocationCommand(entry=entry, dto=self._allocation_dto(amount=Decimal("60.000000")), sequence=1)
        )

        self.assertTrue(first.created)
        self.assertTrue(second.created)
        self.assertTrue(updated.updated)
        self.assertEqual(AccountingGLAllocation.objects.count(), 2)

    def test_upsert_allocation_metadata_and_raw_not_mutated(self):
        entry = self._persisted_entry()
        dto = self._allocation_dto()
        raw = deepcopy(dto.raw)
        metadata = {"sync": "manual"}

        GeneralLedgerCacheService.upsert_allocation(
            UpsertGLAllocationCommand(entry=entry, dto=dto, sequence=1, metadata=metadata)
        )

        self.assertEqual(dto.raw, raw)
        self.assertEqual(metadata, {"sync": "manual"})

    def test_persist_batch_tree_creates_and_then_returns_unchanged(self):
        integration = create_merit_integration()
        allocation = self._allocation_dto()
        entry = self._entry_dto(allocations=(allocation,))
        batch = self._batch_dto(entries=(entry,))

        first = GeneralLedgerCacheService.persist_batch_tree(integration, batch)
        second = GeneralLedgerCacheService.persist_batch_tree(integration, batch)

        self.assertEqual(first["created_count"], 3)
        self.assertEqual(second["unchanged_count"], 3)
        self.assertEqual(AccountingGLBatch.objects.count(), 1)
        self.assertEqual(AccountingGLEntry.objects.count(), 1)
        self.assertEqual(AccountingGLAllocation.objects.count(), 1)

    def test_persist_batch_tree_updates_only_changed_objects(self):
        integration = create_merit_integration()
        initial = self._batch_dto(entries=(self._entry_dto(memo="Old", allocations=(self._allocation_dto(),)),))
        changed = self._batch_dto(entries=(self._entry_dto(memo="New", allocations=(self._allocation_dto(),)),))

        GeneralLedgerCacheService.persist_batch_tree(integration, initial)
        result = GeneralLedgerCacheService.persist_batch_tree(integration, changed)

        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["unchanged_count"], 2)

    def test_persist_batch_tree_rolls_back_on_allocation_failure(self):
        integration = create_merit_integration()
        batch = self._batch_dto(entries=(self._entry_dto(allocations=(self._allocation_dto(),)),))

        with patch.object(GeneralLedgerCacheService, "upsert_allocation", side_effect=RuntimeError("allocation failed")):
            with self.assertRaises(RuntimeError):
                GeneralLedgerCacheService.persist_batch_tree(integration, batch)

        self.assertFalse(AccountingGLBatch.objects.exists())
        self.assertFalse(AccountingGLEntry.objects.exists())

    def test_persist_batch_tree_does_not_create_project_dimension_or_audit(self):
        integration = create_merit_integration()
        batch = self._batch_dto(entries=(self._entry_dto(allocations=(self._allocation_dto(),)),))

        GeneralLedgerCacheService.persist_batch_tree(integration, batch)

        self.assertFalse(Project.objects.exists())
        self.assertFalse(AccountingDimension.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(object_type__contains="GL").exists())

    def _persisted_batch(self):
        integration = create_merit_integration()
        return GeneralLedgerCacheService.upsert_batch(
            UpsertGLBatchCommand(integration=integration, dto=self._batch_dto())
        ).object

    def _persisted_entry(self):
        batch = self._persisted_batch()
        return GeneralLedgerCacheService.upsert_entry(
            UpsertGLEntryCommand(batch=batch, dto=self._entry_dto(), sequence=1)
        ).object


class FakeGLAPIClient:
    def __init__(self, integration, responses=None, side_effects=None):
        self.integration = integration
        self.responses = list(responses or [])
        self.side_effects = list(side_effects or [])
        self.calls = []

    def get_gl_batches_full(self, period_start, period_end, **kwargs):
        self.calls.append((period_start, period_end, kwargs))
        if self.side_effects:
            effect = self.side_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect
        if self.responses:
            return self.responses.pop(0)
        return []


class GeneralLedgerSyncServiceTests(TestCase):
    def _allocation_dto(self, code="26124", amount=Decimal("100.000000")):
        return MeritGLCostAllocationDTO(
            source_type="project",
            code=code,
            name="Kanarbiku",
            multiplier=Decimal("1.00000000"),
            amount=amount,
            batch_id="glb-1",
            entry_id="entry-1",
            raw={"Code": code},
        )

    def _entry_dto(self, entry_id="entry-1", allocations=()):
        return MeritGLEntryDTO(
            account_code="4000",
            account_name="Revenue",
            memo="Memo",
            department_code="",
            debit_amount=Decimal("0.000000"),
            debit_currency="EUR",
            credit_amount=Decimal("100.000000"),
            credit_currency="EUR",
            type_id="1",
            batch_id="glb-1",
            entry_id=entry_id,
            tax_id="",
            tax_percent=None,
            cost_allocations=tuple(allocations),
            raw={"EntryId": entry_id},
        )

    def _batch_dto(self, external_id="glb-1", batch_date=date(2026, 1, 1), entries=()):
        return MeritGLBatchDTO(
            external_id=external_id,
            batch_code="GL",
            number=external_id,
            source_document_id="",
            document="",
            batch_date=batch_date,
            currency_code="EUR",
            currency_rate=Decimal("1.00000000"),
            total_amount=Decimal("100.000000"),
            price_includes_vat=False,
            changed_at=datetime(2026, 1, 2, 10, 0, tzinfo=timezone.get_current_timezone()),
            entries=tuple(entries),
            raw={"GLBId": external_id},
        )

    def _service(self, client):
        return GeneralLedgerSyncService(api_client_factory=lambda integration: client)

    def _command(self, integration, start=date(2026, 1, 1), end=date(2026, 1, 31), **kwargs):
        defaults = {"integration": integration, "period_start": start, "period_end": end}
        defaults.update(kwargs)
        return SyncGeneralLedgerCommand(**defaults)

    def test_split_period_single_day_exact_31_days_and_32_days(self):
        self.assertEqual(GeneralLedgerSyncService.split_period(date(2026, 1, 1), date(2026, 1, 1)), [(date(2026, 1, 1), date(2026, 1, 1))])
        self.assertEqual(GeneralLedgerSyncService.split_period(date(2026, 1, 1), date(2026, 1, 31)), [(date(2026, 1, 1), date(2026, 1, 31))])
        self.assertEqual(
            GeneralLedgerSyncService.split_period(date(2026, 1, 1), date(2026, 2, 1)),
            [(date(2026, 1, 1), date(2026, 1, 31)), (date(2026, 2, 1), date(2026, 2, 1))],
        )

    def test_split_period_multi_month_leap_year_no_gaps_or_overlaps(self):
        chunks = GeneralLedgerSyncService.split_period(date(2024, 2, 1), date(2024, 3, 5))

        self.assertEqual(chunks, [(date(2024, 2, 1), date(2024, 3, 2)), (date(2024, 3, 3), date(2024, 3, 5))])
        self.assertEqual(chunks[0][1] + timedelta(days=1), chunks[1][0])

    def test_split_period_reversed_range_rejected(self):
        with self.assertRaises(ValueError):
            GeneralLedgerSyncService.split_period(date(2026, 2, 1), date(2026, 1, 1))

    def test_successful_sync_creates_state_run_calls_api_and_persists(self):
        integration = create_merit_integration()
        allocation = self._allocation_dto()
        entry = self._entry_dto(allocations=(allocation,))
        batch = self._batch_dto(entries=(entry,))
        client = FakeGLAPIClient(integration, responses=[[batch]])
        metadata = {"run": "manual"}

        result = self._service(client).sync(self._command(integration, metadata=metadata))

        self.assertTrue(result.synced)
        self.assertFalse(result.partial)
        self.assertEqual(result.requested_chunk_count, 1)
        self.assertEqual(result.completed_chunk_count, 1)
        self.assertEqual(result.discovered_batch_count, 1)
        self.assertEqual(result.created_count, 3)
        self.assertEqual(AccountingGLBatch.objects.count(), 1)
        self.assertEqual(AccountingGLEntry.objects.count(), 1)
        self.assertEqual(AccountingGLAllocation.objects.count(), 1)
        self.assertEqual(client.calls[0][2]["with_lines"], True)
        self.assertEqual(client.calls[0][2]["with_cost_allocations"], True)
        self.assertEqual(client.calls[0][2]["date_type"], MeritGLDateType.DOCUMENT_DATE)
        self.assertEqual(metadata, {"run": "manual"})
        state = AccountingSyncState.objects.get(integration=integration, source_type=AccountingSyncState.SourceType.GL)
        self.assertEqual(state.sync_status, AccountingSyncState.SyncStatus.IDLE)
        self.assertEqual(state.last_completed_period_end, date(2026, 1, 31))
        self.assertEqual(result.sync_run.status, AccountingSyncRun.Status.COMPLETED)

    def test_multiple_chunks_called_in_order_and_batches_sorted(self):
        integration = create_merit_integration()
        first = self._batch_dto("glb-b", date(2026, 1, 2))
        second = self._batch_dto("glb-a", date(2026, 1, 1))
        third = self._batch_dto("glb-c", date(2026, 2, 1))
        client = FakeGLAPIClient(integration, responses=[[first, second], [third]])

        result = self._service(client).sync(self._command(integration, end=date(2026, 2, 1)))

        self.assertEqual([call[0:2] for call in client.calls], [(date(2026, 1, 1), date(2026, 1, 31)), (date(2026, 2, 1), date(2026, 2, 1))])
        self.assertEqual([batch.external_id for batch in result.batches], ["glb-a", "glb-b", "glb-c"])
        self.assertEqual(result.completed_chunk_count, 2)

    def test_initial_import_completes_initial_import_status(self):
        integration = create_merit_integration()
        client = FakeGLAPIClient(integration, responses=[[]])

        result = self._service(client).sync(
            self._command(integration, mode=AccountingSyncRun.Mode.INITIAL_BACKFILL, initial_import=True)
        )
        result.sync_state.refresh_from_db()

        self.assertEqual(result.sync_state.initial_import_status, AccountingSyncState.InitialImportStatus.COMPLETED)

    def test_idempotent_second_run_reports_unchanged(self):
        integration = create_merit_integration()
        batch = self._batch_dto(entries=(self._entry_dto(allocations=(self._allocation_dto(),)),))

        first = self._service(FakeGLAPIClient(integration, responses=[[batch]])).sync(self._command(integration))
        second = self._service(FakeGLAPIClient(integration, responses=[[batch]])).sync(self._command(integration))

        self.assertEqual(first.created_count, 3)
        self.assertEqual(second.unchanged_count, 3)
        self.assertEqual(AccountingGLBatch.objects.count(), 1)

    def test_period_resync_does_not_move_forward_cursor_backwards(self):
        integration = create_merit_integration()
        state = AccountingSyncStateService.get_or_create(
            GetOrCreateAccountingSyncStateCommand(integration=integration, source_type=AccountingSyncState.SourceType.GL)
        )
        state.cursor_value = "2026-12-31"
        state.last_completed_period_start = date(2026, 12, 1)
        state.last_completed_period_end = date(2026, 12, 31)
        state.save()

        self._service(FakeGLAPIClient(integration, responses=[[]])).sync(
            self._command(integration, mode=AccountingSyncRun.Mode.PERIOD_RESYNC)
        )
        state.refresh_from_db()

        self.assertEqual(state.cursor_value, "2026-12-31")
        self.assertEqual(state.last_completed_period_end, date(2026, 12, 31))

    def test_second_chunk_api_failure_preserves_first_chunk_and_marks_partial(self):
        integration = create_merit_integration()
        first_batch = self._batch_dto("glb-1")
        secret = integration.encrypted_secret_placeholder
        client = FakeGLAPIClient(integration, side_effects=[[first_batch], AccountingConnectionError(f"failed {secret}")])

        with self.assertRaises(AccountingConnectionError):
            self._service(client).sync(self._command(integration, end=date(2026, 2, 1)))

        self.assertTrue(AccountingGLBatch.objects.filter(external_id="glb-1").exists())
        state = AccountingSyncState.objects.get(integration=integration, source_type=AccountingSyncState.SourceType.GL)
        run = state.runs.latest("id")
        self.assertEqual(run.status, AccountingSyncRun.Status.PARTIAL)
        self.assertNotIn(secret, run.safe_error)
        self.assertEqual(state.last_completed_period_end, date(2026, 1, 31))

    def test_batch_failure_preserves_earlier_batches_and_does_not_complete_chunk(self):
        integration = create_merit_integration()
        batches = [self._batch_dto("glb-1"), self._batch_dto("glb-2")]
        cache_mock = type("CacheMock", (), {})()
        cache_mock.calls = []

        def persist_batch_tree(integration_arg, batch_dto, sync_run=None, metadata=None):
            cache_mock.calls.append(batch_dto.external_id)
            if batch_dto.external_id == "glb-2":
                raise RuntimeError("batch failed")
            return GeneralLedgerCacheService.persist_batch_tree(integration_arg, batch_dto, sync_run=sync_run, metadata=metadata)

        cache_mock.persist_batch_tree = persist_batch_tree

        with self.assertRaises(RuntimeError):
            GeneralLedgerSyncService(
                api_client_factory=lambda integration_arg: FakeGLAPIClient(integration_arg, responses=[batches]),
                cache_service=cache_mock,
            ).sync(self._command(integration))

        self.assertEqual(cache_mock.calls, ["glb-1", "glb-2"])
        self.assertTrue(AccountingGLBatch.objects.filter(external_id="glb-1").exists())
        state = AccountingSyncState.objects.get(integration=integration, source_type=AccountingSyncState.SourceType.GL)
        self.assertIsNone(state.last_completed_period_end)

    def test_first_api_failure_creates_no_gl_records_and_marks_failed(self):
        integration = create_merit_integration()
        client = FakeGLAPIClient(integration, side_effects=[AccountingAuthenticationError("auth failed")])

        with self.assertRaises(AccountingAuthenticationError):
            self._service(client).sync(self._command(integration))

        self.assertFalse(AccountingGLBatch.objects.exists())
        state = AccountingSyncState.objects.get(integration=integration, source_type=AccountingSyncState.SourceType.GL)
        run = state.runs.latest("id")
        self.assertEqual(run.status, AccountingSyncRun.Status.FAILED)
        self.assertEqual(state.sync_status, AccountingSyncState.SyncStatus.FAILED)
        self.assertIsNone(state.last_completed_period_end)

    def test_connection_and_rate_limit_errors_propagate(self):
        integration = create_merit_integration()
        for error in [AccountingConnectionError("connection"), AccountingRateLimitError("rate limit")]:
            with self.assertRaises(error.__class__):
                self._service(FakeGLAPIClient(integration, side_effects=[error])).sync(self._command(integration))

    def test_mode_date_validation_and_forwarding(self):
        integration = create_merit_integration()
        client = FakeGLAPIClient(integration, responses=[[]])

        self._service(client).sync(self._command(integration, mode=AccountingSyncRun.Mode.INCREMENTAL, date_type=MeritGLDateType.CHANGED_DATE))

        self.assertEqual(client.calls[0][2]["date_type"], MeritGLDateType.CHANGED_DATE)
        with self.assertRaises(ValueError):
            self._service(FakeGLAPIClient(integration, responses=[[]])).sync(self._command(integration, mode="bad_mode"))
        with self.assertRaises(ValueError):
            self._service(FakeGLAPIClient(integration, responses=[[]])).sync(self._command(integration, date_type="posting_date"))

    def test_inactive_and_non_merit_integrations_rejected(self):
        inactive = create_merit_integration()
        inactive.is_active = False
        inactive.save()
        other = AccountingIntegration.objects.create(
            organization=create_organization("Other Provider Org"),
            provider=AccountingIntegration.Provider.XERO,
            display_name="Xero",
            is_active=True,
        )

        with self.assertRaises(ValueError):
            self._service(FakeGLAPIClient(inactive, responses=[[]])).sync(self._command(inactive))
        with self.assertRaises(ValueError):
            self._service(FakeGLAPIClient(other, responses=[[]])).sync(self._command(other))


class SyncGeneralLedgerCommandTests(TestCase):
    @patch("apps.accounting.management.commands.sync_general_ledger.GeneralLedgerSyncService")
    def test_management_command_valid_args_call_service_and_print_summary(self, service_mock):
        integration = create_merit_integration()
        state = AccountingSyncState.objects.create(
            organization=integration.organization,
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
        )
        run = AccountingSyncRun.objects.create(
            organization=integration.organization,
            integration=integration,
            sync_state=state,
            source_type=AccountingSyncState.SourceType.GL,
        )
        service_mock.return_value.sync.return_value = SyncGeneralLedgerResult(
            integration=integration,
            sync_state=state,
            sync_run=run,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            requested_chunk_count=1,
            completed_chunk_count=1,
            discovered_batch_count=2,
            created_count=3,
            updated_count=4,
            unchanged_count=5,
            failed_count=0,
            batches=[],
            partial=False,
            synced=True,
            metadata={},
        )
        output = StringIO()

        call_command("sync_general_ledger", integration.id, "--start", "2026-01-01", "--end", "2026-01-31", stdout=output)

        service_mock.return_value.sync.assert_called_once()
        self.assertIn("discovered_batch_count: 2", output.getvalue())
        self.assertIn("synced: True", output.getvalue())

    def test_management_command_invalid_integration_and_dates(self):
        with self.assertRaises(CommandError):
            call_command("sync_general_ledger", 999999, "--start", "2026-01-01", "--end", "2026-01-31", stdout=StringIO())

        integration = create_merit_integration()
        with self.assertRaises(CommandError):
            call_command("sync_general_ledger", integration.id, "--start", "bad-date", "--end", "2026-01-31", stdout=StringIO())

    @patch("apps.accounting.management.commands.sync_general_ledger.GeneralLedgerSyncService")
    def test_management_command_service_error_safe_and_debug_omits_secret(self, service_mock):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = "top-secret"
        integration.save()
        service_mock.return_value.sync.side_effect = RuntimeError("failed top-secret")

        with self.assertRaises(CommandError) as safe_error:
            call_command("sync_general_ledger", integration.id, "--start", "2026-01-01", "--end", "2026-01-31", stdout=StringIO())
        self.assertNotIn("top-secret", str(safe_error.exception))

        with self.assertRaises(CommandError) as debug_error:
            call_command(
                "sync_general_ledger",
                integration.id,
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-31",
                "--debug",
                stdout=StringIO(),
            )
        self.assertIn("RuntimeError", str(debug_error.exception))
        self.assertNotIn("top-secret", str(debug_error.exception))


class GeneralLedgerVerificationServiceTests(TestCase):
    def _batch(self, integration, external_id="glb-1", batch_date=date(2026, 6, 15), currency="EUR"):
        return AccountingGLBatch.objects.create(
            organization=integration.organization,
            integration=integration,
            external_id=external_id,
            batch_code="GL",
            number=external_id,
            batch_date=batch_date,
            currency_code=currency,
            total_amount=Decimal("100.000000"),
            raw_data={"GLBId": external_id},
        )

    def _entry(self, batch, external_id="entry-1", account_code="4000", debit=Decimal("100.000000"), credit=Decimal("0.000000"), debit_currency="EUR", credit_currency="EUR"):
        return AccountingGLEntry.objects.create(
            organization=batch.organization,
            integration=batch.integration,
            batch=batch,
            external_id=external_id,
            account_code=account_code,
            account_name="Account",
            debit_amount=debit,
            debit_currency=debit_currency,
            credit_amount=credit,
            credit_currency=credit_currency,
            raw_data={"EntryId": external_id},
        )

    def _allocation(self, entry, code="26124", amount=Decimal("100.000000"), project=None, dimension=None, external_id="alloc-1"):
        return AccountingGLAllocation.objects.create(
            organization=entry.organization,
            integration=entry.integration,
            entry=entry,
            external_id=external_id,
            source_type="project",
            dimension_code=code,
            dimension_name="Kanarbiku" if code else "",
            dimension_type="project",
            amount=amount,
            project=project,
            accounting_dimension=dimension,
            raw_data={"Code": code},
        )

    def _verify(self, integration, metadata=None, sample_size=10):
        return GeneralLedgerVerificationService.verify(
            VerifyGeneralLedgerCommand(
                integration=integration,
                period_start=date(2026, 6, 1),
                period_end=date(2026, 6, 30),
                sample_size=sample_size,
                metadata=metadata,
            )
        )

    def test_empty_period(self):
        integration = create_merit_integration()

        result = self._verify(integration)

        self.assertEqual(result.batch_count, 0)
        self.assertEqual(result.entry_count, 0)
        self.assertEqual(result.allocation_count, 0)
        self.assertEqual(result.total_debit, Decimal("0"))

    def test_one_complete_batch_tree_with_decimal_totals_and_balance(self):
        integration = create_merit_integration()
        batch = self._batch(integration)
        self._entry(batch, "entry-debit", debit=Decimal("100.123456"), credit=Decimal("0.000000"))
        self._entry(batch, "entry-credit", debit=Decimal("0.000000"), credit=Decimal("100.123456"))

        result = self._verify(integration)

        self.assertEqual(result.batch_count, 1)
        self.assertEqual(result.entry_count, 2)
        self.assertEqual(result.total_debit, Decimal("100.123456"))
        self.assertEqual(result.total_credit, Decimal("100.123456"))
        self.assertEqual(result.balance_difference, Decimal("0.000000"))

    def test_multiple_batches_counted(self):
        integration = create_merit_integration()
        self._batch(integration, "glb-1")
        self._batch(integration, "glb-2")

        result = self._verify(integration)

        self.assertEqual(result.batch_count, 2)

    def test_non_zero_balance_warning(self):
        integration = create_merit_integration()
        batch = self._batch(integration)
        self._entry(batch, debit=Decimal("100.000000"), credit=Decimal("0.000000"))

        result = self._verify(integration)

        self.assertTrue(any("Debit and credit totals differ" in warning for warning in result.warnings))

    def test_mixed_currencies_warning(self):
        integration = create_merit_integration()
        batch = self._batch(integration, currency="USD")
        self._entry(batch, debit_currency="EUR", credit_currency="EUR")

        result = self._verify(integration)

        self.assertTrue(any("Multiple currencies" in warning for warning in result.warnings))

    def test_project_linked_allocation(self):
        integration = create_merit_integration()
        project = Project.objects.create(organization=integration.organization, code="26124", name="Kanarbiku")
        dimension = AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            code="26124",
            name="Kanarbiku",
        )
        entry = self._entry(self._batch(integration))
        self._allocation(entry, project=project, dimension=dimension)

        result = self._verify(integration)

        self.assertEqual(result.linked_project_count, 1)
        self.assertEqual(result.metadata["link_quality"]["linked_both_count"], 1)
        self.assertEqual(result.metadata["samples"]["project_linked"][0]["project_code"], "26124")

    def test_unlinked_and_blank_allocations(self):
        integration = create_merit_integration()
        entry = self._entry(self._batch(integration))
        self._allocation(entry, code="99999", external_id="alloc-unlinked")
        self._allocation(entry, code="", external_id="alloc-blank")

        result = self._verify(integration)

        self.assertEqual(result.unlinked_allocation_count, 2)
        self.assertEqual(result.metadata["link_quality"]["blank_dimension_codes"], 1)
        self.assertIn("99999", result.distinct_unlinked_codes)

    def test_allocation_linked_to_accounting_dimension_only(self):
        integration = create_merit_integration()
        dimension = AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            code="26124",
            name="Kanarbiku",
        )
        entry = self._entry(self._batch(integration))
        self._allocation(entry, dimension=dimension)

        result = self._verify(integration)

        self.assertEqual(result.metadata["link_quality"]["linked_dimension_count"], 1)
        self.assertEqual(result.linked_project_count, 0)

    def test_organization_consistency_detection(self):
        integration = create_merit_integration()
        other_project = Project.objects.create(organization=create_organization("Other Org"), code="26124", name="Other")
        entry = self._entry(self._batch(integration))
        self._allocation(entry, project=other_project)

        result = self._verify(integration)

        self.assertTrue(result.critical_errors)
        self.assertEqual(result.metadata["data_quality"]["project_organization_mismatches"], 1)

    def test_missing_account_and_zero_value_entry_warnings_are_reported_as_data_quality(self):
        integration = create_merit_integration()
        batch = self._batch(integration)
        self._entry(batch, account_code="", debit=Decimal("0.000000"), credit=Decimal("0.000000"))

        result = self._verify(integration)

        self.assertEqual(result.metadata["data_quality"]["entries_missing_account_code"], 1)
        self.assertEqual(result.metadata["data_quality"]["entries_with_zero_debit_and_credit"], 1)

    def test_duplicate_identity_query_behavior_zero_with_constraints(self):
        integration = create_merit_integration()
        batch = self._batch(integration)
        entry = self._entry(batch)
        self._allocation(entry)

        result = self._verify(integration)

        self.assertEqual(result.metadata["identity"]["batch_duplicates"], 0)
        self.assertEqual(result.metadata["identity"]["entry_duplicates"], 0)
        self.assertEqual(result.metadata["identity"]["allocation_duplicates"], 0)

    def test_metadata_not_mutated(self):
        integration = create_merit_integration()
        metadata = {"source": {"operator": "test"}}
        original = {"source": {"operator": "test"}}

        result = self._verify(integration, metadata=metadata)
        result.metadata["input_metadata"]["source"]["operator"] = "changed"

        self.assertEqual(metadata, original)

    def test_no_database_writes_and_no_api_calls(self):
        integration = create_merit_integration()
        batch = self._batch(integration)
        self._entry(batch)
        counts_before = (
            AccountingGLBatch.objects.count(),
            AccountingGLEntry.objects.count(),
            AccountingGLAllocation.objects.count(),
        )

        with patch.object(MeritAPIClient, "get_gl_batches_full") as api_mock:
            self._verify(integration)

        api_mock.assert_not_called()
        self.assertEqual(
            counts_before,
            (
                AccountingGLBatch.objects.count(),
                AccountingGLEntry.objects.count(),
                AccountingGLAllocation.objects.count(),
            ),
        )


class VerifyGeneralLedgerSyncCommandTests(TestCase):
    def _sync_objects(self, integration):
        state, _ = AccountingSyncState.objects.get_or_create(
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
            defaults={
                "organization": integration.organization,
            },
        )
        run = AccountingSyncRun.objects.create(
            organization=integration.organization,
            integration=integration,
            sync_state=state,
            source_type=AccountingSyncState.SourceType.GL,
            requested_period_start=date(2026, 6, 1),
            requested_period_end=date(2026, 6, 30),
        )
        return state, run

    def _sync_result(self, integration):
        state, run = self._sync_objects(integration)
        return SyncGeneralLedgerResult(
            integration=integration,
            sync_state=state,
            sync_run=run,
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            requested_chunk_count=1,
            completed_chunk_count=1,
            discovered_batch_count=0,
            created_count=0,
            updated_count=0,
            unchanged_count=0,
            failed_count=0,
            batches=[],
            partial=False,
            synced=True,
        )

    def test_missing_integration_invalid_dates_and_reversed_dates(self):
        with self.assertRaises(CommandError):
            call_command("verify_general_ledger_sync", 999999, "--start", "2026-06-01", "--end", "2026-06-30", stdout=StringIO())

        integration = create_merit_integration()
        with self.assertRaises(CommandError):
            call_command("verify_general_ledger_sync", integration.id, "--start", "bad", "--end", "2026-06-30", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("verify_general_ledger_sync", integration.id, "--start", "2026-07-01", "--end", "2026-06-30", stdout=StringIO())

    @patch("apps.accounting.management.commands.verify_general_ledger_sync.GeneralLedgerSyncService")
    def test_default_read_only_verification_does_not_call_sync(self, service_mock):
        integration = create_merit_integration()
        output = StringIO()

        call_command("verify_general_ledger_sync", integration.id, "--start", "2026-06-01", "--end", "2026-06-30", stdout=output)

        service_mock.return_value.sync.assert_not_called()
        self.assertIn("General ledger verification", output.getvalue())
        self.assertIn("gl_batches: 0", output.getvalue())

    @patch("apps.accounting.management.commands.verify_general_ledger_sync.GeneralLedgerSyncService")
    def test_run_sync_calls_general_ledger_sync_service(self, service_mock):
        integration = create_merit_integration()
        service_mock.return_value.sync.return_value = self._sync_result(integration)
        output = StringIO()

        call_command("verify_general_ledger_sync", integration.id, "--start", "2026-06-01", "--end", "2026-06-30", "--run-sync", stdout=output)

        service_mock.return_value.sync.assert_called_once()
        self.assertIn("sync_result:", output.getvalue())

    @patch("apps.accounting.management.commands.verify_general_ledger_sync.GeneralLedgerSyncService")
    def test_repeat_sync_calls_sync_twice_and_reports_idempotency(self, service_mock):
        integration = create_merit_integration()
        service_mock.return_value.sync.side_effect = [self._sync_result(integration), self._sync_result(integration)]
        output = StringIO()

        call_command(
            "verify_general_ledger_sync",
            integration.id,
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-30",
            "--run-sync",
            "--repeat-sync",
            stdout=output,
        )

        self.assertEqual(service_mock.return_value.sync.call_count, 2)
        self.assertIn("idempotency:", output.getvalue())

    def test_repeat_sync_requires_run_sync(self):
        integration = create_merit_integration()

        with self.assertRaises(CommandError):
            call_command("verify_general_ledger_sync", integration.id, "--start", "2026-06-01", "--end", "2026-06-30", "--repeat-sync", stdout=StringIO())

    def test_show_unlinked_prints_sample_and_sample_size_respected(self):
        integration = create_merit_integration()
        batch = AccountingGLBatch.objects.create(
            organization=integration.organization,
            integration=integration,
            external_id="glb-1",
            batch_date=date(2026, 6, 1),
            raw_data={"GLBId": "glb-1"},
        )
        entry = AccountingGLEntry.objects.create(
            organization=integration.organization,
            integration=integration,
            batch=batch,
            external_id="entry-1",
            account_code="4000",
            raw_data={"EntryId": "entry-1"},
        )
        AccountingGLAllocation.objects.create(
            organization=integration.organization,
            integration=integration,
            entry=entry,
            external_id="alloc-1",
            dimension_code="99999",
            amount=Decimal("12.000000"),
            raw_data={"Code": "99999"},
        )
        AccountingGLAllocation.objects.create(
            organization=integration.organization,
            integration=integration,
            entry=entry,
            external_id="alloc-2",
            dimension_code="88888",
            amount=Decimal("12.000000"),
            raw_data={"Code": "88888"},
        )
        output = StringIO()

        call_command(
            "verify_general_ledger_sync",
            integration.id,
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-30",
            "--show-unlinked",
            "--sample-size",
            "1",
            stdout=output,
        )

        text = output.getvalue()
        self.assertIn("unlinked_allocations:", text)
        self.assertIn("dimension_code=99999", text)
        self.assertNotIn("dimension_code=88888", text)

    def test_safe_summary_printed_and_secret_never_appears(self):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = "secret-value"
        integration.save()
        output = StringIO()

        call_command("verify_general_ledger_sync", integration.id, "--start", "2026-06-01", "--end", "2026-06-30", stdout=output)

        text = output.getvalue()
        self.assertIn("diagnostic_source_totals:", text)
        self.assertNotIn("secret-value", text)

    @patch("apps.accounting.management.commands.verify_general_ledger_sync.GeneralLedgerSyncService")
    def test_sync_error_handled_safely(self, service_mock):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = "top-secret"
        integration.save()
        service_mock.return_value.sync.side_effect = RuntimeError("failed top-secret")

        with self.assertRaises(CommandError) as error:
            call_command("verify_general_ledger_sync", integration.id, "--start", "2026-06-01", "--end", "2026-06-30", "--run-sync", stdout=StringIO())

        self.assertNotIn("top-secret", str(error.exception))

    @patch("apps.accounting.management.commands.verify_general_ledger_sync.GeneralLedgerSyncService")
    def test_no_real_merit_api_calls_in_command_tests(self, service_mock):
        integration = create_merit_integration()
        output = StringIO()

        call_command("verify_general_ledger_sync", integration.id, "--start", "2026-06-01", "--end", "2026-06-30", stdout=output)

        service_mock.return_value.sync.assert_not_called()


class SecretProviderTests(TestCase):
    def test_get_secret_returns_placeholder_secret(self):
        integration = create_merit_integration()

        secret = SecretProvider.get_secret(integration)

        self.assertEqual(secret, "api-secret")

    def test_missing_secret_raises_secret_missing_error(self):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = ""

        with self.assertRaises(SecretMissingError):
            SecretProvider.get_secret(integration)

    def test_mask_secret_returns_empty_for_empty_value(self):
        self.assertEqual(SecretProvider.mask_secret(""), "")
        self.assertEqual(SecretProvider.mask_secret(None), "")

    def test_mask_secret_hides_short_secret(self):
        self.assertEqual(SecretProvider.mask_secret("abc"), "****")
        self.assertEqual(SecretProvider.mask_secret("abcd"), "****")

    def test_mask_secret_masks_long_secret(self):
        self.assertEqual(SecretProvider.mask_secret("abcdefyz"), "ab****yz")

    def test_secret_is_not_included_in_exception_message(self):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = ""

        with self.assertRaises(SecretMissingError) as context:
            SecretProvider.get_secret(integration)

        self.assertNotIn("api-secret", str(context.exception))
        self.assertNotIn("encrypted_secret_placeholder", str(context.exception))

    def test_provider_does_not_mutate_integration(self):
        integration = create_merit_integration()
        original_secret = integration.encrypted_secret_placeholder
        original_api_id = integration.api_id

        SecretProvider.get_secret(integration)
        SecretProvider.mask_secret(integration.encrypted_secret_placeholder)

        self.assertEqual(integration.encrypted_secret_placeholder, original_secret)
        self.assertEqual(integration.api_id, original_api_id)


class MeritAuthenticationServiceTests(TestCase):
    def test_timestamp_generation_uses_merit_format(self):
        integration = create_merit_integration()
        service = MeritAuthenticationService()

        with patch.object(service, "_timestamp", return_value="20260102030405"):
            authentication = service.create_authentication(integration)

        self.assertEqual(authentication.timestamp, "20260102030405")
        self.assertEqual(len(authentication.timestamp), 14)

    def test_signature_is_deterministic(self):
        integration = create_merit_integration()
        service = MeritAuthenticationService()

        with patch.object(service, "_timestamp", return_value="20260102030405"):
            first = service.create_authentication(integration, body='{"hello":"world"}')
            second = service.create_authentication(integration, body='{"hello":"world"}')

        self.assertEqual(first.signature, second.signature)
        self.assertEqual(first.signature, "N2+UH9qs5blm/lqcpfJjedwse0cfUaY9JFkqDSMjRqQ=")

    def test_headers_generated_correctly(self):
        integration = create_merit_integration()
        service = MeritAuthenticationService()

        with patch.object(service, "_timestamp", return_value="20260102030405"):
            authentication = service.create_authentication(integration, body="{}")

        self.assertEqual(authentication.api_id, "api-id")
        self.assertEqual(authentication.headers, {})

    def test_secret_provider_called(self):
        integration = create_merit_integration()
        secret_provider = TrackingSecretProvider()
        service = MeritAuthenticationService(secret_provider=secret_provider)

        with patch.object(service, "_timestamp", return_value="20260102030405"):
            service.create_authentication(integration)

        self.assertEqual(secret_provider.calls, 1)

    def test_authentication_does_not_expose_secret(self):
        integration = create_merit_integration()
        service = MeritAuthenticationService()

        with patch.object(service, "_timestamp", return_value="20260102030405"):
            authentication = service.create_authentication(integration)

        self.assertNotIn("api-secret", repr(authentication))
        self.assertNotIn("api-secret", authentication.signature)

    def test_merit_authentication_is_immutable(self):
        authentication = MeritAuthentication(api_id="api-id", timestamp="20260102030405", signature="sig", headers={})

        with self.assertRaises(FrozenInstanceError):
            authentication.api_id = "changed"

    def test_missing_api_id_raises_authentication_error(self):
        integration = create_merit_integration()
        integration.api_id = ""

        with self.assertRaises(AccountingAuthenticationError):
            MeritAuthenticationService().create_authentication(integration)

    def test_missing_secret_raises_authentication_error(self):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = ""

        with self.assertRaises(AccountingAuthenticationError):
            MeritAuthenticationService().create_authentication(integration)


class MeritAPIClientTests(TestCase):
    def test_health_returns_structured_local_check_result(self):
        integration = create_merit_integration()

        health = MeritAPIClient(integration).health()

        self.assertTrue(health["healthy"])
        self.assertEqual(health["provider"], AccountingIntegration.Provider.MERIT)
        self.assertEqual(health["mode"], "local_check")
        self.assertIsNone(health["status_code"])
        self.assertIn("response_time_ms", health)

    def test_authenticate_returns_true_when_api_id_and_secret_exist(self):
        integration = create_merit_integration()

        self.assertTrue(MeritAPIClient(integration).authenticate())

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_authentication_error_is_mapped(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(401, '{"Message":"Invalid signature"}')

        with self.assertRaises(AccountingAuthenticationError):
            MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

    def test_missing_credentials_raise_authentication_error(self):
        integration = create_merit_integration()
        integration.api_id = ""
        integration.encrypted_secret_placeholder = ""

        with self.assertRaises(AccountingAuthenticationError):
            MeritAPIClient(integration).health()

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_timeout_is_mapped(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = TimeoutError()

        with self.assertRaises(AccountingConnectionError):
            MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_connection_error_is_mapped(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = URLError("network down")

        with self.assertRaises(AccountingConnectionError):
            MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_500_response_is_mapped(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(500, '{"Message":"Server error"}')

        with self.assertRaises(AccountingAPIError):
            MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_rate_limit_response_is_mapped(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(429, '{"Message":"Too many requests"}')

        with self.assertRaises(AccountingRateLimitError):
            MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_json_parsing(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true, "items": [1, 2]}')

        response = MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

        self.assertEqual(response, {"ok": True, "items": [1, 2]})

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_get_request_builds_url_with_params(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')

        MeritAPIClient(integration).request("GET", "/api/v1/items", params={"page": 2})

        request_object = urlopen_mock.call_args.args[0]
        self.assertEqual(request_object.get_method(), "GET")
        self.assertIn("/api/v1/items?", request_object.full_url)
        self.assertIn("page=2", request_object.full_url)
        self.assertIn("apiId=api-id", request_object.full_url)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_post_request_sends_json_payload(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')

        MeritAPIClient(integration).request("POST", "/api/v1/items", payload={"name": "Test"})

        request_object = urlopen_mock.call_args.args[0]
        self.assertEqual(request_object.get_method(), "POST")
        self.assertEqual(request_object.data.decode("utf-8"), '{"name":"Test"}')

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_invalid_json_response_is_mapped_when_content_type_is_json(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse("{not-json", headers={"Content-Type": "application/json"})

        with self.assertRaises(AccountingUnexpectedResponseError):
            MeritAPIClient(integration).request("POST", "/api/v1/gettaxes", payload={})

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_headers_created_correctly(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')

        MeritAPIClient(integration).request(
            "POST",
            "/api/v1/gettaxes",
            payload={"hello": "world"},
            headers={"X-Test": "yes"},
        )

        request_object = urlopen_mock.call_args.args[0]
        self.assertEqual(request_object.headers["Accept"], "application/json")
        self.assertEqual(request_object.headers["Content-type"], "application/json; charset=utf-8")
        self.assertEqual(request_object.headers["User-agent"], "OperationsWorkspacePlatform/1.0")
        self.assertEqual(request_object.headers["X-test"], "yes")

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_signed_request_contains_auth_query_without_secret(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')

        MeritAPIClient(integration).request("GET", "/api/v1/ping")

        request_object = urlopen_mock.call_args.args[0]
        self.assertIn("apiId=api-id", request_object.full_url)
        self.assertIn("timestamp=", request_object.full_url)
        self.assertIn("signature=", request_object.full_url)
        self.assertNotIn("api-secret", request_object.full_url)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_client_reads_secret_through_secret_provider(self, urlopen_mock):
        integration = create_merit_integration()
        secret_provider = SecretProvider()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')

        with patch.object(secret_provider, "get_secret", wraps=secret_provider.get_secret) as get_secret_mock:
            MeritAPIClient(integration, secret_provider=secret_provider).request(
                "POST",
                "/api/v1/gettaxes",
                payload={},
            )

        self.assertGreaterEqual(get_secret_mock.call_count, 1)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_client_does_not_read_secret_field_directly_when_provider_injected(self, urlopen_mock):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = ""
        secret_provider = StaticSecretProvider()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')

        MeritAPIClient(integration, secret_provider=secret_provider).request("POST", "/api/v1/gettaxes", payload={})

        request_object = urlopen_mock.call_args.args[0]
        self.assertIn("signature=", request_object.full_url)
        self.assertEqual(secret_provider.calls, 1)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_authentication_is_attached_to_request(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"ok": true}')
        authentication_service = MeritAuthenticationService()

        with patch.object(authentication_service, "_timestamp", return_value="20260102030405"):
            MeritAPIClient(integration, authentication_service=authentication_service).request(
                "POST",
                "/api/v1/gettaxes",
                payload={"hello": "world"},
            )

        request_object = urlopen_mock.call_args.args[0]
        self.assertIn("apiId=api-id", request_object.full_url)
        self.assertIn("timestamp=20260102030405", request_object.full_url)
        self.assertIn("signature=", request_object.full_url)
        self.assertNotIn("api-secret", request_object.full_url)

    def test_authentication_error_mapping_from_service(self):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = ""

        with self.assertRaises(AccountingAuthenticationError):
            MeritAPIClient(integration).request(
                "POST",
                "/api/v1/gettaxes",
                payload={},
            )


class VerifyMeritIntegrationCommandTests(TestCase):
    def test_command_requires_valid_integration_id(self):
        output = StringIO()

        with self.assertRaises(CommandError) as error:
            call_command("verify_merit_integration", 999999, stdout=output)

        self.assertIn("AccountingIntegration not found", str(error.exception))

    @patch("apps.accounting.management.commands.verify_merit_integration.MeritAPIClient")
    def test_health_path_calls_merit_api_client_health(self, client_mock):
        integration = create_merit_integration()
        client_mock.return_value.health.return_value = {
            "healthy": True,
            "provider": "merit",
            "mode": "local_check",
            "response_time_ms": 1.5,
        }
        output = StringIO()

        call_command("verify_merit_integration", integration.id, stdout=output)

        client_mock.assert_called_once_with(integration)
        client_mock.return_value.health.assert_called_once()
        text = output.getvalue()
        self.assertIn("integration_id:", text)
        self.assertIn("provider: merit", text)
        self.assertIn("dimension_sync: skipped", text)

    @patch("apps.accounting.management.commands.verify_merit_integration.AccountingDimensionSyncService")
    @patch("apps.accounting.management.commands.verify_merit_integration.MeritAPIClient")
    def test_sync_dimensions_calls_accounting_dimension_sync_service(self, client_mock, sync_service_mock):
        integration = create_merit_integration()
        client_mock.return_value.health.return_value = {"healthy": True, "provider": "merit"}
        sync_service_mock.sync.return_value = SyncAccountingDimensionsResult(
            integration=integration,
            created_count=1,
            updated_count=2,
            unchanged_count=3,
            archived_count=4,
            conflict_count=5,
            dimensions=[],
            conflicts=[],
        )
        output = StringIO()

        call_command("verify_merit_integration", integration.id, "--sync-dimensions", stdout=output)

        sync_service_mock.sync.assert_called_once()
        command = sync_service_mock.sync.call_args.args[0]
        self.assertEqual(command.integration, integration)
        self.assertEqual(command.metadata, {"source": "verify_merit_integration_command"})
        text = output.getvalue()
        self.assertIn("created_count: 1", text)
        self.assertIn("updated_count: 2", text)
        self.assertIn("unchanged_count: 3", text)
        self.assertIn("archived_count: 4", text)
        self.assertIn("conflict_count: 5", text)

    @patch("apps.accounting.management.commands.verify_merit_integration.MeritAPIClient")
    def test_output_does_not_contain_secret(self, client_mock):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = "do-not-print-this"
        integration.save()
        client_mock.return_value.health.return_value = {
            "healthy": True,
            "provider": "merit",
            "mode": "local_check",
        }
        output = StringIO()

        call_command("verify_merit_integration", integration.id, stdout=output)

        self.assertNotIn("do-not-print-this", output.getvalue())

    @patch("apps.accounting.management.commands.verify_merit_integration.MeritAPIClient")
    def test_service_errors_handled_safely(self, client_mock):
        integration = create_merit_integration()
        integration.encrypted_secret_placeholder = "secret-value"
        integration.save()
        client_mock.return_value.health.side_effect = RuntimeError("secret-value failed")

        with self.assertRaises(CommandError) as error:
            call_command("verify_merit_integration", integration.id, stdout=StringIO())

        self.assertIn("Merit health check failed. Check integration configuration and try again.", str(error.exception))
        self.assertNotIn("secret-value", str(error.exception))

    @patch("apps.accounting.management.commands.verify_merit_integration.MeritAPIClient")
    def test_debug_error_still_omits_secret_when_exception_message_is_safe(self, client_mock):
        integration = create_merit_integration()
        client_mock.return_value.health.side_effect = RuntimeError("network unavailable")

        with self.assertRaises(CommandError) as error:
            call_command("verify_merit_integration", integration.id, "--debug", stdout=StringIO())

        self.assertIn("RuntimeError: network unavailable", str(error.exception))
        self.assertNotIn("api-secret", str(error.exception))

    @patch("apps.accounting.management.commands.verify_merit_integration.MeritAPIClient")
    def test_no_real_api_calls_in_tests(self, client_mock):
        integration = create_merit_integration()
        client_mock.return_value.health.return_value = {"healthy": True, "provider": "merit"}

        call_command("verify_merit_integration", integration.id, stdout=StringIO())

        client_mock.return_value.health.assert_called_once()


class MeritDimensionAPITests(TestCase):
    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_list_dimensions_empty_list(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"Dimensions": []}')

        dimensions = MeritAPIClient(integration).list_dimensions()

        self.assertEqual(dimensions, [])

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_list_dimensions_single_dimension(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse(
            '{"Dimensions": [{"Id": "m-1", "Code": "26124", "Name": "Kanarbiku", "DimensionType": "project"}]}'
        )

        dimensions = MeritAPIClient(integration).list_dimensions()

        self.assertEqual(len(dimensions), 1)
        self.assertEqual(dimensions[0].external_id, "m-1")
        self.assertEqual(dimensions[0].code, "26124")
        self.assertEqual(dimensions[0].name, "Kanarbiku")
        self.assertEqual(dimensions[0].dimension_type, "project")
        self.assertTrue(dimensions[0].active)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_list_dimensions_multiple_dimensions(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse(
            '{"Dimensions": ['
            '{"Id": "m-1", "Code": "26124", "Name": "Kanarbiku"},'
            '{"Id": "m-2", "Code": "26125", "Name": "Lennujaama", "Active": false}'
            "]}"
        )

        dimensions = MeritAPIClient(integration).list_dimensions()

        self.assertEqual([dimension.code for dimension in dimensions], ["26124", "26125"])
        self.assertFalse(dimensions[1].active)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_list_dimensions_flattens_merit_values_shape(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse(
            '{"Dimensions": [{"Name": "project", "Values": ['
            '{"Id": "v-1", "Code": "26124", "Name": "Kanarbiku"}'
            "]}]}"
        )

        dimensions = MeritAPIClient(integration).list_dimensions()

        self.assertEqual(len(dimensions), 1)
        self.assertEqual(dimensions[0].external_id, "v-1")
        self.assertEqual(dimensions[0].dimension_type, "project")

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_list_dimensions_missing_fields(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"Dimensions": [{}]}')

        dimensions = MeritAPIClient(integration).list_dimensions()

        self.assertEqual(dimensions[0].external_id, "")
        self.assertEqual(dimensions[0].code, "")
        self.assertEqual(dimensions[0].name, "")
        self.assertEqual(dimensions[0].dimension_type, "project")
        self.assertTrue(dimensions[0].active)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_list_dimensions_invalid_json(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse("{not-json", headers={"Content-Type": "application/json"})

        with self.assertRaises(AccountingUnexpectedResponseError):
            MeritAPIClient(integration).list_dimensions()

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_get_dimension_returns_dto(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse('{"Id": "m-1", "Code": "26124", "Name": "Kanarbiku"}')

        dimension = MeritAPIClient(integration).get_dimension("m-1")

        self.assertEqual(dimension.external_id, "m-1")
        self.assertEqual(dimension.code, "26124")
        request_object = urlopen_mock.call_args.args[0]
        self.assertIn("/api/v2/getdimension?", request_object.full_url)
        self.assertIn("Id=m-1", request_object.full_url)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_get_dimension_404_returns_none(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(404, '{"Message":"Not found"}')

        dimension = MeritAPIClient(integration).get_dimension("missing")

        self.assertIsNone(dimension)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_dimension_401_maps_to_authentication_error(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(401, '{"Message":"Unauthorized"}')

        with self.assertRaises(AccountingAuthenticationError):
            MeritAPIClient(integration).list_dimensions()

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_dimension_429_maps_to_rate_limit_error(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(429, '{"Message":"Too many requests"}')

        with self.assertRaises(AccountingRateLimitError):
            MeritAPIClient(integration).list_dimensions()

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_dimension_500_maps_to_api_error(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(500, '{"Message":"Server error"}')

        with self.assertRaises(AccountingAPIError):
            MeritAPIClient(integration).list_dimensions()

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_payload(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse(
            '{"Dimensions": [{"Id": "new-1", "Code": "26126", "Name": "New Project"}]}'
        )

        dimension = MeritAPIClient(integration).create_dimension(
            code="26126",
            name="New Project",
            dimension_type="project",
        )

        request_object = urlopen_mock.call_args.args[0]
        payload = request_object.data.decode("utf-8")
        self.assertIn("/api/v2/senddimvalues?", request_object.full_url)
        self.assertIn('"Dimensions":[{"Name":"project","Values":[{"Code":"26126","Name":"New Project"}]}]', payload)
        self.assertEqual(dimension.external_id, "new-1")
        self.assertEqual(dimension.code, "26126")

    def test_dimension_dto_is_immutable(self):
        dimension = MeritDimensionDTO(
            external_id="m-1",
            code="26124",
            name="Kanarbiku",
            dimension_type="project",
            active=True,
            raw={"Id": "m-1"},
        )

        with self.assertRaises(FrozenInstanceError):
            dimension.code = "changed"

    def test_dimension_methods_do_not_write_database(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        project_count = Project.objects.count()
        dimension_count = AccountingDimension.objects.count()

        with patch("apps.accounting.connectors.merit.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value = FakeHTTPResponse('{"Dimensions": []}')
            MeritAPIClient(integration).list_dimensions()

        self.assertEqual(Project.objects.count(), project_count)
        self.assertEqual(AccountingDimension.objects.count(), dimension_count)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_value_builds_correct_payload(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse(
            '{"Dimensions": [{"DimValueId": "dv-1", "DimValueCode": "26126", "DimValueName": "New Project"}]}'
        )

        value = MeritAPIClient(integration).create_dimension_value(
            code="26126",
            name="New Project",
            dimension_type="project",
            dimension_id="dim-project",
            external_id="dv-1",
            end_date="2026-12-31",
        )

        request_object = urlopen_mock.call_args.args[0]
        payload = request_object.data.decode("utf-8")
        self.assertIn("/api/v2/senddimvalues?", request_object.full_url)
        self.assertIn(
            '"Dimensions":[{"DimId":"dim-project","DimValueCode":"26126","DimValueName":"New Project",'
            '"DimValueId":"dv-1","EndDate":"2026-12-31"}]',
            payload,
        )
        self.assertEqual(value.external_id, "dv-1")
        self.assertEqual(value.code, "26126")
        self.assertEqual(value.name, "New Project")
        self.assertEqual(value.dimension_type, "project")

    def test_create_dimension_value_requires_dimension_id(self):
        integration = create_merit_integration()

        with self.assertRaises(ValueError):
            MeritAPIClient(integration).create_dimension_value(code="26126", name="New Project")

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_value_maps_response_to_dto(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse(
            '{"Dimensions": [{"DimValueId": "dv-1", "DimValueCode": "26126", "DimValueName": "New Project", "Active": true}]}'
        )

        value = MeritAPIClient(integration).create_dimension_value(
            code="26126",
            name="New Project",
            dimension_id="dim-project",
        )

        self.assertIsInstance(value, MeritDimensionValueDTO)
        self.assertEqual(value.external_id, "dv-1")
        self.assertEqual(value.raw["DimValueId"], "dv-1")
        self.assertTrue(value.active)

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_value_401_maps_to_authentication_error(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(401, '{"Message":"Unauthorized"}')

        with self.assertRaises(AccountingAuthenticationError):
            MeritAPIClient(integration).create_dimension_value(
                code="26126",
                name="New Project",
                dimension_id="dim-project",
            )

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_value_429_maps_to_rate_limit_error(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(429, '{"Message":"Too many requests"}')

        with self.assertRaises(AccountingRateLimitError):
            MeritAPIClient(integration).create_dimension_value(
                code="26126",
                name="New Project",
                dimension_id="dim-project",
            )

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_value_500_maps_to_api_error(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.side_effect = http_error(500, '{"Message":"Server error"}')

        with self.assertRaises(AccountingAPIError):
            MeritAPIClient(integration).create_dimension_value(
                code="26126",
                name="New Project",
                dimension_id="dim-project",
            )

    @patch("apps.accounting.connectors.merit.request.urlopen")
    def test_create_dimension_value_invalid_json(self, urlopen_mock):
        integration = create_merit_integration()
        urlopen_mock.return_value = FakeHTTPResponse("{not-json", headers={"Content-Type": "application/json"})

        with self.assertRaises(AccountingUnexpectedResponseError):
            MeritAPIClient(integration).create_dimension_value(
                code="26126",
                name="New Project",
                dimension_id="dim-project",
            )

    def test_dimension_value_methods_do_not_write_database(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        project_count = Project.objects.count()
        dimension_count = AccountingDimension.objects.count()

        with patch("apps.accounting.connectors.merit.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value = FakeHTTPResponse(
                '{"Dimensions": [{"DimValueId": "dv-1", "DimValueCode": "26126", "DimValueName": "New Project"}]}'
            )
            MeritAPIClient(integration).create_dimension_value(
                code="26126",
                name="New Project",
                dimension_id="dim-project",
            )

        self.assertEqual(Project.objects.count(), project_count)
        self.assertEqual(AccountingDimension.objects.count(), dimension_count)


class MeritGLFullDetailsAPITests(TestCase):
    def _sample_batch(self):
        return {
            "GLBId": "glb-1",
            "BatchCode": "GL",
            "No": "42",
            "DocId": "doc-1",
            "Document": "Purchase invoice",
            "BatchDate": "2026-07-01",
            "CurrencyCode": "EUR",
            "CurrencyRate": "1.000000",
            "TotalAmount": "123.450000",
            "PriceInclVat": True,
            "ChangedDate": "2026-07-02T10:20:30+00:00",
            "Entries": [
                {
                    "AccountCode": "4000",
                    "AccontName": "Revenue",
                    "Memo": "Project work",
                    "DepartmentCode": "D1",
                    "DebitAmount": "0",
                    "DebitCurrency": "EUR",
                    "CreditAmount": "123.450000",
                    "CreditCurrency": "EUR",
                    "TypeId": 1,
                    "BatchId": "glb-1",
                    "EntryId": "entry-1",
                    "TaxId": "tax-1",
                    "TaxPct": "22.0000",
                    "CostAllocLines": [
                        {
                            "SourceType": "project",
                            "Code": "26124",
                            "Name": "Kanarbiku",
                            "Mult": "1.0000",
                            "Amount": "123.450000",
                            "BatchId": "glb-1",
                            "EntryId": "entry-1",
                        }
                    ],
                }
            ],
        }

    def _call_gl(self, client):
        return client.get_gl_batches_full(date(2026, 7, 1), date(2026, 7, 31))

    def test_get_gl_batches_full_builds_post_request_payload(self):
        client = MeritAPIClient(create_merit_integration())

        with patch.object(client, "request", return_value=[]) as request_mock:
            self._call_gl(client)

        request_mock.assert_called_once()
        self.assertEqual(request_mock.call_args.args, ("POST", MeritAPIClient.GL_BATCHES_FULL_PATH))
        self.assertEqual(
            request_mock.call_args.kwargs["payload"],
            {
                "PeriodStart": "20260701",
                "PeriodEnd": "20260731",
                "WithLines": 1,
                "WithCostAlloc": 1,
                "DateType": 0,
            },
        )

    def test_get_gl_batches_full_uses_merit_compact_period_for_june_regression(self):
        client = MeritAPIClient(create_merit_integration())

        with patch.object(client, "request", return_value=[]) as request_mock:
            client.get_gl_batches_full(date(2026, 6, 1), date(2026, 6, 30))

        self.assertEqual(
            request_mock.call_args.kwargs["payload"],
            {
                "PeriodStart": "20260601",
                "PeriodEnd": "20260630",
                "WithLines": 1,
                "WithCostAlloc": 1,
                "DateType": 0,
            },
        )

    def test_get_gl_batches_full_supports_flags_and_changed_date_type(self):
        client = MeritAPIClient(create_merit_integration())

        with patch.object(client, "request", return_value=[]) as request_mock:
            client.get_gl_batches_full(
                "2026-07-01",
                "2026-07-31",
                with_lines=False,
                with_cost_allocations=False,
                date_type=MeritGLDateType.CHANGED_DATE,
            )

        payload = request_mock.call_args.kwargs["payload"]
        self.assertEqual(payload["WithLines"], 0)
        self.assertEqual(payload["WithCostAlloc"], 0)
        self.assertEqual(payload["DateType"], 1)

    def test_get_gl_batches_full_rejects_period_longer_than_31_calendar_days(self):
        client = MeritAPIClient(create_merit_integration())

        with self.assertRaises(ValueError):
            client.get_gl_batches_full(date(2026, 7, 1), date(2026, 8, 1))

    def test_get_gl_batches_full_rejects_reversed_period(self):
        client = MeritAPIClient(create_merit_integration())

        with self.assertRaises(ValueError):
            client.get_gl_batches_full(date(2026, 7, 31), date(2026, 7, 1))

    def test_get_gl_batches_full_rejects_unsupported_date_type(self):
        client = MeritAPIClient(create_merit_integration())

        with self.assertRaises(ValueError):
            client.get_gl_batches_full(date(2026, 7, 1), date(2026, 7, 31), date_type="posted_date")

    def test_get_gl_batches_full_empty_response_returns_empty_list(self):
        client = MeritAPIClient(create_merit_integration())

        with patch.object(client, "request", return_value=[]):
            batches = self._call_gl(client)

        self.assertEqual(batches, [])

    def test_get_gl_batches_full_maps_one_batch_without_entries(self):
        client = MeritAPIClient(create_merit_integration())
        raw_batch = self._sample_batch()
        raw_batch.pop("Entries")

        with patch.object(client, "request", return_value=[raw_batch]):
            batches = self._call_gl(client)

        self.assertEqual(len(batches), 1)
        self.assertIsInstance(batches[0], MeritGLBatchDTO)
        self.assertEqual(batches[0].external_id, "glb-1")
        self.assertEqual(batches[0].entries, ())

    def test_get_gl_batches_full_maps_entries_and_cost_allocations(self):
        client = MeritAPIClient(create_merit_integration())

        with patch.object(client, "request", return_value=[self._sample_batch()]):
            batch = self._call_gl(client)[0]

        entry = batch.entries[0]
        allocation = entry.cost_allocations[0]
        self.assertEqual(entry.account_code, "4000")
        self.assertEqual(entry.account_name, "Revenue")
        self.assertEqual(entry.credit_amount, Decimal("123.450000"))
        self.assertEqual(entry.tax_percent, Decimal("22.0000"))
        self.assertEqual(allocation.source_type, "project")
        self.assertEqual(allocation.code, "26124")
        self.assertEqual(allocation.amount, Decimal("123.450000"))
        self.assertEqual(allocation.multiplier, Decimal("1.0000"))

    def test_get_gl_batches_full_maps_multiple_batches(self):
        client = MeritAPIClient(create_merit_integration())
        second = self._sample_batch()
        second["GLBId"] = "glb-2"
        second["No"] = "43"

        with patch.object(client, "request", return_value=[self._sample_batch(), second]):
            batches = self._call_gl(client)

        self.assertEqual([batch.external_id for batch in batches], ["glb-1", "glb-2"])

    def test_get_gl_batches_full_maps_multiple_project_allocations(self):
        client = MeritAPIClient(create_merit_integration())
        raw_batch = self._sample_batch()
        raw_batch["Entries"][0]["CostAllocLines"].append(
            {
                "SourceType": "project",
                "Code": "26125",
                "Name": "Lennujaama",
                "Mult": "0.5000",
                "Amount": "61.725000",
            }
        )

        with patch.object(client, "request", return_value=[raw_batch]):
            allocations = self._call_gl(client)[0].entries[0].cost_allocations

        self.assertEqual([allocation.code for allocation in allocations], ["26124", "26125"])

    def test_get_gl_batches_full_supports_account_name_spelling(self):
        client = MeritAPIClient(create_merit_integration())
        raw_batch = self._sample_batch()
        raw_batch["Entries"][0].pop("AccontName")
        raw_batch["Entries"][0]["AccountName"] = "Revenue corrected"

        with patch.object(client, "request", return_value=[raw_batch]):
            entry = self._call_gl(client)[0].entries[0]

        self.assertEqual(entry.account_name, "Revenue corrected")

    def test_get_gl_batches_full_keeps_decimal_precision(self):
        client = MeritAPIClient(create_merit_integration())
        raw_batch = self._sample_batch()
        raw_batch["TotalAmount"] = "123.456789"
        raw_batch["CurrencyRate"] = "1.234567"

        with patch.object(client, "request", return_value=[raw_batch]):
            batch = self._call_gl(client)[0]

        self.assertEqual(batch.total_amount, Decimal("123.456789"))
        self.assertEqual(batch.currency_rate, Decimal("1.234567"))

    def test_get_gl_batches_full_tolerates_nullable_fields(self):
        client = MeritAPIClient(create_merit_integration())
        raw_batch = self._sample_batch()
        raw_batch["BatchDate"] = None
        raw_batch["ChangedDate"] = "not-a-date"
        raw_batch["TotalAmount"] = None
        raw_batch["PriceInclVat"] = None
        raw_batch["Entries"][0]["CostAllocLines"] = None

        with patch.object(client, "request", return_value=[raw_batch]):
            batch = self._call_gl(client)[0]

        self.assertIsNone(batch.batch_date)
        self.assertIsNone(batch.changed_at)
        self.assertIsNone(batch.total_amount)
        self.assertIsNone(batch.price_includes_vat)
        self.assertEqual(batch.entries[0].cost_allocations, ())

    def test_get_gl_batches_full_preserves_raw_and_does_not_mutate_response(self):
        client = MeritAPIClient(create_merit_integration())
        response = [self._sample_batch()]
        original = deepcopy(response)

        with patch.object(client, "request", return_value=response):
            batch = self._call_gl(client)[0]

        self.assertEqual(response, original)
        response[0]["Document"] = "Changed after mapping"
        self.assertEqual(batch.raw["Document"], "Purchase invoice")
        self.assertEqual(original[0]["Document"], "Purchase invoice")

    def test_gl_batch_dto_is_immutable(self):
        client = MeritAPIClient(create_merit_integration())

        with patch.object(client, "request", return_value=[self._sample_batch()]):
            batch = self._call_gl(client)[0]

        with self.assertRaises(FrozenInstanceError):
            batch.external_id = "changed"

    def test_get_gl_batches_full_invalid_top_level_payload_raises(self):
        client = MeritAPIClient(create_merit_integration())

        with patch.object(client, "request", return_value={}):
            with self.assertRaises(AccountingUnexpectedResponseError):
                self._call_gl(client)

    def test_get_gl_batches_full_malformed_batch_without_identity_raises(self):
        client = MeritAPIClient(create_merit_integration())

        with patch.object(client, "request", return_value=[{"BatchCode": "GL"}]):
            with self.assertRaises(AccountingUnexpectedResponseError):
                self._call_gl(client)

    def test_get_gl_batches_full_invalid_json_propagates(self):
        client = MeritAPIClient(create_merit_integration())

        with patch.object(client, "request", side_effect=AccountingUnexpectedResponseError("invalid json")):
            with self.assertRaises(AccountingUnexpectedResponseError):
                self._call_gl(client)

    def test_get_gl_batches_full_does_not_write_database_or_audit(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        project_count = Project.objects.count()
        dimension_count = AccountingDimension.objects.count()
        audit_count = AuditEvent.objects.count()
        client = MeritAPIClient(integration)

        with patch.object(client, "request", return_value=[]):
            client.get_gl_batches_full(date(2026, 7, 1), date(2026, 7, 31))

        self.assertEqual(Project.objects.count(), project_count)
        self.assertEqual(AccountingDimension.objects.count(), dimension_count)
        self.assertEqual(AuditEvent.objects.count(), audit_count)


class AccountingDimensionSyncServiceTests(TestCase):
    def test_creates_new_accounting_dimension_from_dto(self):
        integration = create_merit_integration()
        dto = MeritDimensionDTO("m-1", "26124", "Kanarbiku", "project", True, {"Id": "m-1"})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        dimension = AccountingDimension.objects.get(code="26124")
        self.assertEqual(result.created_count, 1)
        self.assertEqual(dimension.organization, integration.organization)
        self.assertEqual(dimension.provider, integration.provider)
        self.assertEqual(dimension.integration, integration)
        self.assertEqual(dimension.external_id, "m-1")
        self.assertEqual(dimension.name, "Kanarbiku")
        self.assertEqual(dimension.raw_data, {"Id": "m-1"})
        self.assertIsNotNone(dimension.last_synced_at)

    def test_updates_existing_accounting_dimension(self):
        integration = create_merit_integration()
        dimension = AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="m-1",
            code="26124",
            name="Old name",
            last_synced_at="2026-01-01T00:00:00Z",
        )
        dto = MeritDimensionDTO("m-1", "26124", "New name", "project", True, {"Id": "m-1", "Name": "New name"})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        dimension.refresh_from_db()
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(dimension.name, "New name")
        self.assertEqual(dimension.raw_data, {"Id": "m-1", "Name": "New name"})

    def test_unchanged_dimension_counted(self):
        integration = create_merit_integration()
        AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="m-1",
            code="26124",
            name="Kanarbiku",
            raw_data={"Id": "m-1"},
            last_synced_at="2026-01-01T00:00:00Z",
        )
        dto = MeritDimensionDTO("m-1", "26124", "Kanarbiku", "project", True, {"Id": "m-1"})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        self.assertEqual(result.unchanged_count, 1)
        self.assertEqual(result.updated_count, 0)

    def test_archives_missing_previously_synced_dimension(self):
        integration = create_merit_integration()
        dimension = AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="m-old",
            code="26123",
            name="Old project",
            last_synced_at="2026-01-01T00:00:00Z",
        )
        dto = MeritDimensionDTO("m-1", "26124", "Kanarbiku", "project", True, {"Id": "m-1"})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        dimension.refresh_from_db()
        self.assertEqual(result.archived_count, 1)
        self.assertFalse(dimension.is_active)

    def test_detects_duplicate_incoming_code_conflict(self):
        integration = create_merit_integration()
        dtos = [
            MeritDimensionDTO("m-1", "26124", "Kanarbiku A", "project", True, {}),
            MeritDimensionDTO("m-2", "26124", "Kanarbiku B", "project", True, {}),
        ]

        with patch.object(MeritAPIClient, "list_dimensions", return_value=dtos):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        self.assertEqual(result.conflict_count, 1)
        self.assertEqual(result.conflicts[0]["type"], "duplicate_incoming_code")
        self.assertFalse(AccountingDimension.objects.filter(code="26124").exists())

    def test_detects_same_code_different_external_id_conflict(self):
        integration = create_merit_integration()
        AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="m-existing",
            code="26124",
            name="Existing",
        )
        dto = MeritDimensionDTO("m-new", "26124", "Incoming", "project", True, {})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        self.assertEqual(result.conflict_count, 1)
        self.assertEqual(result.conflicts[0]["type"], "same_code_different_external_id")
        self.assertEqual(AccountingDimension.objects.get(code="26124").external_id, "m-existing")

    def test_detects_same_external_id_different_code_conflict(self):
        integration = create_merit_integration()
        AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="m-1",
            code="26124",
            name="Existing",
        )
        dto = MeritDimensionDTO("m-1", "26125", "Incoming", "project", True, {})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        self.assertEqual(result.conflict_count, 1)
        self.assertEqual(result.conflicts[0]["type"], "same_external_id_different_code")
        self.assertEqual(AccountingDimension.objects.get(external_id="m-1").code, "26124")

    def test_creates_sync_started_and_completed_audit_events(self):
        integration = create_merit_integration()
        dto = MeritDimensionDTO("m-1", "26124", "Kanarbiku", "project", True, {})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        event_types = list(AuditEvent.objects.values_list("event_type", flat=True))
        self.assertIn("accounting_dimension_sync_started", event_types)
        self.assertIn("accounting_dimension_sync_completed", event_types)

    def test_completed_audit_event_stores_conflict_details(self):
        integration = create_merit_integration()
        dtos = [
            MeritDimensionDTO("m-1", "26124", "Kanarbiku A", "project", True, {}),
            MeritDimensionDTO("m-2", "26124", "Kanarbiku B", "project", True, {}),
        ]

        with patch.object(MeritAPIClient, "list_dimensions", return_value=dtos):
            AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        event = AuditEvent.objects.filter(event_type="accounting_dimension_sync_completed").latest("created_at")
        self.assertEqual(event.metadata["conflict_count"], 1)
        self.assertEqual(event.metadata["conflicts"][0]["type"], "duplicate_incoming_code")
        self.assertEqual(event.metadata["conflicts"][0]["code"], "26124")

    def test_metadata_is_not_mutated(self):
        integration = create_merit_integration()
        metadata = {"source": {"requested_by": "test"}}
        original_metadata = {"source": {"requested_by": "test"}}

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[]):
            result = AccountingDimensionSyncService.sync(
                SyncAccountingDimensionsCommand(integration=integration, metadata=metadata)
            )

        result.metadata["source"]["requested_by"] = "changed"
        self.assertEqual(metadata, original_metadata)

    def test_api_errors_propagate_safely(self):
        integration = create_merit_integration()

        with patch.object(MeritAPIClient, "list_dimensions", side_effect=AccountingAPIError("Merit down")):
            with self.assertRaises(AccountingAPIError):
                AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

    def test_organization_scoping_works(self):
        integration = create_merit_integration()
        other_integration = create_merit_integration(create_organization("Other Org"))
        AccountingDimension.objects.create(
            organization=other_integration.organization,
            integration=other_integration,
            provider=other_integration.provider,
            external_id="m-1",
            code="26124",
            name="Other org dimension",
        )
        dto = MeritDimensionDTO("m-1", "26124", "Own org dimension", "project", True, {})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            result = AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        self.assertEqual(result.created_count, 1)
        self.assertEqual(AccountingDimension.objects.filter(code="26124").count(), 2)

    def test_no_project_objects_created(self):
        integration = create_merit_integration()
        project_count = Project.objects.count()
        dto = MeritDimensionDTO("m-1", "26124", "Kanarbiku", "project", True, {})

        with patch.object(MeritAPIClient, "list_dimensions", return_value=[dto]):
            AccountingDimensionSyncService.sync(SyncAccountingDimensionsCommand(integration=integration))

        self.assertEqual(Project.objects.count(), project_count)


class AccountingDimensionValueServiceTests(TestCase):
    def _dto(self, external_id="dv-1", code="26124", name="Kanarbiku", active=True):
        return MeritDimensionValueDTO(
            external_id=external_id,
            code=code,
            name=name,
            dimension_type="project",
            active=active,
            raw={"DimValueId": external_id, "DimValueCode": code, "DimValueName": name},
        )

    def test_creates_dimension_via_mocked_merit_api_client(self):
        integration = create_merit_integration()
        dto = self._dto()

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=dto) as create_mock:
            result = AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                    dimension_id="dim-project",
                )
            )

        create_mock.assert_called_once_with(
            code="26124",
            name="Kanarbiku",
            dimension_type="project",
            dimension_id="dim-project",
            external_id=None,
            end_date=None,
        )
        self.assertTrue(result.created)
        self.assertFalse(result.updated)
        self.assertEqual(result.dto, dto)
        self.assertEqual(result.dimension.organization, integration.organization)
        self.assertEqual(result.dimension.provider, integration.provider)
        self.assertEqual(result.dimension.integration, integration)
        self.assertEqual(result.dimension.external_id, "dv-1")
        self.assertEqual(result.dimension.code, "26124")
        self.assertEqual(result.dimension.name, "Kanarbiku")
        self.assertEqual(result.dimension.raw_data, dto.raw)

    def test_updates_existing_accounting_dimension(self):
        integration = create_merit_integration()
        dimension = AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="dv-1",
            code="26124",
            name="Old name",
        )
        dto = self._dto(name="New name")

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=dto):
            result = AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="New name",
                    dimension_id="dim-project",
                    external_id="dv-1",
                )
            )

        dimension.refresh_from_db()
        self.assertFalse(result.created)
        self.assertTrue(result.updated)
        self.assertEqual(dimension.name, "New name")
        self.assertIsNotNone(dimension.last_synced_at)

    def test_does_not_duplicate_same_code(self):
        integration = create_merit_integration()
        AccountingDimension.objects.create(
            organization=integration.organization,
            integration=integration,
            provider=integration.provider,
            external_id="old-id",
            code="26124",
            name="Existing",
        )
        dto = self._dto(external_id="dv-1", code="26124", name="Updated")

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=dto):
            result = AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Updated",
                    dimension_id="dim-project",
                )
            )

        self.assertFalse(result.created)
        self.assertEqual(AccountingDimension.objects.filter(code="26124").count(), 1)
        self.assertEqual(AccountingDimension.objects.get(code="26124").external_id, "dv-1")

    def test_sets_last_synced_at(self):
        integration = create_merit_integration()

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=self._dto()):
            result = AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                    dimension_id="dim-project",
                )
            )

        self.assertIsNotNone(result.dimension.last_synced_at)

    def test_creates_audit_event(self):
        integration = create_merit_integration()

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=self._dto()):
            AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                    dimension_id="dim-project",
                )
            )

        event = AuditEvent.objects.get(event_type="accounting_dimension_value_created")
        self.assertEqual(event.organization, integration.organization)
        self.assertEqual(event.object_type, "AccountingDimension")
        self.assertEqual(event.metadata["created"], True)

    def test_metadata_is_not_mutated(self):
        integration = create_merit_integration()
        metadata = {"source": {"requested_by": "test"}}
        original_metadata = {"source": {"requested_by": "test"}}

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=self._dto()):
            result = AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                    dimension_id="dim-project",
                    metadata=metadata,
                )
            )

        result.metadata["source"]["requested_by"] = "changed"
        self.assertEqual(metadata, original_metadata)

    def test_api_error_prevents_db_write(self):
        integration = create_merit_integration()

        with patch.object(
            MeritAPIClient,
            "create_dimension_value",
            side_effect=AccountingAPIError("Merit down"),
        ):
            with self.assertRaises(AccountingAPIError):
                AccountingDimensionValueService.create(
                    CreateAccountingDimensionValueCommand(
                        integration=integration,
                        code="26124",
                        name="Kanarbiku",
                        dimension_id="dim-project",
                    )
                )

        self.assertFalse(AccountingDimension.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(event_type="accounting_dimension_value_created").exists())

    def test_requires_dimension_id(self):
        integration = create_merit_integration()

        with self.assertRaises(ValueError):
            AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                )
            )

    def test_organization_scoped(self):
        integration = create_merit_integration()
        other_integration = create_merit_integration(create_organization("Other Org"))
        AccountingDimension.objects.create(
            organization=other_integration.organization,
            integration=other_integration,
            provider=other_integration.provider,
            external_id="dv-1",
            code="26124",
            name="Other org dimension",
        )

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=self._dto()):
            result = AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                    dimension_id="dim-project",
                )
            )

        self.assertTrue(result.created)
        self.assertEqual(AccountingDimension.objects.filter(code="26124").count(), 2)

    def test_no_project_created(self):
        integration = create_merit_integration()
        project_count = Project.objects.count()

        with patch.object(MeritAPIClient, "create_dimension_value", return_value=self._dto()):
            AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code="26124",
                    name="Kanarbiku",
                    dimension_id="dim-project",
                )
            )

        self.assertEqual(Project.objects.count(), project_count)


class AccountingDimensionConflictResolutionServiceTests(TestCase):
    def _dimension(self, organization=None, **kwargs):
        organization = organization or create_organization()
        defaults = {
            "provider": AccountingDimension.Provider.MERIT,
            "external_id": "m-existing",
            "code": "26124",
            "name": "Local Kanarbiku",
            "dimension_type": AccountingDimension.DimensionType.PROJECT,
            "raw_data": {"Id": "m-existing", "Name": "Local Kanarbiku"},
        }
        defaults.update(kwargs)
        return AccountingDimension.objects.create(organization=organization, **defaults)

    def _conflict(self):
        return {
            "type": "same_code_different_external_id",
            "code": "26124",
            "dimension_type": "project",
            "existing_external_id": "m-existing",
            "incoming_external_id": "m-incoming",
            "incoming_name": "Incoming Kanarbiku",
            "incoming_raw": {"Id": "m-incoming", "Name": "Incoming Kanarbiku"},
        }

    def test_keep_local_does_not_change_dimension(self):
        organization = create_organization()
        dimension = self._dimension(organization)

        result = AccountingDimensionConflictResolutionService.resolve(
            ResolveDimensionConflictCommand(
                organization=organization,
                conflict=self._conflict(),
                resolution_type="keep_local",
            )
        )

        dimension.refresh_from_db()
        self.assertTrue(result.resolved)
        self.assertEqual(result.affected_dimension, dimension)
        self.assertEqual(dimension.external_id, "m-existing")
        self.assertEqual(dimension.name, "Local Kanarbiku")

    def test_accept_incoming_updates_dimension(self):
        organization = create_organization()
        dimension = self._dimension(organization)

        result = AccountingDimensionConflictResolutionService.resolve(
            ResolveDimensionConflictCommand(
                organization=organization,
                conflict=self._conflict(),
                resolution_type="accept_incoming",
            )
        )

        dimension.refresh_from_db()
        self.assertTrue(result.resolved)
        self.assertEqual(dimension.external_id, "m-incoming")
        self.assertEqual(dimension.name, "Incoming Kanarbiku")
        self.assertEqual(dimension.raw_data, {"Id": "m-incoming", "Name": "Incoming Kanarbiku"})

    def test_mark_inactive_sets_is_active_false(self):
        organization = create_organization()
        dimension = self._dimension(organization)

        result = AccountingDimensionConflictResolutionService.resolve(
            ResolveDimensionConflictCommand(
                organization=organization,
                conflict=self._conflict(),
                resolution_type="mark_inactive",
            )
        )

        dimension.refresh_from_db()
        self.assertTrue(result.resolved)
        self.assertFalse(dimension.is_active)

    def test_manual_review_required_records_audit_but_unresolved(self):
        organization = create_organization()
        self._dimension(organization)

        result = AccountingDimensionConflictResolutionService.resolve(
            ResolveDimensionConflictCommand(
                organization=organization,
                conflict=self._conflict(),
                resolution_type="manual_review_required",
            )
        )

        self.assertFalse(result.resolved)
        event = AuditEvent.objects.get(event_type="accounting_dimension_conflict_resolved")
        self.assertEqual(event.metadata["resolution_type"], "manual_review_required")
        self.assertFalse(event.metadata["resolved"])

    def test_ignore_records_audit_and_does_not_change_dimension(self):
        organization = create_organization()
        dimension = self._dimension(organization)

        result = AccountingDimensionConflictResolutionService.ignore(
            IgnoreDimensionConflictCommand(
                organization=organization,
                conflict=self._conflict(),
                reason="Known duplicate from Merit cleanup",
            )
        )

        dimension.refresh_from_db()
        self.assertTrue(result.resolved)
        self.assertEqual(dimension.external_id, "m-existing")
        event = AuditEvent.objects.get(event_type="accounting_dimension_conflict_resolved")
        self.assertEqual(event.metadata["resolution_type"], "ignore")
        self.assertEqual(event.metadata["reason"], "Known duplicate from Merit cleanup")

    def test_metadata_is_not_mutated(self):
        organization = create_organization()
        self._dimension(organization)
        metadata = {"source": {"view": "conflicts"}}
        original_metadata = {"source": {"view": "conflicts"}}

        result = AccountingDimensionConflictResolutionService.resolve(
            ResolveDimensionConflictCommand(
                organization=organization,
                conflict=self._conflict(),
                resolution_type="keep_local",
                metadata=metadata,
            )
        )

        result.metadata["source"]["view"] = "changed"
        self.assertEqual(metadata, original_metadata)

    def test_conflict_is_not_mutated(self):
        organization = create_organization()
        self._dimension(organization)
        conflict = self._conflict()
        original_conflict = self._conflict()

        AccountingDimensionConflictResolutionService.resolve(
            ResolveDimensionConflictCommand(
                organization=organization,
                conflict=conflict,
                resolution_type="accept_incoming",
            )
        )

        self.assertEqual(conflict, original_conflict)

    def test_invalid_resolution_type_raises_clear_error(self):
        organization = create_organization()

        with self.assertRaisesMessage(ValueError, "Unsupported dimension conflict resolution type"):
            AccountingDimensionConflictResolutionService.resolve(
                ResolveDimensionConflictCommand(
                    organization=organization,
                    conflict=self._conflict(),
                    resolution_type="auto_fix",
                )
            )

    def test_no_merit_api_calls(self):
        organization = create_organization()
        self._dimension(organization)

        with patch.object(MeritAPIClient, "list_dimensions") as list_mock:
            with patch.object(MeritAPIClient, "create_dimension_value") as create_mock:
                AccountingDimensionConflictResolutionService.resolve(
                    ResolveDimensionConflictCommand(
                        organization=organization,
                        conflict=self._conflict(),
                        resolution_type="keep_local",
                    )
                )

        list_mock.assert_not_called()
        create_mock.assert_not_called()

    def test_no_project_changes(self):
        organization = create_organization()
        self._dimension(organization)
        project_count = Project.objects.count()

        AccountingDimensionConflictResolutionService.resolve(
            ResolveDimensionConflictCommand(
                organization=organization,
                conflict=self._conflict(),
                resolution_type="accept_incoming",
            )
        )

        self.assertEqual(Project.objects.count(), project_count)

    def test_organization_scoping_respected(self):
        organization = create_organization()
        other_organization = create_organization("Other Org")
        dimension = self._dimension(organization)
        other_dimension = self._dimension(
            other_organization,
            external_id="m-other",
            code="26124",
            name="Other org dimension",
        )

        result = AccountingDimensionConflictResolutionService.resolve(
            ResolveDimensionConflictCommand(
                organization=organization,
                conflict=self._conflict(),
                resolution_type="mark_inactive",
            )
        )

        dimension.refresh_from_db()
        other_dimension.refresh_from_db()
        self.assertEqual(result.affected_dimension, dimension)
        self.assertFalse(dimension.is_active)
        self.assertTrue(other_dimension.is_active)

    def test_audit_event_created_for_each_action(self):
        organization = create_organization()
        self._dimension(organization)

        AccountingDimensionConflictResolutionService.resolve(
            ResolveDimensionConflictCommand(
                organization=organization,
                conflict=self._conflict(),
                resolution_type="keep_local",
            )
        )
        AccountingDimensionConflictResolutionService.ignore(
            IgnoreDimensionConflictCommand(
                organization=organization,
                conflict=self._conflict(),
                reason="Reviewed",
            )
        )

        self.assertEqual(AuditEvent.objects.filter(event_type="accounting_dimension_conflict_resolved").count(), 2)


class ProjectCodeAllocationServiceTests(TestCase):
    def test_suggests_next_code_from_projects(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Existing 1")
        Project.objects.create(organization=organization, code="26125", name="Existing 2")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26126")

    def test_suggests_next_code_from_accounting_dimensions(self):
        organization = create_organization()
        AccountingDimension.objects.create(organization=organization, code="26124", name="Existing 1")
        AccountingDimension.objects.create(organization=organization, code="26125", name="Existing 2")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26126")

    def test_merges_project_and_accounting_dimension_codes(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Workspace project")
        AccountingDimension.objects.create(organization=organization, code="26125", name="Merit dimension")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26126")
        self.assertEqual(suggestion.used_codes, ["26124", "26125"])

    def test_ignores_non_numeric_codes(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="ABC", name="Non numeric")
        AccountingDimension.objects.create(organization=organization, code="26125", name="Numeric")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26126")
        self.assertIn("ABC", suggestion.used_codes)

    def test_respects_min_code(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Existing")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization, min_code=27000)
        )

        self.assertEqual(suggestion.suggested_code, "27000")

    def test_prefix_considers_matching_codes_and_preserves_suffix_width(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26001", name="Matching 1")
        Project.objects.create(organization=organization, code="26002", name="Matching 2")
        Project.objects.create(organization=organization, code="27099", name="Other prefix")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization, prefix="26")
        )

        self.assertEqual(suggestion.suggested_code, "26003")

    def test_organization_isolation(self):
        organization = create_organization()
        other_organization = create_organization("Other Org")
        Project.objects.create(organization=other_organization, code="99999", name="Other")
        Project.objects.create(organization=organization, code="26124", name="Own")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26125")
        self.assertNotIn("99999", suggestion.used_codes)

    def test_inactive_dimensions_are_ignored_for_allocation(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Workspace project")
        AccountingDimension.objects.create(
            organization=organization,
            code="26125",
            name="Inactive dimension",
            is_active=False,
        )

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.suggested_code, "26125")
        self.assertNotIn("26125", suggestion.used_codes)

    def test_metadata_is_not_mutated(self):
        organization = create_organization()
        metadata = {"source": {"requested_by": "test"}}
        original_metadata = {"source": {"requested_by": "test"}}

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization, metadata=metadata)
        )

        suggestion.metadata["source"] = "changed"
        self.assertEqual(metadata, original_metadata)

    def test_returns_source_summary(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Workspace project")
        AccountingDimension.objects.create(organization=organization, code="26125", name="Merit dimension")

        suggestion = ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(suggestion.source_summary["project_codes_count"], 1)
        self.assertEqual(suggestion.source_summary["accounting_dimension_codes_count"], 1)
        self.assertEqual(suggestion.source_summary["used_numeric_codes_count"], 2)

    def test_no_database_writes_except_test_setup(self):
        organization = create_organization()
        Project.objects.create(organization=organization, code="26124", name="Workspace project")
        project_count = Project.objects.count()
        dimension_count = AccountingDimension.objects.count()

        ProjectCodeAllocationService.suggest_next_code(
            SuggestNextProjectCodeCommand(organization=organization)
        )

        self.assertEqual(Project.objects.count(), project_count)
        self.assertEqual(AccountingDimension.objects.count(), dimension_count)


class ManagementCostAllocationModelTests(TestCase):
    def _pool(self, organization=None, name="Office"):
        organization = organization or create_organization()
        return ManagementCostPool.objects.create(
            organization=organization,
            name=name,
            default_strategy=AllocationStrategy.REVENUE,
        )

    def _period(self, organization=None, year=2026, month=6):
        organization = organization or create_organization()
        return ManagementAllocationPeriod.objects.create(organization=organization, year=year, month=month)

    def _project(self, organization=None, code="26124"):
        organization = organization or create_organization()
        return Project.objects.create(organization=organization, code=code, name=f"Project {code}")

    def test_cost_pool_defaults_and_str(self):
        organization = create_organization()

        pool = ManagementCostPool.objects.create(organization=organization, name="Accounting")

        self.assertTrue(pool.is_active)
        self.assertEqual(pool.default_strategy, AllocationStrategy.REVENUE)
        self.assertEqual(str(pool), "Accounting")

    def test_pool_name_unique_per_organization(self):
        organization = create_organization()
        self._pool(organization, "Management")

        with self.assertRaises(ValidationError):
            self._pool(organization, "Management")

    def test_same_pool_name_allowed_for_different_organizations(self):
        self._pool(create_organization("Org 1"), "Office")
        self._pool(create_organization("Org 2"), "Office")

        self.assertEqual(ManagementCostPool.objects.filter(name="Office").count(), 2)

    def test_pool_account_persistence_and_unique_inside_pool(self):
        pool = self._pool()

        account = ManagementCostPoolAccount.objects.create(pool=pool, account_code="5000")

        self.assertTrue(account.is_active)
        self.assertIn("5000", str(account))
        with self.assertRaises(ValidationError):
            ManagementCostPoolAccount.objects.create(pool=pool, account_code="5000")

    def test_one_active_account_code_per_organization(self):
        organization = create_organization()
        office = self._pool(organization, "Office")
        vehicles = self._pool(organization, "Vehicles")
        ManagementCostPoolAccount.objects.create(pool=office, account_code="5000")

        with self.assertRaises(ValidationError):
            ManagementCostPoolAccount.objects.create(pool=vehicles, account_code="5000")

    def test_inactive_duplicate_account_code_allowed(self):
        organization = create_organization()
        office = self._pool(organization, "Office")
        vehicles = self._pool(organization, "Vehicles")
        ManagementCostPoolAccount.objects.create(pool=office, account_code="5000")

        duplicate = ManagementCostPoolAccount.objects.create(pool=vehicles, account_code="5000", is_active=False)

        self.assertFalse(duplicate.is_active)

    def test_period_defaults_label_and_uniqueness(self):
        organization = create_organization()
        period = self._period(organization, year=2026, month=6)

        self.assertEqual(period.status, PeriodStatus.DRAFT)
        self.assertEqual(period.period_label, "2026-06")
        self.assertEqual(str(period), "2026-06")
        with self.assertRaises(ValidationError):
            self._period(organization, year=2026, month=6)

    def test_invalid_month_and_year_rejected(self):
        organization = create_organization()

        with self.assertRaises(ValidationError):
            self._period(organization, year=2026, month=13)
        with self.assertRaises(ValidationError):
            self._period(organization, year=1999, month=6)

    def test_rule_persistence_and_configuration(self):
        pool = self._pool()

        rule = ManagementAllocationRule.objects.create(
            pool=pool,
            strategy=AllocationStrategy.PROJECT_MANAGER,
            configuration={"project_manager_role": "project_manager"},
        )

        self.assertTrue(rule.is_active)
        self.assertEqual(rule.configuration["project_manager_role"], "project_manager")
        self.assertIn(AllocationStrategy.PROJECT_MANAGER, str(rule))

    def test_version_defaults_and_str(self):
        organization = create_organization()
        pool = self._pool(organization)
        period = self._period(organization)

        version = ManagementAllocationVersion.objects.create(period=period, pool=pool, version_number=1)

        self.assertEqual(version.status, VersionStatus.DRAFT)
        self.assertIn("v1", str(version))

    def test_negative_version_number_rejected(self):
        organization = create_organization()
        pool = self._pool(organization)
        period = self._period(organization)

        with self.assertRaises(ValidationError):
            ManagementAllocationVersion.objects.create(period=period, pool=pool, version_number=-1)

    def test_pool_and_period_must_share_organization(self):
        pool = self._pool(create_organization("Pool Org"))
        period = self._period(create_organization("Period Org"))

        with self.assertRaises(ValidationError):
            ManagementAllocationVersion.objects.create(period=period, pool=pool, version_number=1)

    def test_entry_persistence(self):
        organization = create_organization()
        pool = self._pool(organization)
        period = self._period(organization)
        project = self._project(organization)
        version = ManagementAllocationVersion.objects.create(period=period, pool=pool, version_number=1)

        entry = ManagementAllocationEntry.objects.create(
            version=version,
            project=project,
            percentage=Decimal("25.0000"),
            amount=Decimal("123.450000"),
            manual_override=True,
            notes="Reviewed",
        )

        self.assertEqual(entry.percentage, Decimal("25.0000"))
        self.assertEqual(entry.amount, Decimal("123.450000"))
        self.assertTrue(entry.manual_override)
        self.assertIn(project.code, str(entry))

    def test_invalid_percentage_rejected(self):
        organization = create_organization()
        pool = self._pool(organization)
        period = self._period(organization)
        project = self._project(organization)
        version = ManagementAllocationVersion.objects.create(period=period, pool=pool, version_number=1)

        with self.assertRaises(ValidationError):
            ManagementAllocationEntry.objects.create(version=version, project=project, percentage=Decimal("-1"))
        with self.assertRaises(ValidationError):
            ManagementAllocationEntry.objects.create(version=version, project=project, percentage=Decimal("101"))

    def test_entry_project_must_share_organization(self):
        organization = create_organization()
        pool = self._pool(organization)
        period = self._period(organization)
        version = ManagementAllocationVersion.objects.create(period=period, pool=pool, version_number=1)
        project = self._project(create_organization("Other Org"), code="99999")

        with self.assertRaises(ValidationError):
            ManagementAllocationEntry.objects.create(version=version, project=project)

    def test_admin_registration(self):
        for model in (
            ManagementCostPool,
            ManagementCostPoolAccount,
            ManagementAllocationPeriod,
            ManagementAllocationVersion,
            ManagementAllocationRule,
            ManagementAllocationEntry,
        ):
            self.assertIn(model, admin.site._registry)

    def test_enums_expose_expected_values(self):
        self.assertEqual(AllocationStrategy.REVENUE, "revenue")
        self.assertEqual(AllocationStrategy.EQUAL, "equal")
        self.assertEqual(AllocationStrategy.MANUAL_PERCENT, "manual_percent")
        self.assertEqual(AllocationStrategy.MANUAL_AMOUNT, "manual_amount")
        self.assertEqual(AllocationStrategy.PROJECT_MANAGER, "project_manager")
        self.assertEqual(PeriodStatus.APPROVED, "approved")
        self.assertEqual(VersionStatus.SUPERSEDED, "superseded")


class ManagementCostAllocationServiceTests(TestCase):
    def _setup_version(self):
        organization = create_organization()
        pool = ManagementCostPool.objects.create(organization=organization, name="Office")
        period = ManagementAllocationPeriod.objects.create(organization=organization, year=2026, month=6)
        version = ManagementAllocationVersion.objects.create(period=period, pool=pool, version_number=1)
        return organization, pool, period, version

    def test_create_pool_creates_audit_event(self):
        organization = create_organization()

        pool = ManagementCostPoolService.create_pool(
            CreateManagementCostPoolCommand(
                organization=organization,
                name="Administration",
                description="Back office",
                display_order=10,
            )
        )

        self.assertEqual(pool.name, "Administration")
        self.assertEqual(
            AuditEvent.objects.filter(event_type="management_cost_pool_created", object_id=str(pool.id)).count(),
            1,
        )

    def test_create_rule_creates_audit_and_does_not_mutate_configuration(self):
        pool = ManagementCostPool.objects.create(organization=create_organization(), name="Management")
        configuration = {"basis": {"type": "revenue"}}
        original_configuration = {"basis": {"type": "revenue"}}

        rule = ManagementCostPoolService.create_rule(
            CreateManagementAllocationRuleCommand(
                pool=pool,
                strategy=AllocationStrategy.REVENUE,
                configuration=configuration,
                metadata={"source": "test"},
            )
        )

        self.assertEqual(rule.configuration, original_configuration)
        self.assertEqual(configuration, original_configuration)
        self.assertEqual(AuditEvent.objects.filter(event_type="management_allocation_rule_created").count(), 1)

    def test_create_version_auto_increments_version_number(self):
        organization, pool, period, first = self._setup_version()

        second = ManagementAllocationVersionService.create_version(
            CreateManagementAllocationVersionCommand(period=period, pool=pool)
        )

        self.assertEqual(first.version_number, 1)
        self.assertEqual(second.version_number, 2)
        self.assertEqual(second.status, VersionStatus.DRAFT)
        self.assertEqual(AuditEvent.objects.filter(event_type="management_allocation_version_created").count(), 1)

    def test_approve_version_sets_status_and_audit(self):
        organization, pool, period, version = self._setup_version()

        approved = ManagementAllocationVersionService.approve(
            ApproveManagementAllocationVersionCommand(version=version, reason="Monthly review")
        )

        self.assertEqual(approved.status, VersionStatus.APPROVED)
        self.assertIsNotNone(approved.approved_at)
        self.assertEqual(approved.reason, "Monthly review")
        self.assertEqual(AuditEvent.objects.filter(event_type="management_allocation_version_approved").count(), 1)

    def test_approving_new_version_supersedes_previous_approved_version(self):
        organization, pool, period, first = self._setup_version()
        ManagementAllocationVersionService.approve(ApproveManagementAllocationVersionCommand(version=first))
        second = ManagementAllocationVersionService.create_version(
            CreateManagementAllocationVersionCommand(period=period, pool=pool)
        )

        approved = ManagementAllocationVersionService.approve(ApproveManagementAllocationVersionCommand(version=second))
        first.refresh_from_db()

        self.assertEqual(approved.status, VersionStatus.APPROVED)
        self.assertEqual(first.status, VersionStatus.SUPERSEDED)
        self.assertEqual(
            ManagementAllocationVersion.objects.filter(period=period, pool=pool, status=VersionStatus.APPROVED).count(),
            1,
        )
        self.assertEqual(AuditEvent.objects.filter(event_type="management_allocation_version_superseded").count(), 1)

    def test_inactive_pool_approval_rejected(self):
        organization, pool, period, version = self._setup_version()
        pool.is_active = False
        pool.save()

        with self.assertRaisesMessage(ValueError, "Inactive management cost pools cannot be approved"):
            ManagementAllocationVersionService.approve(ApproveManagementAllocationVersionCommand(version=version))

    def test_metadata_not_mutated(self):
        organization, pool, period, version = self._setup_version()
        metadata = {"source": {"screen": "approval"}}
        original_metadata = {"source": {"screen": "approval"}}

        ManagementAllocationVersionService.approve(
            ApproveManagementAllocationVersionCommand(version=version, metadata=metadata)
        )

        self.assertEqual(metadata, original_metadata)

    def test_organization_isolation(self):
        first_org = create_organization("First Org")
        second_org = create_organization("Second Org")
        ManagementCostPool.objects.create(organization=first_org, name="Office")
        ManagementCostPool.objects.create(organization=second_org, name="Office")

        self.assertEqual(ManagementCostPool.objects.filter(organization=first_org).count(), 1)
        self.assertEqual(ManagementCostPool.objects.filter(organization=second_org).count(), 1)

    def test_rollback_if_audit_fails(self):
        organization = create_organization()

        with patch("apps.accounting.services.management_allocations.AuditService.record") as audit_mock:
            audit_mock.side_effect = RuntimeError("audit failed")
            with self.assertRaises(RuntimeError):
                ManagementCostPoolService.create_pool(
                    CreateManagementCostPoolCommand(organization=organization, name="Rollback Pool")
                )

        self.assertFalse(ManagementCostPool.objects.filter(name="Rollback Pool").exists())


class FakeAggregationService:
    def __init__(self, revenues, costs=None, data_quality_status="ok"):
        self.revenues = revenues
        self.costs = costs or {}
        self.data_quality_status = data_quality_status
        self.calls = []

    def aggregate(self, command):
        self.calls.append(command)
        return type(
            "AggregationResult",
            (),
            {
                "revenue": self.revenues.get(command.project.id, Decimal("0")),
                "total_cost": self.costs.get(command.project.id, Decimal("0")),
                "result": self.revenues.get(command.project.id, Decimal("0")) - self.costs.get(command.project.id, Decimal("0")),
                "currency": command.currency or "EUR",
                "data_quality_status": self.data_quality_status,
                "warnings": ["mixed_currency"] if self.data_quality_status == "mixed_currency" else [],
                "allocation_count": 1,
                "source_batch_count": 1,
                "source_entry_count": 1,
            },
        )()


class ManagementAllocationProposalServiceTests(TestCase):
    def _setup(self):
        organization = create_organization()
        pool = ManagementCostPool.objects.create(organization=organization, name="Office")
        first = Project.objects.create(organization=organization, code="26124", name="First")
        second = Project.objects.create(organization=organization, code="26125", name="Second")
        third = Project.objects.create(organization=organization, code="26126", name="Third")
        return organization, pool, first, second, third

    def _command(self, pool, projects, **kwargs):
        defaults = {
            "pool": pool,
            "year": 2026,
            "month": 6,
            "project_ids": [project.id for project in projects],
            "source_amount": Decimal("100.00"),
        }
        defaults.update(kwargs)
        return GenerateManagementAllocationProposalCommand(**defaults)

    def _service(self, revenues=None, costs=None, data_quality_status="ok"):
        return ManagementAllocationProposalService(
            project_financial_aggregation_service=FakeAggregationService(
                revenues or {},
                costs=costs,
                data_quality_status=data_quality_status,
            )
        )

    def _gl_entry(self, organization, *, account_code="5000", batch_date=date(2026, 6, 15), debit="100.000000", credit="0.000000", suffix="1"):
        integration = create_merit_integration(organization)
        batch = AccountingGLBatch.objects.create(
            organization=organization,
            integration=integration,
            external_id=f"mgmt-batch-{suffix}",
            batch_date=batch_date,
        )
        return AccountingGLEntry.objects.create(
            organization=organization,
            integration=integration,
            batch=batch,
            external_id=f"mgmt-entry-{suffix}",
            account_code=account_code,
            debit_amount=Decimal(debit),
            credit_amount=Decimal(credit),
        )

    def test_period_created_for_valid_month_and_metadata_not_mutated(self):
        organization, pool, first, second, third = self._setup()
        metadata = {"source": {"screen": "test"}}
        original = deepcopy(metadata)

        result = self._service().generate(
            self._command(pool, [first, second], strategy=AllocationStrategy.EQUAL, metadata=metadata)
        )

        self.assertEqual(result.period.period_label, "2026-06")
        self.assertEqual(result.version.status, VersionStatus.DRAFT)
        self.assertEqual(metadata, original)

    def test_invalid_month_inactive_pool_empty_projects_and_archived_period_rejected(self):
        organization, pool, first, second, third = self._setup()

        with self.assertRaisesMessage(ValueError, "month must be between 1 and 12"):
            self._service().generate(self._command(pool, [first], month=13, strategy=AllocationStrategy.EQUAL))
        pool.is_active = False
        pool.save()
        with self.assertRaisesMessage(ValueError, "Inactive management cost pools"):
            self._service().generate(self._command(pool, [first], strategy=AllocationStrategy.EQUAL))
        pool.is_active = True
        pool.save()
        with self.assertRaisesMessage(ValueError, "requires at least one selected project"):
            self._service().generate(self._command(pool, [], strategy=AllocationStrategy.EQUAL))
        ManagementAllocationPeriod.objects.create(
            organization=organization,
            year=2026,
            month=7,
            status=PeriodStatus.ARCHIVED,
        )
        with self.assertRaisesMessage(ValueError, "Archived management allocation periods"):
            self._service().generate(self._command(pool, [first], month=7, strategy=AllocationStrategy.EQUAL))

    def test_organization_isolation(self):
        organization, pool, first, second, third = self._setup()
        other_project = Project.objects.create(organization=create_organization("Other"), code="999", name="Other")

        with self.assertRaisesMessage(ValueError, "belong to the pool organization"):
            self._service().generate(self._command(pool, [first, other_project], strategy=AllocationStrategy.EQUAL))

    def test_manual_source_amount_used_and_warning_for_existing_draft(self):
        organization, pool, first, second, third = self._setup()
        ManagementAllocationPeriod.objects.create(organization=organization, year=2026, month=6)
        ManagementAllocationVersion.objects.create(
            period=ManagementAllocationPeriod.objects.get(organization=organization, year=2026, month=6),
            pool=pool,
            version_number=1,
        )

        result = self._service().generate(self._command(pool, [first, second], strategy=AllocationStrategy.EQUAL))

        self.assertEqual(result.source_amount, Decimal("100.00"))
        self.assertEqual(result.version.metadata["source_amount_origin"], "manual")
        self.assertIn("existing_draft_version", [warning["code"] for warning in result.warnings])

    def test_gl_derived_source_amount_uses_debit_minus_credit_and_month_boundaries(self):
        organization, pool, first, second, third = self._setup()
        ManagementCostPoolAccount.objects.create(pool=pool, account_code="5000")
        ManagementCostPoolAccount.objects.create(pool=pool, account_code="5100")
        self._gl_entry(organization, account_code="5000", debit="100.000000", credit="0.000000", suffix="1")
        self._gl_entry(organization, account_code="5100", debit="50.000000", credit="10.000000", suffix="2")
        self._gl_entry(organization, account_code="5200", debit="999.000000", credit="0.000000", suffix="unmapped")
        self._gl_entry(organization, account_code="5000", batch_date=date(2026, 7, 1), debit="999.000000", suffix="outside")

        result = self._service().generate(
            self._command(pool, [first, second], strategy=AllocationStrategy.EQUAL, source_amount=None)
        )

        self.assertEqual(result.source_amount, Decimal("140.000000"))
        self.assertEqual(result.version.metadata["source_amount_origin"], "gl_pool_accounts")
        self.assertEqual(result.version.metadata["calculation_diagnostics"]["source"]["amount_semantics"], "debit_amount_minus_credit_amount")

    def test_workspace_project_source_uses_project_direct_cost_and_traceability(self):
        organization, pool, first, second, third = self._setup()
        service = self._service(costs={first.id: Decimal("345.670000")})

        result = service.generate(
            GenerateManagementAllocationProposalCommand(
                year=2026,
                month=6,
                project_ids=[second.id, third.id],
                source_type=AllocationSourceType.WORKSPACE_PROJECT,
                source_project=first,
                source_amount_basis=AllocationSourceAmountBasis.PROJECT_DIRECT_COST,
                source_currency="EUR",
                strategy=AllocationStrategy.EQUAL,
            )
        )

        self.assertIsNone(result.pool)
        self.assertEqual(result.source_project, first)
        self.assertEqual(result.source_amount, Decimal("345.670000"))
        self.assertEqual(result.version.source_type, AllocationSourceType.WORKSPACE_PROJECT)
        self.assertIsNone(result.version.pool)
        self.assertEqual(result.version.source_project, first)
        self.assertEqual(result.version.source_amount_basis, AllocationSourceAmountBasis.PROJECT_DIRECT_COST)
        self.assertEqual(result.version.metadata["source_amount_origin"], "workspace_project_direct_cost")
        self.assertEqual(result.version.metadata["source_project_code"], first.code)
        self.assertEqual(result.version.metadata["calculation_diagnostics"]["source"]["direct_cost"], "345.670000")
        self.assertEqual([entry.project for entry in result.entries], [second, third])

    def test_workspace_project_source_cannot_be_target_or_mixed_currency_without_explicit_currency(self):
        organization, pool, first, second, third = self._setup()

        with self.assertRaisesMessage(ValueError, "source Project cannot also be selected"):
            self._service(costs={first.id: Decimal("100")}).generate(
                GenerateManagementAllocationProposalCommand(
                    year=2026,
                    month=6,
                    project_ids=[first.id, second.id],
                    source_type=AllocationSourceType.WORKSPACE_PROJECT,
                    source_project=first,
                    source_amount_basis=AllocationSourceAmountBasis.PROJECT_DIRECT_COST,
                    strategy=AllocationStrategy.EQUAL,
                )
            )
        with self.assertRaisesMessage(ValueError, "mixed currency"):
            self._service(costs={first.id: Decimal("100")}, data_quality_status="mixed_currency").generate(
                GenerateManagementAllocationProposalCommand(
                    year=2026,
                    month=6,
                    project_ids=[second.id],
                    source_type=AllocationSourceType.WORKSPACE_PROJECT,
                    source_project=first,
                    source_amount_basis=AllocationSourceAmountBasis.PROJECT_DIRECT_COST,
                    strategy=AllocationStrategy.EQUAL,
                )
            )

    def test_reversal_negative_source_amount_from_gl(self):
        organization, pool, first, second, third = self._setup()
        ManagementCostPoolAccount.objects.create(pool=pool, account_code="5000")
        self._gl_entry(organization, account_code="5000", debit="0.000000", credit="80.000000")

        result = self._service().generate(
            self._command(pool, [first, second], strategy=AllocationStrategy.EQUAL, source_amount=None)
        )

        self.assertEqual(result.source_amount, Decimal("-80.000000"))
        self.assertEqual(sum(entry.amount for entry in result.entries), Decimal("-80.000000"))

    def test_zero_source_amount_warning(self):
        organization, pool, first, second, third = self._setup()

        result = self._service().generate(
            self._command(pool, [first, second], strategy=AllocationStrategy.EQUAL, source_amount=Decimal("0"))
        )

        self.assertEqual(result.allocated_amount, Decimal("0.00"))
        self.assertIn("zero_source_amount", [warning["code"] for warning in result.warnings])

    def test_revenue_strategy_weights_by_positive_revenue(self):
        organization, pool, first, second, third = self._setup()
        service = self._service({first.id: Decimal("300"), second.id: Decimal("100")})

        result = service.generate(self._command(pool, [first, second], strategy=AllocationStrategy.REVENUE))

        self.assertEqual([entry.amount for entry in result.entries], [Decimal("75.00"), Decimal("25.00")])
        self.assertEqual(sum(entry.percentage for entry in result.entries), Decimal("100.0000"))
        self.assertEqual(len(service.project_financial_aggregation_service.calls), 2)

    def test_revenue_strategy_warns_zero_and_negative_revenue_and_fails_without_positive_basis(self):
        organization, pool, first, second, third = self._setup()
        result = self._service({first.id: Decimal("100"), second.id: Decimal("0"), third.id: Decimal("-50")}).generate(
            self._command(pool, [first, second, third], strategy=AllocationStrategy.REVENUE)
        )

        self.assertEqual([entry.amount for entry in result.entries], [Decimal("100.00"), Decimal("0.00"), Decimal("0.00")])
        self.assertIn("zero_revenue_project", [warning["code"] for warning in result.warnings])
        self.assertIn("negative_revenue_project_excluded", [warning["code"] for warning in result.warnings])
        with self.assertRaisesMessage(ValueError, "requires positive selected-project revenue"):
            self._service({first.id: Decimal("0"), second.id: Decimal("-1")}).generate(
                self._command(pool, [first, second], strategy=AllocationStrategy.REVENUE)
            )

    def test_equal_strategy_rounding_and_negative_amounts(self):
        organization, pool, first, second, third = self._setup()

        result = self._service().generate(
            self._command(pool, [first, second, third], strategy=AllocationStrategy.EQUAL, source_amount=Decimal("100.00"))
        )
        negative = self._service().generate(
            self._command(pool, [first, second], strategy=AllocationStrategy.EQUAL, source_amount=Decimal("-10.00"), month=7)
        )

        self.assertEqual([entry.amount for entry in result.entries], [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")])
        self.assertEqual(sum(entry.amount for entry in result.entries), Decimal("100.00"))
        self.assertEqual(sum(entry.percentage for entry in result.entries), Decimal("100.0000"))
        self.assertEqual(sum(entry.amount for entry in negative.entries), Decimal("-10.00"))

    def test_manual_percentages_valid_and_invalid(self):
        organization, pool, first, second, third = self._setup()
        result = self._service().generate(
            self._command(
                pool,
                [first, second],
                strategy=AllocationStrategy.MANUAL_PERCENT,
                manual_percentages={first.id: Decimal("60"), second.id: Decimal("40")},
            )
        )

        self.assertEqual([entry.amount for entry in result.entries], [Decimal("60.00"), Decimal("40.00")])
        self.assertTrue(all(entry.manual_override for entry in result.entries))
        with self.assertRaisesMessage(ValueError, "cannot be negative"):
            self._service().generate(
                self._command(pool, [first, second], strategy=AllocationStrategy.MANUAL_PERCENT, manual_percentages={first.id: -1, second.id: 101})
            )
        with self.assertRaisesMessage(ValueError, "must total exactly 100"):
            self._service().generate(
                self._command(pool, [first, second], strategy=AllocationStrategy.MANUAL_PERCENT, manual_percentages={first.id: 60, second.id: 30})
            )
        with self.assertRaisesMessage(ValueError, "unknown project"):
            self._service().generate(
                self._command(pool, [first, second], strategy=AllocationStrategy.MANUAL_PERCENT, manual_percentages={first.id: 60, second.id: 40, 9999: 0})
            )

    def test_manual_amounts_valid_and_invalid(self):
        organization, pool, first, second, third = self._setup()
        result = self._service().generate(
            self._command(
                pool,
                [first, second],
                strategy=AllocationStrategy.MANUAL_AMOUNT,
                manual_amounts={first.id: Decimal("70.00"), second.id: Decimal("30.00")},
            )
        )

        self.assertEqual([entry.percentage for entry in result.entries], [Decimal("70.0000"), Decimal("30.0000")])
        self.assertTrue(all(entry.manual_override for entry in result.entries))
        with self.assertRaisesMessage(ValueError, "must total exactly"):
            self._service().generate(
                self._command(pool, [first, second], strategy=AllocationStrategy.MANUAL_AMOUNT, manual_amounts={first.id: 70, second.id: 20})
            )
        with self.assertRaisesMessage(ValueError, "unknown project"):
            self._service().generate(
                self._command(pool, [first, second], strategy=AllocationStrategy.MANUAL_AMOUNT, manual_amounts={first.id: 100, 9999: 0})
            )
        negative = self._service().generate(
            self._command(
                pool,
                [first, second],
                strategy=AllocationStrategy.MANUAL_AMOUNT,
                source_amount=Decimal("-100.00"),
                manual_amounts={first.id: Decimal("-70.00"), second.id: Decimal("-30.00")},
                month=7,
            )
        )
        self.assertEqual(sum(entry.amount for entry in negative.entries), Decimal("-100.00"))

    def test_project_manager_strategy_requires_manager_and_respects_explicit_projects(self):
        organization, pool, first, second, third = self._setup()
        manager_one = ProjectParty.objects.create(
            organization=organization,
            project=first,
            name="Manager",
            email="manager@example.com",
            role=ProjectParty.Role.PROJECT_MANAGER,
        )
        ProjectParty.objects.create(
            organization=organization,
            project=second,
            name="Manager",
            email="manager@example.com",
            role=ProjectParty.Role.PROJECT_MANAGER,
        )

        with self.assertRaisesMessage(ValueError, "requires project_manager_id"):
            self._service().generate(self._command(pool, [first], strategy=AllocationStrategy.PROJECT_MANAGER))
        result = self._service({first.id: Decimal("100"), second.id: Decimal("100")}).generate(
            self._command(
                pool,
                [first, second],
                strategy=AllocationStrategy.PROJECT_MANAGER,
                project_manager_id=manager_one.id,
            )
        )
        self.assertEqual(result.project_count, 2)
        self.assertEqual(result.version.metadata["project_manager_id"], manager_one.id)
        with self.assertRaisesMessage(ValueError, "must be related"):
            self._service({first.id: Decimal("100"), third.id: Decimal("100")}).generate(
                self._command(pool, [first, third], strategy=AllocationStrategy.PROJECT_MANAGER, project_manager_id=manager_one.id, month=7)
            )

    def test_project_manager_rule_can_use_equal_basis(self):
        organization, pool, first, second, third = self._setup()
        manager_one = ProjectParty.objects.create(
            organization=organization,
            project=first,
            name="Manager",
            email="manager@example.com",
            role=ProjectParty.Role.PROJECT_MANAGER,
        )
        ProjectParty.objects.create(
            organization=organization,
            project=second,
            name="Manager",
            email="manager@example.com",
            role=ProjectParty.Role.PROJECT_MANAGER,
        )
        ManagementAllocationRule.objects.create(
            pool=pool,
            strategy=AllocationStrategy.PROJECT_MANAGER,
            configuration={"basis": "equal"},
        )

        result = self._service({first.id: Decimal("1000"), second.id: Decimal("1")}).generate(
            self._command(pool, [first, second], strategy=None, project_manager_id=manager_one.id)
        )

        self.assertEqual([entry.amount for entry in result.entries], [Decimal("50.00"), Decimal("50.00")])

    def test_versioning_keeps_history_draft_and_no_auto_superseding(self):
        organization, pool, first, second, third = self._setup()
        first_result = self._service().generate(self._command(pool, [first], strategy=AllocationStrategy.EQUAL))
        ManagementAllocationVersionService.approve(ApproveManagementAllocationVersionCommand(version=first_result.version))

        second_result = self._service().generate(self._command(pool, [first], strategy=AllocationStrategy.EQUAL, month=6))
        first_result.version.refresh_from_db()

        self.assertEqual(first_result.version.status, VersionStatus.APPROVED)
        self.assertEqual(second_result.version.version_number, 2)
        self.assertEqual(second_result.version.status, VersionStatus.DRAFT)
        self.assertEqual(ManagementAllocationEntry.objects.filter(version=second_result.version, project=first).count(), 1)

    def test_preview_is_read_only_and_matches_generated_entries(self):
        organization, pool, first, second, third = self._setup()
        service = self._service({first.id: Decimal("300"), second.id: Decimal("100")})
        command = self._command(pool, [first, second], strategy=AllocationStrategy.REVENUE)
        counts = (
            ManagementAllocationPeriod.objects.count(),
            ManagementAllocationVersion.objects.count(),
            ManagementAllocationEntry.objects.count(),
            AuditEvent.objects.count(),
        )

        preview = service.preview(command)
        repeated_preview = service.preview(command)

        self.assertEqual(
            counts,
            (
                ManagementAllocationPeriod.objects.count(),
                ManagementAllocationVersion.objects.count(),
                ManagementAllocationEntry.objects.count(),
                AuditEvent.objects.count(),
            ),
        )
        self.assertEqual(preview.created, False)
        self.assertEqual(preview.source_amount, Decimal("100.00"))
        self.assertEqual(preview.allocated_amount, Decimal("100.00"))
        self.assertEqual(preview.unallocated_amount, Decimal("0.00"))
        self.assertEqual(preview.total_percentage, Decimal("100.0000"))
        self.assertEqual([entry.allocated_amount for entry in preview.entries], [Decimal("75.00"), Decimal("25.00")])
        self.assertEqual(preview.metadata["fingerprint"], repeated_preview.metadata["fingerprint"])

        generated = service.generate(command)

        self.assertEqual([entry.amount for entry in generated.entries], [entry.allocated_amount for entry in preview.entries])
        self.assertEqual(generated.metadata["fingerprint"], preview.metadata["fingerprint"])
        self.assertEqual(ManagementAllocationVersion.objects.count(), 1)

    def test_preview_before_after_values_use_existing_approved_allocations_only(self):
        organization, pool, first, second, third = self._setup()
        period = ManagementAllocationPeriod.objects.create(organization=organization, year=2026, month=6)
        approved = ManagementAllocationVersion.objects.create(
            period=period,
            pool=pool,
            version_number=1,
            status=VersionStatus.APPROVED,
            approved_at=timezone.now(),
            metadata={"source_amount": "10.00", "source_amount_origin": "manual"},
        )
        ManagementAllocationEntry.objects.create(
            version=approved,
            project=first,
            percentage=Decimal("100.0000"),
            amount=Decimal("10.00"),
        )
        draft = ManagementAllocationVersion.objects.create(
            period=period,
            pool=pool,
            version_number=2,
            status=VersionStatus.DRAFT,
            metadata={"source_amount": "99.00", "source_amount_origin": "manual"},
        )
        ManagementAllocationEntry.objects.create(
            version=draft,
            project=first,
            percentage=Decimal("100.0000"),
            amount=Decimal("99.00"),
        )

        preview = self._service(costs={first.id: Decimal("5")}).preview(
            self._command(pool, [first], strategy=AllocationStrategy.EQUAL, source_amount=Decimal("20.00"))
        )
        entry = preview.entries[0]

        self.assertEqual(entry.before_direct_cost, Decimal("5"))
        self.assertEqual(entry.current_allocated_in, Decimal("10.00"))
        self.assertEqual(entry.current_management_total_cost, Decimal("15.00"))
        self.assertEqual(entry.allocated_amount, Decimal("20.00"))
        self.assertEqual(entry.projected_management_total_cost, Decimal("35.00"))
        self.assertIn("existing_draft_version", [warning["code"] for warning in preview.warnings])

    def test_rollback_when_entry_creation_fails_and_no_audit(self):
        organization, pool, first, second, third = self._setup()

        with patch("apps.accounting.services.management_allocations.ManagementAllocationEntry.objects.create") as create_mock:
            create_mock.side_effect = RuntimeError("entry failed")
            with self.assertRaises(RuntimeError):
                self._service().generate(self._command(pool, [first], strategy=AllocationStrategy.EQUAL))

        self.assertFalse(ManagementAllocationVersion.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(event_type="management_allocation_proposal_generated").exists())

    def test_success_audit_and_no_source_model_mutation_or_merit_api(self):
        organization, pool, first, second, third = self._setup()
        entry_count = AccountingGLEntry.objects.count()
        project_count = Project.objects.count()

        with patch("apps.accounting.connectors.MeritAPIClient.request") as request_mock:
            result = self._service().generate(self._command(pool, [first], strategy=AllocationStrategy.EQUAL))

        request_mock.assert_not_called()
        self.assertEqual(AccountingGLEntry.objects.count(), entry_count)
        self.assertEqual(Project.objects.count(), project_count)
        event = AuditEvent.objects.get(event_type="management_allocation_proposal_generated")
        self.assertEqual(event.metadata["strategy"], AllocationStrategy.EQUAL)
        self.assertEqual(event.metadata["allocated_amount"], str(result.allocated_amount))
