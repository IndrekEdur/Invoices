from unittest.mock import patch
from types import SimpleNamespace
from decimal import Decimal

from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.communications.models import (
    EmailAccount,
    EmailAnswerDraft,
    EmailAttachment,
    EmailMessage,
    EmailProjectLink,
    EmailQuestion,
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
    AllocationSourceType,
    AllocationStrategy,
    FinancialAlert,
    FinancialAlertBasis,
    FinancialAlertEvaluationRun,
    FinancialAlertEvaluationRunStatus,
    FinancialAlertRule,
    FinancialAlertSeverity,
    FinancialAlertStatus,
    FinancialAlertType,
    ManagementAllocationEntry,
    ManagementAllocationPeriod,
    ManagementAllocationVersion,
    ManagementCostPool,
    ManagementCostPoolAccount,
    VersionStatus,
)
from apps.accounting.connectors import MeritAPIClient
from apps.accounting.services import (
    AggregateProjectFinancialsCommand,
    CreateAccountingDimensionValueResult,
    ManagementAllocationProposalService,
    ManagementAllocationVersionService,
    ApproveManagementAllocationVersionCommand,
    ProjectFinancialAggregationService,
    SyncAccountingDimensionsResult,
    SyncGeneralLedgerResult,
)
from apps.core.models import AuditEvent
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.documents.models import Document
from apps.knowledge.services import ProjectKnowledgeBuilder
from apps.projects.models import Project, ProjectAddress, ProjectParty
from apps.projects.services import (
    ChangeProjectStatusCommand,
    CreateProjectFromAccountingDimensionResult,
    CreateProjectWithSuggestedCodeResult,
    ProjectStatusService,
)
from apps.workflow.models import WorkflowDefinition, WorkflowInstance, WorkflowState
from apps.workspace.forms import calendar_month_bounds


def create_organization(name="Workspace Org"):
    return OrganizationService.create(CreateOrganizationCommand(name=name))


def create_email_account(organization, **kwargs):
    defaults = {
        "provider": EmailAccount.Provider.IMAP,
        "display_name": "Workspace mailbox",
        "email_address": "workspace@example.com",
        "username": "workspace@example.com",
        "host": "mail.example.com",
        "port": 993,
        "encrypted_secret_placeholder": "stored-secret",
    }
    defaults.update(kwargs)
    return EmailAccount.objects.create(
        organization=organization,
        **defaults,
    )


def create_email_message(organization, subject="Workspace email"):
    account = create_email_account(organization)
    return EmailMessage.objects.create(
        organization=organization,
        account=account,
        external_message_id=f"{subject}-id",
        subject=subject,
        body_text="Workspace body text",
        sender_email="sender@example.com",
        sender_name="Sender Name",
        recipients=["receiver@example.com"],
        received_at=timezone.now(),
    )


def create_project(organization, code="26070", name="Workspace Project"):
    return Project.objects.create(organization=organization, code=code, name=name)


def create_financial_alert(project, **kwargs):
    alert_type = kwargs.get("alert_type", FinancialAlertType.PROJECT_LIFETIME_NEGATIVE)
    rule = kwargs.pop("rule", None) or FinancialAlertRule.objects.filter(
        organization=project.organization,
        alert_type=alert_type,
        is_active=True,
    ).first()
    if rule is None:
        rule = FinancialAlertRule.objects.create(
            organization=project.organization,
            alert_type=alert_type,
            name=f"Rule {alert_type}",
            financial_basis=kwargs.get("financial_basis", FinancialAlertBasis.MANAGEMENT),
            severity=kwargs.get("severity", FinancialAlertSeverity.WARNING),
        )
    defaults = {
        "organization": project.organization,
        "project": project,
        "rule": rule,
        "alert_type": FinancialAlertType.PROJECT_LIFETIME_NEGATIVE,
        "financial_basis": FinancialAlertBasis.MANAGEMENT,
        "severity": FinancialAlertSeverity.WARNING,
        "status": FinancialAlertStatus.OPEN,
        "fingerprint": f"alert-{project.id}-{timezone.now().timestamp()}",
        "title": f"{project.code} negative result",
        "message": "Project result is below threshold.",
        "period_start": None,
        "period_end": None,
        "currency": "EUR",
        "accounting_amount": Decimal("-100.00"),
        "management_amount": Decimal("-120.00"),
        "evaluated_amount": Decimal("-120.00"),
        "threshold_amount": Decimal("0.00"),
        "data_quality_status": "complete",
        "metadata": {"warnings": ["review result"], "api_secret": "never-render", "signature": "never-render"},
    }
    defaults.update(kwargs)
    return FinancialAlert.objects.create(**defaults)


def create_merit_integration(organization, metadata=None):
    return AccountingIntegration.objects.create(
        organization=organization,
        provider=AccountingIntegration.Provider.MERIT,
        display_name="Merit Aktiva",
        api_base_url="https://merit.example.test",
        api_id="api-id",
        encrypted_secret_placeholder="api-secret",
        metadata=metadata or {},
    )


def create_gl_account(organization, integration=None, account_code="4000", account_name="Materials", project=None):
    integration = integration or create_merit_integration(organization)
    batch = AccountingGLBatch.objects.create(
        organization=organization,
        integration=integration,
        external_id=f"batch-{account_code}",
        batch_date=timezone.datetime(2026, 6, 1).date(),
        currency_code="EUR",
    )
    entry = AccountingGLEntry.objects.create(
        organization=organization,
        integration=integration,
        batch=batch,
        external_id=f"entry-{account_code}",
        account_code=account_code,
        account_name=account_name,
        debit_amount="100.000000",
        credit_amount="25.000000",
        memo=f"{account_name} memo",
    )
    allocation = AccountingGLAllocation.objects.create(
        organization=organization,
        integration=integration,
        entry=entry,
        external_id=f"alloc-{account_code}",
        dimension_code=project.code if project else "26124",
        amount="75.000000",
        project=project,
    )
    return integration, batch, entry, allocation


class WorkspaceRouteTests(TestCase):
    routes = [
        ("workspace:home", "/workspace/"),
        ("workspace:dashboard", "/workspace/dashboard/"),
        ("workspace:inbox", "/workspace/inbox/"),
        ("workspace:projects", "/workspace/projects/"),
        ("workspace:financial_dashboard", "/workspace/financials/"),
        ("workspace:documents", "/workspace/documents/"),
        ("workspace:reviews", "/workspace/reviews/"),
        ("workspace:search", "/workspace/search/"),
        ("workspace:assistant", "/workspace/assistant/"),
        ("workspace:settings", "/workspace/settings/"),
        ("workspace:design_system", "/workspace/design-system/"),
        ("workspace:accounting_dimension_conflicts", "/workspace/accounting/dimensions/conflicts/"),
        ("workspace:settings_account_classifications", "/workspace/settings/account-classifications/"),
        ("workspace:settings_financial_alert_rules", "/workspace/settings/financial-alert-rules/"),
    ]

    def test_every_workspace_route_returns_http_200(self):
        for route_name, path in self.routes:
            with self.subTest(route_name=route_name):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)

    def test_url_namespace_works(self):
        for route_name, path in self.routes:
            with self.subTest(route_name=route_name):
                self.assertEqual(reverse(route_name), path)

    def test_templates_render_base_layout(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Operations Workspace Platform")
        self.assertContains(response, "Dashboard")
        self.assertContains(response, "workspace-content")

    def test_dashboard_cards_render(self):
        response = self.client.get(reverse("workspace:dashboard"))

        for title in [
            "Total Imported Emails",
            "Emails Needing Project Confirmation",
            "Detected Questions",
            "Answer Drafts Needing Review",
            "Active Projects",
            "Documents",
            "Workflow Instances",
            "Audit Events Today",
        ]:
            with self.subTest(title=title):
                self.assertContains(response, title)

    def test_design_system_page_returns_http_200(self):
        response = self.client.get(reverse("workspace:design_system"))

        self.assertEqual(response.status_code, 200)

    def test_design_system_template_renders_key_component_labels(self):
        response = self.client.get(reverse("workspace:design_system"))

        for label in [
            "Primary Button",
            "Cards",
            "Badges and Status Badges",
            "Design System Table",
            "No items yet",
            "Form Field Wrapper",
        ]:
            with self.subTest(label=label):
                self.assertContains(response, label)

    def test_navigation_contains_design_system_link(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Design System")
        self.assertContains(response, reverse("workspace:design_system"))

    def test_navigation_contains_financials_link(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Financials")
        self.assertContains(response, reverse("workspace:financial_dashboard"))


class GLAccountClassificationSettingsTests(TestCase):
    def _gl_entry(self, organization, integration, account_code="4100", account_name="Materials", currency="EUR", suffix="a"):
        batch = AccountingGLBatch.objects.create(
            organization=organization,
            integration=integration,
            external_id=f"currency-batch-{account_code}-{suffix}",
            batch_date=timezone.datetime(2026, 6, 1).date(),
            currency_code=currency,
        )
        return AccountingGLEntry.objects.create(
            organization=organization,
            integration=integration,
            batch=batch,
            external_id=f"currency-entry-{account_code}-{suffix}",
            account_code=account_code,
            account_name=account_name,
            debit_amount="10.000000",
            credit_amount="0.000000",
        )

    def test_account_classification_list_shows_imported_account_statistics(self):
        organization = create_organization()
        project = create_project(organization)
        integration, _batch, _entry, _allocation = create_gl_account(
            organization,
            account_code="4002",
            account_name="Materials",
            project=project,
        )

        response = self.client.get(
            reverse("workspace:settings_account_classifications"),
            {"integration_id": integration.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "4002")
        self.assertContains(response, "Materials")
        self.assertContains(response, "100,00")
        self.assertContains(response, "25,00")
        self.assertContains(response, "75,00")
        self.assertContains(response, "unclassified")

    def test_account_classification_list_resolves_integration_mapping_search_filter_and_sort(self):
        organization = create_organization()
        project = create_project(organization)
        integration, _batch, _entry, _allocation = create_gl_account(
            organization,
            account_code="3000",
            account_name="Revenue",
            project=project,
        )
        AccountingAccountClassification.objects.create(
            organization=organization,
            integration=integration,
            account_code="3000",
            account_name="Revenue",
            category=AccountingAccountClassification.Category.REVENUE,
            reporting_sign="-1",
        )

        response = self.client.get(
            reverse("workspace:settings_account_classifications"),
            {"integration_id": integration.id, "q": "rev", "filter": "revenue", "sort": "category"},
        )

        self.assertContains(response, "3000")
        self.assertContains(response, "revenue")
        self.assertContains(response, "integration-specific")
        self.assertContains(response, "-1")

    def test_account_classification_list_is_organization_scoped(self):
        organization = create_organization("Visible Org")
        other = create_organization("Other Org")
        project = create_project(organization)
        integration, _batch, _entry, _allocation = create_gl_account(
            organization,
            account_code="4000",
            project=project,
        )
        other_integration = create_merit_integration(other)
        create_gl_account(other, integration=other_integration, account_code="9999")

        response = self.client.get(
            reverse("workspace:settings_account_classifications"),
            {"integration_id": integration.id},
        )

        self.assertContains(response, "4000")
        self.assertNotContains(response, "9999")

    def test_account_classification_detail_shows_entries_and_allocations(self):
        organization = create_organization()
        project = create_project(organization)
        integration, _batch, _entry, _allocation = create_gl_account(
            organization,
            account_code="5000",
            account_name="Subcontractors",
            project=project,
        )

        response = self.client.get(
            reverse("workspace:settings_account_classification_detail", args=["5000"]),
            {"integration_id": integration.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Subcontractors")
        self.assertContains(response, "Recent GL Entries")
        self.assertContains(response, "Project Allocation Samples")
        self.assertContains(response, project.code)

    def test_account_classification_detail_missing_account_is_safe(self):
        organization = create_organization()
        integration = create_merit_integration(organization)

        response = self.client.get(
            reverse("workspace:settings_account_classification_detail", args=["4040"]),
            {"integration_id": integration.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Imported GL account not found")

    def test_edit_page_and_post_create_classification_with_audit(self):
        organization = create_organization()
        project = create_project(organization)
        integration, _batch, _entry, _allocation = create_gl_account(
            organization,
            account_code="6000",
            account_name="Labor",
            project=project,
        )

        response = self.client.get(
            reverse("workspace:settings_account_classification_edit", args=["6000"]),
            {"integration_id": integration.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Save Classification")

        response = self.client.post(
            reverse("workspace:settings_account_classification_edit", args=["6000"]),
            {
                "integration_id": integration.id,
                "category": AccountingAccountClassification.Category.LABOR_COST,
                "reporting_sign": "1",
                "include_in_project_result": "on",
                "is_active": "on",
                "notes": "Labor mapping",
            },
        )

        self.assertEqual(response.status_code, 302)
        classification = AccountingAccountClassification.objects.get(account_code="6000")
        self.assertEqual(classification.category, AccountingAccountClassification.Category.LABOR_COST)
        self.assertEqual(classification.notes, "Labor mapping")
        self.assertTrue(AuditEvent.objects.filter(event_type="accounting_account_classification_saved").exists())

    def test_post_updates_classification_and_does_not_change_gl_source_records(self):
        organization = create_organization()
        project = create_project(organization)
        integration, _batch, entry, allocation = create_gl_account(
            organization,
            account_code="7000",
            account_name="Transport",
            project=project,
        )
        AccountingAccountClassification.objects.create(
            organization=organization,
            integration=integration,
            account_code="7000",
            category=AccountingAccountClassification.Category.UNCLASSIFIED,
        )

        self.client.post(
            reverse("workspace:settings_account_classification_edit", args=["7000"]),
            {
                "integration_id": integration.id,
                "category": AccountingAccountClassification.Category.TRANSPORT_COST,
                "reporting_sign": "1",
                "include_in_project_result": "on",
                "is_active": "on",
            },
        )

        self.assertEqual(AccountingAccountClassification.objects.count(), 1)
        entry.refresh_from_db()
        allocation.refresh_from_db()
        self.assertEqual(entry.account_code, "7000")
        self.assertEqual(allocation.amount, 75)
        self.assertEqual(Project.objects.count(), 1)

    def test_invalid_category_and_reporting_sign_are_rejected(self):
        organization = create_organization()
        integration, _batch, _entry, _allocation = create_gl_account(organization, account_code="8000")

        response = self.client.post(
            reverse("workspace:settings_account_classification_edit", args=["8000"]),
            {
                "integration_id": integration.id,
                "category": "not_real",
                "reporting_sign": "2",
                "include_in_project_result": "on",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(AccountingAccountClassification.objects.exists())

    def test_get_requests_do_not_create_classifications(self):
        organization = create_organization()
        integration, _batch, _entry, _allocation = create_gl_account(organization, account_code="8100")

        self.client.get(
            reverse("workspace:settings_account_classification_edit", args=["8100"]),
            {"integration_id": integration.id},
        )

        self.assertFalse(AccountingAccountClassification.objects.exists())

    def test_currency_diagnostic_single_eur_entry(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        self._gl_entry(organization, integration, account_code="4110", currency="EUR", suffix="one")

        response = self.client.get(
            reverse("workspace:settings_account_classifications"),
            {"integration_id": integration.id},
        )

        self.assertContains(response, "Currency: EUR")
        self.assertNotContains(response, "Mixed currencies: EUR")

    def test_currency_diagnostic_many_eur_entries_deduplicated(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        self._gl_entry(organization, integration, account_code="4111", currency="EUR", suffix="one")
        self._gl_entry(organization, integration, account_code="4111", currency=" eur ", suffix="two")
        self._gl_entry(organization, integration, account_code="4111", currency="eur", suffix="three")

        response = self.client.get(
            reverse("workspace:settings_account_classifications"),
            {"integration_id": integration.id},
        )

        self.assertContains(response, "Currency: EUR")
        self.assertNotContains(response, "Mixed currencies: EUR, EUR")

    def test_currency_diagnostic_mixed_sorted_and_deduplicated(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        self._gl_entry(organization, integration, account_code="4112", currency="usd", suffix="one")
        self._gl_entry(organization, integration, account_code="4112", currency=" EUR ", suffix="two")
        self._gl_entry(organization, integration, account_code="4112", currency="USD", suffix="three")

        response = self.client.get(
            reverse("workspace:settings_account_classifications"),
            {"integration_id": integration.id},
        )

        self.assertContains(response, "Mixed currencies: EUR, USD")
        self.assertNotContains(response, "Mixed currencies: USD, EUR")

    def test_currency_diagnostic_blank_values_ignored(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        self._gl_entry(organization, integration, account_code="4113", currency="", suffix="blank")
        self._gl_entry(organization, integration, account_code="4113", currency=" EUR ", suffix="eur")

        response = self.client.get(
            reverse("workspace:settings_account_classifications"),
            {"integration_id": integration.id},
        )

        self.assertContains(response, "Currency: EUR")
        self.assertNotContains(response, "Mixed currencies:")

    def test_currency_unknown_when_all_values_blank(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        self._gl_entry(organization, integration, account_code="4114", currency="", suffix="blank")

        response = self.client.get(
            reverse("workspace:settings_account_classifications"),
            {"integration_id": integration.id},
        )

        self.assertContains(response, "Currency unknown")

    def test_currency_diagnostic_get_does_not_write_database(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        self._gl_entry(organization, integration, account_code="4115", currency="EUR", suffix="one")
        counts = (
            AccountingGLBatch.objects.count(),
            AccountingGLEntry.objects.count(),
            AccountingGLAllocation.objects.count(),
            AccountingAccountClassification.objects.count(),
            AuditEvent.objects.count(),
        )

        response = self.client.get(
            reverse("workspace:settings_account_classifications"),
            {"integration_id": integration.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            counts,
            (
                AccountingGLBatch.objects.count(),
                AccountingGLEntry.objects.count(),
                AccountingGLAllocation.objects.count(),
                AccountingAccountClassification.objects.count(),
                AuditEvent.objects.count(),
            ),
        )


class ProjectFinancialOverviewTests(TestCase):
    def _classified_project(self):
        organization = create_organization()
        project = create_project(organization, code="26124", name="Kanarbiku")
        integration = create_merit_integration(organization)
        AccountingAccountClassification.objects.create(
            organization=organization,
            integration=integration,
            account_code="3000",
            account_name="Revenue",
            category=AccountingAccountClassification.Category.REVENUE,
            reporting_sign="-1",
        )
        AccountingAccountClassification.objects.create(
            organization=organization,
            integration=integration,
            account_code="4002",
            account_name="Materials",
            category=AccountingAccountClassification.Category.MATERIAL_COST,
            reporting_sign="1",
        )
        self._allocation(project, integration, "3000", "Revenue", "-1000.000000", "2026-06-01", "revenue")
        self._allocation(project, integration, "4002", "Materials", "250.000000", "2026-06-15", "materials")
        return organization, integration, project

    def _allocation(self, project, integration, account_code, account_name, amount, batch_date, suffix, currency="EUR", project_link=True):
        batch = AccountingGLBatch.objects.create(
            organization=project.organization,
            integration=integration,
            external_id=f"batch-{account_code}-{suffix}",
            batch_date=timezone.datetime.fromisoformat(batch_date).date(),
            currency_code=currency,
            document=f"Document {suffix}",
            number=f"N-{suffix}",
        )
        entry = AccountingGLEntry.objects.create(
            organization=project.organization,
            integration=integration,
            batch=batch,
            external_id=f"entry-{account_code}-{suffix}",
            account_code=account_code,
            account_name=account_name,
            memo=f"Memo {suffix}",
            debit_amount="0.000000",
            credit_amount="0.000000",
        )
        return AccountingGLAllocation.objects.create(
            organization=project.organization,
            integration=integration,
            entry=entry,
            external_id=f"alloc-{account_code}-{suffix}",
            dimension_code=project.code,
            dimension_name=project.name,
            amount=amount,
            project=project if project_link else None,
        )

    def test_financials_route_returns_200_header_default_period_and_no_api_call(self):
        _organization, _integration, project = self._classified_project()
        counts = (
            AccountingGLBatch.objects.count(),
            AccountingGLEntry.objects.count(),
            AccountingGLAllocation.objects.count(),
        )

        with patch.object(ProjectFinancialAggregationService, "aggregate", wraps=ProjectFinancialAggregationService().aggregate) as aggregate_mock:
            with patch.object(MeritAPIClient, "request") as request_mock:
                response = self.client.get(reverse("workspace:project_financials", args=[project.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Project Financials")
        self.assertContains(response, "Kanarbiku")
        self.assertContains(response, "2026-01-01")
        self.assertContains(response, "Revenue")
        aggregate_mock.assert_called_once()
        request_mock.assert_not_called()
        self.assertEqual(
            counts,
            (
                AccountingGLBatch.objects.count(),
                AccountingGLEntry.objects.count(),
                AccountingGLAllocation.objects.count(),
            ),
        )

    def test_custom_period_currency_and_overhead_are_passed_to_aggregation(self):
        _organization, _integration, project = self._classified_project()

        with patch.object(ProjectFinancialAggregationService, "aggregate", wraps=ProjectFinancialAggregationService().aggregate) as aggregate_mock:
            response = self.client.get(
                reverse("workspace:project_financials", args=[project.id]),
                {
                    "period": "custom",
                    "start": "2026-06-01",
                    "end": "2026-06-30",
                    "currency": "EUR",
                    "include_overhead": "0",
                },
            )

        self.assertEqual(response.status_code, 200)
        command = aggregate_mock.call_args.args[0]
        self.assertEqual(command.currency, "EUR")
        self.assertFalse(command.include_overhead)
        self.assertContains(response, "currency_filter_active:EUR")
        self.assertContains(response, "overhead_excluded")

    def test_invalid_and_reversed_period_are_safe(self):
        _organization, _integration, project = self._classified_project()

        invalid = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "bad", "end": "2026-06-30"},
        )
        reversed_response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-07-01", "end": "2026-06-30"},
        )

        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, "Invalid start date")
        self.assertEqual(reversed_response.status_code, 200)
        self.assertContains(reversed_response, "Period end cannot be before period start")

    def test_summary_monthly_data_quality_and_unclassified_sections(self):
        organization, integration, project = self._classified_project()
        self._allocation(project, integration, "9999", "Unknown", "80.000000", "2026-06-20", "unknown")
        other_project = create_project(organization, code="99999", name="Other")
        self._allocation(other_project, integration, "9999", "Unknown", "999.000000", "2026-06-20", "other")

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30"},
        )

        self.assertContains(response, "1 000,00")
        self.assertContains(response, "250,00")
        self.assertContains(response, "750,00")
        self.assertContains(response, "75,00%")
        self.assertContains(response, "unclassified_amount_present")
        self.assertContains(response, "9999")
        self.assertContains(response, "Unknown")
        self.assertContains(response, "80,00")
        self.assertNotContains(response, "999,00")
        self.assertContains(response, "2026-06")

    def test_monthly_vertical_chart_renders_for_one_month(self):
        _organization, _integration, project = self._classified_project()

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30"},
        )

        self.assertContains(response, "financial-chart")
        self.assertContains(response, "financial-chart__zero-line")
        self.assertContains(response, "2026-06 financial bars")
        self.assertContains(response, "Revenue")
        self.assertContains(response, "Management total cost")
        self.assertContains(response, "Management result")
        self.assertContains(response, "Revenue - 1 000,00 EUR")
        self.assertContains(response, "Management total cost - 250,00 EUR")
        self.assertContains(response, "Management result - 750,00 EUR")
        self.assertContains(response, "financial-chart__gridline")

    def test_accounting_toggle_keeps_accounting_only_chart_labels(self):
        _organization, _integration, project = self._classified_project()

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30", "view": "accounting"},
        )

        self.assertContains(response, "Current view: Accounting")
        self.assertContains(response, "Cost - 250,00 EUR")
        self.assertContains(response, "Result - 750,00 EUR")

    def test_monthly_vertical_chart_renders_multiple_months_chronologically(self):
        _organization, integration, project = self._classified_project()
        self._allocation(project, integration, "3000", "Revenue", "-200.000000", "2026-05-01", "revenue-may")
        self._allocation(project, integration, "4002", "Materials", "50.000000", "2026-07-01", "materials-july")

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-05-01", "end": "2026-07-31"},
        )
        content = response.content.decode()

        self.assertLess(content.index("2026-05 financial bars"), content.index("2026-06 financial bars"))
        self.assertLess(content.index("2026-06 financial bars"), content.index("2026-07 financial bars"))
        self.assertContains(response, "financial-chart__bar--revenue")
        self.assertContains(response, "financial-chart__bar--cost")
        self.assertContains(response, "financial-chart__bar--result-positive")

    def test_monthly_vertical_chart_uses_shared_scaling(self):
        _organization, _integration, project = self._classified_project()

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30"},
        )

        self.assertContains(response, "Scale max: 1 000,00 EUR")
        self.assertContains(response, 'style="height: 100.00%"', html=False)
        self.assertContains(response, 'style="height: 25.00%"', html=False)
        self.assertContains(response, 'style="height: 75.00%"', html=False)

    def test_monthly_vertical_chart_negative_result_extends_below_zero(self):
        organization = create_organization()
        project = create_project(organization, code="26126", name="Loss project")
        integration = create_merit_integration(organization)
        AccountingAccountClassification.objects.create(
            organization=organization,
            integration=integration,
            account_code="4002",
            account_name="Materials",
            category=AccountingAccountClassification.Category.MATERIAL_COST,
            reporting_sign="1",
        )
        self._allocation(project, integration, "4002", "Materials", "500.000000", "2026-06-15", "loss-materials")

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30"},
        )

        self.assertContains(response, "financial-chart__bar--result-negative")
        self.assertContains(response, "Management result - -500,00 EUR")
        self.assertContains(response, 'style="height: 83.33%"', html=False)

    def test_monthly_vertical_chart_zero_values_have_accessible_labels(self):
        _organization, integration, project = self._classified_project()
        self._allocation(project, integration, "4002", "Materials", "0.000000", "2026-07-01", "zero")

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-07-31"},
        )

        self.assertContains(response, "Revenue - 0,00 EUR")
        self.assertContains(response, "Management total cost - 0,00 EUR")
        self.assertContains(response, "Management result - 0,00 EUR")

    def test_monthly_vertical_chart_all_zero_or_empty_state(self):
        organization = create_organization()
        project = create_project(organization, code="26127", name="No monthly activity")

        response = self.client.get(reverse("workspace:project_financials", args=[project.id]))

        self.assertContains(response, "No monthly financial activity found for the selected period.")

    def test_monthly_vertical_chart_mixed_currency_warning_remains(self):
        _organization, integration, project = self._classified_project()
        self._allocation(project, integration, "4002", "Materials", "100.000000", "2026-07-01", "usd", currency="USD")

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-07-31"},
        )

        self.assertContains(response, "Data-quality warnings apply to this chart")
        self.assertContains(response, "mixed_currency")

    def test_monthly_table_still_renders_below_chart(self):
        _organization, _integration, project = self._classified_project()

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30"},
        )

        self.assertContains(response, "Monthly Financials")
        self.assertContains(response, "<th class=\"px-4 py-3 text-left\">Month</th>", html=False)
        self.assertContains(response, "1 000,00")
        self.assertContains(response, "750,00")

    def test_management_view_adds_approved_allocations_to_project_financials(self):
        organization, _integration, project = self._classified_project()
        pool = ManagementCostPool.objects.create(organization=organization, name="Office", default_strategy=AllocationStrategy.EQUAL)
        period = ManagementAllocationPeriod.objects.create(organization=organization, year=2026, month=6)
        version = ManagementAllocationVersion.objects.create(
            period=period,
            pool=pool,
            version_number=1,
            status=VersionStatus.APPROVED,
            approved_at=timezone.now(),
            metadata={"source_amount": "125.000000"},
        )
        ManagementAllocationEntry.objects.create(version=version, project=project, percentage="100.0000", amount="125.000000")

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30"},
        )

        self.assertContains(response, "Current view: Management")
        self.assertContains(response, "Allocated Cost")
        self.assertContains(response, "Management Total Cost")
        self.assertContains(response, "Management Result")
        self.assertContains(response, "Office")
        self.assertContains(response, "125,00")
        self.assertContains(response, "375,00")
        self.assertContains(response, "625,00")

    def test_accounting_view_keeps_direct_accounting_result_visible(self):
        organization, _integration, project = self._classified_project()
        pool = ManagementCostPool.objects.create(organization=organization, name="Office", default_strategy=AllocationStrategy.EQUAL)
        period = ManagementAllocationPeriod.objects.create(organization=organization, year=2026, month=6)
        version = ManagementAllocationVersion.objects.create(
            period=period,
            pool=pool,
            version_number=1,
            status=VersionStatus.APPROVED,
            approved_at=timezone.now(),
        )
        ManagementAllocationEntry.objects.create(version=version, project=project, percentage="100.0000", amount="125.000000")

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30", "view": "accounting"},
        )

        self.assertContains(response, "Current view: Accounting")
        self.assertContains(response, "Accounting Result")
        self.assertContains(response, "750,00")
        self.assertContains(response, "Cost - 250,00 EUR")
        self.assertContains(response, "Result - 750,00 EUR")

    def test_financial_money_formatting_uses_estonian_two_decimal_display(self):
        _organization, integration, project = self._classified_project()
        self._allocation(project, integration, "9998", "Negative adjustment", "-20.115000", "2026-06-20", "negative-adjustment")

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30"},
        )

        self.assertContains(response, "1 000,00")
        self.assertContains(response, "-20,12")
        self.assertContains(response, "0,00")
        self.assertNotContains(response, "1000.000000")

    def test_financial_chart_gridlines_include_zero_and_readable_ticks(self):
        _organization, integration, project = self._classified_project()
        self._allocation(project, integration, "3000", "Revenue", "-19132.880000", "2026-06-10", "large-revenue")

        response = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30"},
        )

        self.assertContains(response, "20 000")
        self.assertContains(response, "15 000")
        self.assertContains(response, "10 000")
        self.assertContains(response, "5 000")
        self.assertContains(response, ">0<", html=False)
        self.assertContains(response, "border-t-2 border-slate-500")

    def test_workspace_sidebar_renders_sticky_full_height_navigation(self):
        response = self.client.get(reverse("workspace:project_financials", args=[self._classified_project()[2].id]))

        self.assertContains(response, "lg:sticky lg:top-0")
        self.assertContains(response, "h-screen")
        self.assertContains(response, "overflow-y-auto")
        self.assertContains(response, "flex min-w-0 flex-1 flex-col")

    def test_monthly_vertical_chart_get_does_not_call_api_or_write_database(self):
        _organization, _integration, project = self._classified_project()
        counts = (
            AccountingGLBatch.objects.count(),
            AccountingGLEntry.objects.count(),
            AccountingGLAllocation.objects.count(),
            AuditEvent.objects.count(),
        )

        with patch.object(MeritAPIClient, "request") as request_mock:
            response = self.client.get(
                reverse("workspace:project_financials", args=[project.id]),
                {"period": "custom", "start": "2026-06-01", "end": "2026-06-30"},
            )

        self.assertEqual(response.status_code, 200)
        request_mock.assert_not_called()
        self.assertEqual(
            counts,
            (
                AccountingGLBatch.objects.count(),
                AccountingGLEntry.objects.count(),
                AccountingGLAllocation.objects.count(),
                AuditEvent.objects.count(),
            ),
        )

    def test_no_data_state_and_mixed_currency_warning(self):
        _organization, integration, project = self._classified_project()
        empty_project = create_project(project.organization, code="26125", name="Empty")

        empty_response = self.client.get(reverse("workspace:project_financials", args=[empty_project.id]))
        self.assertContains(empty_response, "no_data")
        self.assertContains(empty_response, "No linked financial transactions found")

        self._allocation(project, integration, "4002", "Materials", "100.000000", "2026-07-01", "usd", currency="USD")
        mixed = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-07-31"},
        )
        self.assertContains(mixed, "mixed_currency")

    def test_sync_state_success_and_failed_safe_error_are_shown(self):
        organization, integration, project = self._classified_project()
        state = AccountingSyncState.objects.create(
            organization=organization,
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
            sync_status=AccountingSyncState.SyncStatus.IDLE,
            last_successful_sync_at=timezone.now(),
        )
        AccountingSyncRun.objects.create(
            organization=organization,
            integration=integration,
            sync_state=state,
            source_type=AccountingSyncState.SourceType.GL,
            status=AccountingSyncRun.Status.COMPLETED,
        )

        success = self.client.get(reverse("workspace:project_financials", args=[project.id]))
        self.assertContains(success, "successful")
        self.assertContains(success, "Last successful sync")

        secret = integration.encrypted_secret_placeholder
        state.sync_status = AccountingSyncState.SyncStatus.FAILED
        state.last_error = "Safe sync error"
        state.save()
        failed = self.client.get(reverse("workspace:project_financials", args=[project.id]))
        self.assertContains(failed, "failed")
        self.assertContains(failed, "Safe sync error")
        self.assertNotContains(failed, secret)

    def test_project_detail_contains_financials_link(self):
        _organization, _integration, project = self._classified_project()

        response = self.client.get(reverse("workspace:project_detail", args=[project.id]))

        self.assertContains(response, "Financials")
        self.assertContains(response, reverse("workspace:project_financials", args=[project.id]))

    def test_allocation_drilldown_filters_and_normalized_amount(self):
        _organization, _integration, project = self._classified_project()

        response = self.client.get(
            reverse("workspace:project_financial_allocations", args=[project.id]),
            {
                "start": "2026-06-01",
                "end": "2026-06-30",
                "category": AccountingAccountClassification.Category.REVENUE,
                "month": "2026-06",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Allocation Drill-down")
        self.assertContains(response, "3000")
        self.assertContains(response, "-1 000,00")
        self.assertContains(response, "1 000,00")
        self.assertNotContains(response, "4002")


class OrganizationFinancialDashboardTests(TestCase):
    def _setup(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        AccountingAccountClassification.objects.create(
            organization=organization,
            integration=integration,
            account_code="3000",
            category=AccountingAccountClassification.Category.REVENUE,
            reporting_sign="-1",
        )
        AccountingAccountClassification.objects.create(
            organization=organization,
            integration=integration,
            account_code="4000",
            category=AccountingAccountClassification.Category.MATERIAL_COST,
            reporting_sign="1",
        )
        return organization, integration

    def _allocation(self, project, integration, account_code, amount, batch_date="2026-06-15", suffix="a", currency="EUR"):
        batch = AccountingGLBatch.objects.create(
            organization=project.organization,
            integration=integration,
            external_id=f"orgfin-batch-{project.code}-{account_code}-{suffix}",
            batch_date=timezone.datetime.fromisoformat(batch_date).date(),
            currency_code=currency,
        )
        entry = AccountingGLEntry.objects.create(
            organization=project.organization,
            integration=integration,
            batch=batch,
            external_id=f"orgfin-entry-{project.code}-{account_code}-{suffix}",
            account_code=account_code,
            account_name=f"Account {account_code}",
            debit_amount="0.000000",
            credit_amount="0.000000",
        )
        return AccountingGLAllocation.objects.create(
            organization=project.organization,
            integration=integration,
            entry=entry,
            external_id=f"orgfin-alloc-{project.code}-{account_code}-{suffix}",
            dimension_code=project.code,
            dimension_name=project.name,
            amount=amount,
            project=project,
        )

    def _project_with_activity(self, code="26170", name="Revenue project", status=Project.Status.ACTIVE, revenue="1000.000000", cost="250.000000", currency="EUR"):
        organization, integration = self._setup()
        project = create_project(organization, code=code, name=name)
        project.status = status
        project.save()
        if revenue is not None:
            self._allocation(project, integration, "3000", f"-{revenue}", suffix="rev", currency=currency)
        if cost is not None:
            self._allocation(project, integration, "4000", cost, suffix="cost", currency=currency)
        return organization, integration, project

    def test_financial_dashboard_route_default_month_sidebar_and_no_api_call(self):
        _organization, _integration, project = self._project_with_activity()
        counts = (AccountingGLBatch.objects.count(), AccountingGLEntry.objects.count(), AccountingGLAllocation.objects.count(), AuditEvent.objects.count())

        with patch.object(MeritAPIClient, "request") as request_mock:
            response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Financial Dashboard")
        self.assertContains(response, "Organization-wide project revenue")
        self.assertContains(response, project.code)
        self.assertContains(response, "Financials")
        request_mock.assert_not_called()
        self.assertEqual(counts, (AccountingGLBatch.objects.count(), AccountingGLEntry.objects.count(), AccountingGLAllocation.objects.count(), AuditEvent.objects.count()))

    def test_invalid_month_is_safe_and_month_links_render(self):
        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "bad"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid month. Use YYYY-MM.")
        self.assertContains(response, "Previous month")
        self.assertContains(response, "Next month")
        self.assertContains(response, "Current month")

    def test_candidate_selection_includes_activity_and_excludes_inactive_no_data_by_default(self):
        organization, integration = self._setup()
        active = create_project(organization, code="26171", name="Active activity")
        empty = create_project(organization, code="26172", name="No data")
        self._allocation(active, integration, "3000", "-500.000000", suffix="rev")

        with patch.object(ProjectFinancialAggregationService, "aggregate", wraps=ProjectFinancialAggregationService().aggregate) as aggregate_mock:
            response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06"})

        self.assertContains(response, active.code)
        self.assertNotContains(response, empty.name)
        self.assertEqual(aggregate_mock.call_count, 1)

    def test_organization_isolation_and_month_boundaries(self):
        organization, integration = self._setup()
        visible = create_project(organization, code="261710", name="Visible June")
        outside_month = create_project(organization, code="261711", name="Outside month")
        other_org = create_organization("Other financial org")
        other_integration = create_merit_integration(other_org)
        other_project = create_project(other_org, code="99901", name="Other org project")
        self._allocation(visible, integration, "3000", "-500.000000", batch_date="2026-06-30", suffix="visible")
        self._allocation(outside_month, integration, "3000", "-600.000000", batch_date="2026-07-01", suffix="outside")
        self._allocation(other_project, other_integration, "3000", "-700.000000", batch_date="2026-06-15", suffix="other")

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06"})

        self.assertContains(response, visible.name)
        self.assertNotContains(response, outside_month.name)
        self.assertNotContains(response, other_project.name)

    def test_show_no_data_includes_empty_projects(self):
        organization, _integration = self._setup()
        empty = create_project(organization, code="26173", name="Empty shown")

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "show_no_data": "1"})

        self.assertContains(response, empty.name)
        self.assertContains(response, "no_data")

    def test_completed_and_archived_projects_with_activity_are_visible(self):
        organization, integration = self._setup()
        completed = create_project(organization, code="26174", name="Completed activity")
        archived = create_project(organization, code="26175", name="Archived activity")
        completed.status = Project.Status.COMPLETED
        archived.status = Project.Status.ARCHIVED
        completed.save()
        archived.save()
        self._allocation(completed, integration, "3000", "-300.000000", suffix="completed")
        self._allocation(archived, integration, "4000", "120.000000", suffix="archived")

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06"})

        self.assertContains(response, "Completed activity")
        self.assertContains(response, "Archived activity")
        completed_only = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "status": "completed"})
        self.assertContains(completed_only, "Completed activity")
        self.assertNotContains(completed_only, "Archived activity")

    def test_search_result_and_data_quality_filters(self):
        organization, integration = self._setup()
        profitable = create_project(organization, code="26176", name="Searchable profit")
        cost_only = create_project(organization, code="26177", name="Cost only")
        unclassified = create_project(organization, code="26178", name="Unclassified project")
        self._allocation(profitable, integration, "3000", "-900.000000", suffix="profit-rev")
        self._allocation(profitable, integration, "4000", "100.000000", suffix="profit-cost")
        self._allocation(cost_only, integration, "4000", "300.000000", suffix="cost-only")
        self._allocation(unclassified, integration, "9999", "40.000000", suffix="unclassified")

        search = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "search": "Searchable"})
        self.assertContains(search, profitable.name)
        self.assertNotContains(search, cost_only.name)

        costs = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "result_status": "costs_without_revenue"})
        self.assertContains(costs, cost_only.name)
        self.assertNotContains(costs, profitable.name)

        quality = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "data_quality": "unclassified"})
        self.assertContains(quality, unclassified.name)
        self.assertNotContains(quality, profitable.name)

    def test_default_sort_revenue_desc_and_sort_links(self):
        organization, integration = self._setup()
        high = create_project(organization, code="26179", name="High revenue")
        low = create_project(organization, code="26180", name="Low revenue")
        self._allocation(low, integration, "3000", "-100.000000", suffix="low")
        self._allocation(high, integration, "3000", "-900.000000", suffix="high")

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06"})
        content = response.content.decode()

        self.assertLess(content.index("High revenue"), content.index("Low revenue"))
        self.assertContains(response, "sort=total_cost")
        ascending = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "sort": "revenue", "direction": "asc"})
        ascending_content = ascending.content.decode().split("Project Financial Ranking", 1)[1]
        self.assertLess(ascending_content.index("Low revenue"), ascending_content.index("High revenue"))

    def test_financial_dashboard_chart_renders_revenue_cost_result_and_margin(self):
        _organization, _integration, project = self._project_with_activity(
            code="26190",
            name="Chart metrics",
            revenue="1000.000000",
            cost="250.000000",
        )

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "currency": "EUR"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Project Revenue, Cost and Result Comparison")
        self.assertContains(response, f"{project.code} {project.name} Revenue: 1 000,00 EUR")
        self.assertContains(response, f"{project.code} {project.name} Cost: 250,00 EUR")
        self.assertContains(response, f"{project.code} {project.name} Result: 750,00 EUR")
        self.assertContains(response, "75,00%")
        self.assertContains(response, "Project Financial Ranking")

    def test_financial_dashboard_chart_revenue_zero_gives_no_margin(self):
        _organization, _integration, project = self._project_with_activity(
            code="26191",
            name="Cost without revenue chart",
            revenue=None,
            cost="250.000000",
        )

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "currency": "EUR"})

        chart_section = response.content.decode().split("Project Revenue, Cost and Result Comparison", 1)[1].split("Project Financial Ranking", 1)[0]
        self.assertIn(project.name, chart_section)
        self.assertIn("Margin", chart_section)
        self.assertIn("-", chart_section)

    def test_financial_dashboard_chart_negative_result_uses_negative_style(self):
        _organization, _integration, project = self._project_with_activity(
            code="26192",
            name="Negative result chart",
            revenue="100.000000",
            cost="250.000000",
        )

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "currency": "EUR"})

        self.assertContains(response, f"{project.code} {project.name} Result: -150,00 EUR")
        self.assertContains(response, "bg-red-500")
        self.assertContains(response, "left: 0.00%; width: 37.50%;")
        self.assertContains(response, "left: 37.50%;")

    def test_financial_dashboard_chart_negative_axis_uses_actual_min_result(self):
        organization, integration = self._setup()
        positive = create_project(organization, code="26195", name="Positive axis chart")
        negative = create_project(organization, code="26196", name="Small negative axis chart")
        self._allocation(positive, integration, "3000", "-1000.000000", suffix="positive-rev")
        self._allocation(negative, integration, "3000", "-100.000000", suffix="negative-rev")
        self._allocation(negative, integration, "4000", "250.000000", suffix="negative-cost")

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "currency": "EUR"})
        chart_rows = response.context["chart_rows"]
        negative_chart = next(chart for chart in chart_rows if chart["row"].project_code == negative.code)
        negative_result = next(metric for metric in negative_chart["metrics"] if metric["label"] == "Result")

        self.assertEqual(negative_chart["axis"]["min_negative"], Decimal("-150.000000"))
        self.assertEqual(negative_chart["axis"]["max_positive"], Decimal("1000.000000"))
        self.assertEqual(negative_chart["axis"]["zero_line_percent"], "13.04")
        self.assertEqual(negative_result["left_percent"], "0.00")
        self.assertEqual(negative_result["width_percent"], "13.04")
        self.assertContains(response, "-150,00 EUR")

    def test_financial_dashboard_chart_uses_shared_monetary_scale(self):
        organization, integration = self._setup()
        largest = create_project(organization, code="26193", name="Largest chart")
        smaller = create_project(organization, code="26194", name="Smaller chart")
        self._allocation(largest, integration, "3000", "-1000.000000", suffix="largest-rev")
        self._allocation(smaller, integration, "3000", "-500.000000", suffix="smaller-rev")
        self._allocation(smaller, integration, "4000", "250.000000", suffix="smaller-cost")

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "currency": "EUR"})
        chart_rows = response.context["chart_rows"]

        self.assertEqual(chart_rows[0]["row"].project_code, largest.code)
        self.assertEqual(chart_rows[0]["metrics"][0]["width_percent"], "100.00")
        self.assertEqual(chart_rows[1]["metrics"][0]["width_percent"], "50.00")
        self.assertEqual(chart_rows[1]["metrics"][1]["width_percent"], "25.00")

    def test_financial_dashboard_chart_top_10_and_data_quality_marker(self):
        organization, integration = self._setup()
        for index in range(12):
            project = create_project(organization, code=f"262{index:02d}", name=f"Chart top {index:02d}")
            self._allocation(project, integration, "3000", f"-{1000 - index}.000000", suffix=f"rev-{index}")
        unclassified = create_project(organization, code="26299", name="Chart unclassified")
        self._allocation(unclassified, integration, "3000", "-100.000000", suffix="unclassified-rev")
        self._allocation(unclassified, integration, "9999", "5000.000000", suffix="unclassified")

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "sort": "revenue", "direction": "desc"})
        chart_section = response.content.decode().split("Project Revenue, Cost and Result Comparison", 1)[1].split("Project Financial Ranking", 1)[0]

        self.assertEqual(len(response.context["chart_rows"]), 10)
        self.assertIn("Chart top 00", chart_section)
        self.assertNotIn("Chart top 10", chart_section)

        unclassified_response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "search": "Chart unclassified"})
        self.assertContains(unclassified_response, "Chart unclassified")
        self.assertContains(unclassified_response, "unclassified")

    def test_summary_cards_use_totals_and_overall_margin(self):
        organization, integration = self._setup()
        first = create_project(organization, code="26181", name="First")
        second = create_project(organization, code="26182", name="Second")
        self._allocation(first, integration, "3000", "-1000.000000", suffix="first-rev")
        self._allocation(first, integration, "4000", "200.000000", suffix="first-cost")
        self._allocation(second, integration, "3000", "-500.000000", suffix="second-rev")
        self._allocation(second, integration, "4000", "100.000000", suffix="second-cost")

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "currency": "EUR"})

        self.assertContains(response, "Projects with activity")
        self.assertContains(response, "1 500,00 EUR")
        self.assertContains(response, "300,00 EUR")
        self.assertContains(response, "1 200,00 EUR")
        self.assertContains(response, "80,00%")
        self.assertContains(response, "Profitable projects")

    def test_currency_filter_and_mixed_currency_warning(self):
        organization, integration = self._setup()
        eur = create_project(organization, code="26183", name="EUR project")
        usd = create_project(organization, code="26184", name="USD project")
        self._allocation(eur, integration, "3000", "-100.000000", suffix="eur", currency="EUR")
        self._allocation(usd, integration, "3000", "-200.000000", suffix="usd", currency="USD")

        mixed = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06"})
        self.assertContains(mixed, "Multiple currencies found")
        self.assertContains(mixed, "Select currency")

        filtered = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "currency": "EUR"})
        self.assertContains(filtered, "EUR project")
        self.assertNotContains(filtered, "USD project")
        self.assertContains(filtered, "100,00 EUR")

    def test_table_links_preserve_month_currency_and_overhead(self):
        _organization, _integration, project = self._project_with_activity()

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "currency": "EUR", "include_overhead": "0"})

        self.assertContains(response, reverse("workspace:project_financials", args=[project.id]))
        self.assertContains(response, "start=2026-06-01")
        self.assertContains(response, "end=2026-06-30")
        self.assertContains(response, "currency=EUR")
        self.assertContains(response, "include_overhead=0")
        self.assertContains(response, "Allocation Drill-down")

    def test_pagination_preserves_filters(self):
        organization, integration = self._setup()
        for index in range(30):
            project = create_project(organization, code=f"27{index:03d}", name=f"Paged {index:02d}")
            self._allocation(project, integration, "3000", f"-{100 + index}.000000", suffix=str(index))

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06", "currency": "EUR", "sort": "project_code", "direction": "asc"})

        self.assertContains(response, "Page 1 of 2")
        self.assertContains(response, "page=2")
        self.assertContains(response, "sort=project_code")
        self.assertContains(response, "currency=EUR")


class MonthlyGLSyncUITests(TestCase):
    def _result(self, integration, period_start=timezone.datetime(2026, 6, 1).date(), period_end=timezone.datetime(2026, 6, 30).date()):
        return SyncGeneralLedgerResult(
            integration=integration,
            sync_state=None,
            sync_run=None,
            period_start=period_start,
            period_end=period_end,
            requested_chunk_count=1,
            completed_chunk_count=1,
            discovered_batch_count=142,
            created_count=28,
            updated_count=4,
            unchanged_count=1206,
            failed_count=0,
            batches=[],
            partial=False,
            synced=True,
            metadata={},
        )

    def test_calendar_month_bounds(self):
        self.assertEqual(calendar_month_bounds("2026-01"), (timezone.datetime(2026, 1, 1).date(), timezone.datetime(2026, 1, 31).date()))
        self.assertEqual(calendar_month_bounds("2026-04"), (timezone.datetime(2026, 4, 1).date(), timezone.datetime(2026, 4, 30).date()))
        self.assertEqual(calendar_month_bounds("2026-02"), (timezone.datetime(2026, 2, 1).date(), timezone.datetime(2026, 2, 28).date()))
        self.assertEqual(calendar_month_bounds("2028-02"), (timezone.datetime(2028, 2, 1).date(), timezone.datetime(2028, 2, 29).date()))
        self.assertEqual(calendar_month_bounds("2026-12"), (timezone.datetime(2026, 12, 1).date(), timezone.datetime(2026, 12, 31).date()))
        self.assertEqual(calendar_month_bounds("2035-07"), (timezone.datetime(2035, 7, 1).date(), timezone.datetime(2035, 7, 31).date()))
        with self.assertRaises(ValueError):
            calendar_month_bounds("2026/06")
        with self.assertRaises(ValueError):
            calendar_month_bounds("bad")

    def test_sync_form_rendered_with_month_and_active_integration(self):
        organization = create_organization()
        integration = create_merit_integration(organization)

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06"})

        self.assertContains(response, "Monthly Merit GL Sync")
        self.assertContains(response, reverse("workspace:financial_dashboard_sync_month"))
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, 'value="2026-06"', html=False)
        self.assertContains(response, integration.display_name)

    def test_multiple_integrations_selector_and_no_integration_message(self):
        organization = create_organization()
        first = create_merit_integration(organization)
        second = create_merit_integration(organization)
        second.display_name = "Second Merit"
        second.api_id = "api-id-2"
        second.save()

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06"})
        self.assertContains(response, first.display_name)
        self.assertContains(response, "Second Merit")
        self.assertContains(response, "Multiple active Merit integrations")

        AccountingIntegration.objects.all().delete()
        no_integration = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06"})
        self.assertContains(no_integration, "No active Merit integration is configured")
        self.assertContains(no_integration, reverse("workspace:settings_accounting_integrations"))
        self.assertContains(no_integration, "disabled", html=False)

    @patch("apps.workspace.views.GeneralLedgerSyncService.sync")
    def test_get_does_not_call_service_and_post_calls_gl_sync_service(self, sync_mock):
        organization = create_organization()
        integration = create_merit_integration(organization)
        sync_mock.return_value = self._result(integration)

        get_response = self.client.get(reverse("workspace:financial_dashboard_sync_month"))
        self.assertEqual(get_response.status_code, 405)
        sync_mock.assert_not_called()

        response = self.client.post(
            reverse("workspace:financial_dashboard_sync_month"),
            {
                "integration": integration.id,
                "month": "2026-06",
                "next": "/workspace/financials/?month=2026-06&currency=EUR&include_overhead=0",
            },
            follow=True,
        )

        self.assertRedirects(response, "/workspace/financials/?month=2026-06&currency=EUR&include_overhead=0")
        sync_mock.assert_called_once()
        command = sync_mock.call_args.args[0]
        self.assertEqual(command.integration, integration)
        self.assertEqual(command.period_start, timezone.datetime(2026, 6, 1).date())
        self.assertEqual(command.period_end, timezone.datetime(2026, 6, 30).date())
        self.assertEqual(command.mode, AccountingSyncRun.Mode.PERIOD_RESYNC)
        self.assertEqual(command.date_type, "document_date")
        self.assertTrue(command.with_lines)
        self.assertTrue(command.with_cost_allocations)
        self.assertFalse(command.initial_import)
        self.assertEqual(command.metadata, {"source": "workspace_financial_dashboard", "selected_month": "2026-06"})
        self.assertContains(response, "Merit GL sync completed for 2026-06")
        self.assertContains(response, "discovered 142 provider batches")
        self.assertContains(response, "created 28")
        self.assertContains(response, "updated 4")
        self.assertContains(response, "unchanged 1206")

    @patch("apps.workspace.views.MeritAPIClient.get_gl_batches_full")
    @patch("apps.workspace.views.GeneralLedgerSyncService.sync")
    def test_no_direct_merit_api_call_invalid_inputs_and_organization_isolation(self, sync_mock, api_mock):
        organization = create_organization()
        integration = create_merit_integration(organization)
        other_org = create_organization("Other sync org")
        other_integration = create_merit_integration(other_org)
        inactive = create_merit_integration(organization)
        inactive.is_active = False
        inactive.save()
        non_merit = AccountingIntegration.objects.create(
            organization=organization,
            provider=AccountingIntegration.Provider.XERO,
            display_name="Xero",
            api_base_url="https://xero.example.test",
            api_id="xero-id",
            encrypted_secret_placeholder="xero-secret",
        )

        cases = [
            {"integration": integration.id, "month": "bad"},
            {"integration": other_integration.id, "month": "2026-06"},
            {"integration": inactive.id, "month": "2026-06"},
            {"integration": non_merit.id, "month": "2026-06"},
        ]
        for payload in cases:
            response = self.client.post(reverse("workspace:financial_dashboard_sync_month"), payload, follow=True)
            self.assertContains(response, "Merit GL sync could not start")

        sync_mock.assert_not_called()
        api_mock.assert_not_called()

    @patch("apps.workspace.views.GeneralLedgerSyncService.sync")
    def test_running_sync_blocks_post_and_disables_button(self, sync_mock):
        organization = create_organization()
        integration = create_merit_integration(organization)
        other = create_merit_integration(organization)
        AccountingSyncState.objects.create(
            organization=organization,
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
            sync_status=AccountingSyncState.SyncStatus.RUNNING,
        )
        AccountingSyncState.objects.create(
            organization=organization,
            integration=other,
            source_type=AccountingSyncState.SourceType.GL,
            sync_status=AccountingSyncState.SyncStatus.IDLE,
        )

        page = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06"})
        self.assertContains(page, "A Merit GL sync is already running")
        self.assertContains(page, "disabled", html=False)

        response = self.client.post(
            reverse("workspace:financial_dashboard_sync_month"),
            {"integration": integration.id, "month": "2026-06"},
            follow=True,
        )

        sync_mock.assert_not_called()
        self.assertContains(response, "already running")

    @patch("apps.workspace.views.GeneralLedgerSyncService.sync")
    def test_error_messages_are_safe_for_partial_and_total_failure(self, sync_mock):
        organization = create_organization()
        integration = create_merit_integration(organization)
        AccountingSyncRun.objects.create(
            organization=organization,
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
            status=AccountingSyncRun.Status.PARTIAL,
            requested_period_start=timezone.datetime(2026, 6, 1).date(),
            requested_period_end=timezone.datetime(2026, 6, 30).date(),
        )
        sync_mock.side_effect = RuntimeError("api-secret signature=secret raw payload")

        partial = self.client.post(
            reverse("workspace:financial_dashboard_sync_month"),
            {"integration": integration.id, "month": "2026-06"},
            follow=True,
        )
        self.assertContains(partial, "failed after partial progress")
        self.assertNotContains(partial, "api-secret")
        self.assertNotContains(partial, "signature=secret")
        self.assertNotContains(partial, "raw payload")

        sync_mock.reset_mock()
        sync_mock.side_effect = RuntimeError("api-secret")
        total = self.client.post(
            reverse("workspace:financial_dashboard_sync_month"),
            {"integration": integration.id, "month": "2026-07"},
            follow=True,
        )
        self.assertContains(total, "failed. No new completion state was recorded")
        self.assertNotContains(total, "api-secret")

    def test_selected_month_sync_run_panel_scopes_latest_run(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        other_integration = create_merit_integration(organization)
        june_start = timezone.datetime(2026, 6, 1).date()
        june_end = timezone.datetime(2026, 6, 30).date()
        may_start = timezone.datetime(2026, 5, 1).date()
        may_end = timezone.datetime(2026, 5, 31).date()
        AccountingSyncRun.objects.create(
            organization=organization,
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
            status=AccountingSyncRun.Status.COMPLETED,
            mode=AccountingSyncRun.Mode.PERIOD_RESYNC,
            requested_period_start=may_start,
            requested_period_end=may_end,
            discovered_count=999,
        )
        AccountingSyncRun.objects.create(
            organization=organization,
            integration=other_integration,
            source_type=AccountingSyncState.SourceType.GL,
            status=AccountingSyncRun.Status.FAILED,
            requested_period_start=june_start,
            requested_period_end=june_end,
            safe_error="other integration error",
        )
        AccountingSyncRun.objects.create(
            organization=organization,
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
            status=AccountingSyncRun.Status.FAILED,
            requested_period_start=june_start,
            requested_period_end=june_end,
            safe_error="safe selected month error",
            discovered_count=7,
            created_count=2,
            updated_count=3,
            unchanged_count=4,
            skipped_count=5,
            failed_count=6,
        )

        response = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-06"})

        self.assertContains(response, "Selected Month Sync Run")
        self.assertContains(response, "failed")
        self.assertContains(response, "safe selected month error")
        self.assertContains(response, "7")
        self.assertContains(response, "2 / 3 / 4")
        self.assertContains(response, "5 / 6")
        self.assertNotContains(response, "999")
        self.assertNotContains(response, "other integration error")

        empty = self.client.get(reverse("workspace:financial_dashboard"), {"month": "2026-08"})
        self.assertContains(empty, "No sync run for selected month yet.")


class DashboardMVPTests(TestCase):
    def test_dashboard_returns_200_with_empty_db(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No emails yet")
        self.assertContains(response, "No project suggestions yet")

    def test_dashboard_shows_email_count(self):
        organization = create_organization()
        create_email_message(organization, subject="Email count subject")

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Total Imported Emails")
        self.assertContains(response, "Email count subject")
        self.assertContains(response, ">1<", html=False)

    def test_dashboard_shows_project_count(self):
        organization = create_organization()
        create_project(organization, code="26080", name="Active dashboard project")

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Active Projects")
        self.assertContains(response, ">1<", html=False)

    def test_dashboard_shows_document_count(self):
        organization = create_organization()
        Document.objects.create(
            organization=organization,
            title="Dashboard document",
            original_filename="dashboard.pdf",
        )

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Documents")
        self.assertContains(response, "Dashboard document")

    def test_dashboard_shows_question_count(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Question email")
        EmailQuestion.objects.create(
            organization=organization,
            email_message=message,
            question_text="Can you confirm?",
        )

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Detected Questions")
        self.assertContains(response, "Can you confirm?")

    def test_dashboard_shows_project_suggestions(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Suggestion email")
        project = create_project(organization, code="26081", name="Suggested project")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            status=EmailProjectLink.Status.SUGGESTED,
            confidence=90,
        )

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Emails Needing Project Confirmation")
        self.assertContains(response, "Suggestion email")
        self.assertContains(response, "26081")
        self.assertContains(response, "90%")

    def test_dashboard_shows_recent_emails(self):
        organization = create_organization()
        create_email_message(organization, subject="Recent email")

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Latest 5 Emails")
        self.assertContains(response, "Recent email")

    def test_dashboard_uses_empty_states_when_no_data(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "No emails yet")
        self.assertContains(response, "No documents yet")

    def test_dashboard_shows_answer_drafts_workflow_and_audit_counts(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Draft email")
        EmailAnswerDraft.objects.create(
            organization=organization,
            email_message=message,
            status=EmailAnswerDraft.Status.NEEDS_REVIEW,
            draft_text="Draft needs review",
        )
        workflow = WorkflowDefinition.objects.create(code="dashboard", name="Dashboard workflow")
        state = WorkflowState.objects.create(workflow=workflow, code="new", name="New", is_initial=True)
        WorkflowInstance.objects.create(
            organization=organization,
            workflow=workflow,
            current_state=state,
            entity_type="email",
            entity_uuid=message.organization.uuid,
        )
        AuditEvent.objects.create(
            organization=organization,
            event_type="dashboard.test",
            object_type="EmailMessage",
            object_id=str(message.id),
            message="Dashboard audit",
        )

        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Answer Drafts Needing Review")
        self.assertContains(response, "Workflow Instances")
        self.assertContains(response, "Audit Events Today")
        self.assertContains(response, "dashboard.test")


class SettingsWorkspaceTests(TestCase):
    def test_settings_page_returns_200(self):
        response = self.client.get(reverse("workspace:settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Platform Settings Workspace")

    def test_summary_counts_render(self):
        organization = create_organization()
        create_email_account(organization)
        create_merit_integration(organization)
        create_project(organization, code="26150", name="Settings project")
        AccountingDimension.objects.create(organization=organization, code="26151", name="Settings dimension")
        AuditEvent.objects.create(event_type="settings.test", object_type="settings", object_id="1")

        response = self.client.get(reverse("workspace:settings"))

        for label in [
            "Organizations",
            "Email Accounts",
            "Accounting Integrations",
            "Projects",
            "Accounting Dimensions",
            "Recent Audit Events",
        ]:
            with self.subTest(label=label):
                self.assertContains(response, label)

    def test_email_accounts_shown(self):
        organization = create_organization()
        create_email_account(organization)

        response = self.client.get(reverse("workspace:settings"))

        self.assertContains(response, "Email Account Settings")
        self.assertContains(response, "workspace@example.com")
        self.assertContains(response, "Sync now")
        self.assertContains(response, "Test Connection")

    def test_accounting_integrations_shown(self):
        organization = create_organization()
        create_merit_integration(organization)

        response = self.client.get(reverse("workspace:settings"))

        self.assertContains(response, "Accounting Integration Settings")
        self.assertContains(response, "Merit Aktiva")
        self.assertContains(response, "Sync Merit Dimensions")

    def test_merit_section_renders(self):
        organization = create_organization()
        create_merit_integration(organization, metadata={"project_dimension_id": "dim-project"})
        AccountingDimension.objects.create(
            organization=organization,
            code="26152",
            name="Merit cached dimension",
            last_synced_at=timezone.now(),
        )

        response = self.client.get(reverse("workspace:settings"))

        self.assertContains(response, "Merit Settings")
        self.assertContains(response, "Project Dimension configured")
        self.assertContains(response, "Dimension cache count")
        self.assertContains(response, "yes")

    def test_project_numbering_renders(self):
        organization = create_organization()
        create_project(organization, code="26153", name="Highest project")
        AccountingDimension.objects.create(organization=organization, code="26154", name="Cached dimension")

        response = self.client.get(reverse("workspace:settings"))

        self.assertContains(response, "Project Numbering")
        self.assertContains(response, "Highest project code")
        self.assertContains(response, "26153")
        self.assertContains(response, "Next suggested code")
        self.assertContains(response, "26155")

    def test_system_health_cards_render(self):
        response = self.client.get(reverse("workspace:settings"))

        for label in ["System Health", "Email", "Accounting", "Knowledge", "Database", "Storage"]:
            with self.subTest(label=label):
                self.assertContains(response, label)

    def test_navigation_cards_render(self):
        response = self.client.get(reverse("workspace:settings"))

        for label in [
            "General",
            "Organizations",
            "Email Accounts",
            "Accounting",
            "Merit",
            "Project Numbering",
            "Knowledge",
            "Documents",
            "Dropbox (Coming Soon)",
            "Users &amp; Roles",
            "Security",
            "Audit",
            "System Health",
        ]:
            with self.subTest(label=label):
                self.assertContains(response, label)


class EmailAccountManagementUITests(TestCase):
    def test_list_returns_200(self):
        response = self.client.get(reverse("workspace:settings_email_accounts"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email Account Management")

    def test_create_page_returns_200(self):
        create_organization()

        response = self.client.get(reverse("workspace:settings_email_account_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create Email Account")

    def test_create_post_creates_email_account(self):
        organization = create_organization()

        response = self.client.post(
            reverse("workspace:settings_email_account_create"),
            {
                "provider": EmailAccount.Provider.IMAP,
                "display_name": "Zone mailbox",
                "email_address": "zone@example.com",
                "username": "zone@example.com",
                "host": "imap.zone.eu",
                "port": "993",
                "use_ssl": "on",
                "auth_type": "password",
                "secret": "super-secret-password",
                "is_active": "on",
            },
        )

        account = EmailAccount.objects.get(email_address="zone@example.com")
        self.assertRedirects(response, reverse("workspace:settings_email_account_detail", kwargs={"account_id": account.id}))
        self.assertEqual(account.organization, organization)
        self.assertEqual(account.encrypted_secret_placeholder, "super-secret-password")

    def test_edit_page_returns_200(self):
        organization = create_organization()
        account = create_email_account(organization)

        response = self.client.get(reverse("workspace:settings_email_account_edit", kwargs={"account_id": account.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit Email Account")

    def test_edit_post_updates_non_secret_fields(self):
        organization = create_organization()
        account = create_email_account(organization, encrypted_secret_placeholder="keep-me")

        response = self.client.post(
            reverse("workspace:settings_email_account_edit", kwargs={"account_id": account.id}),
            {
                "provider": EmailAccount.Provider.IMAP,
                "display_name": "Updated mailbox",
                "email_address": "updated@example.com",
                "username": "updated@example.com",
                "host": "imap.updated.test",
                "port": "143",
                "use_tls": "on",
                "auth_type": "password",
                "is_active": "on",
            },
        )

        account.refresh_from_db()
        self.assertRedirects(response, reverse("workspace:settings_email_account_detail", kwargs={"account_id": account.id}))
        self.assertEqual(account.display_name, "Updated mailbox")
        self.assertEqual(account.email_address, "updated@example.com")
        self.assertEqual(account.host, "imap.updated.test")
        self.assertEqual(account.encrypted_secret_placeholder, "keep-me")

    def test_edit_post_with_empty_secret_keeps_existing_secret(self):
        organization = create_organization()
        account = create_email_account(organization, encrypted_secret_placeholder="existing-secret")

        self.client.post(
            reverse("workspace:settings_email_account_edit", kwargs={"account_id": account.id}),
            {
                "provider": EmailAccount.Provider.IMAP,
                "display_name": account.display_name,
                "email_address": account.email_address,
                "username": account.username,
                "host": account.host,
                "port": "993",
                "use_ssl": "on",
                "auth_type": account.auth_type,
                "secret": "",
                "is_active": "on",
            },
        )

        account.refresh_from_db()
        self.assertEqual(account.encrypted_secret_placeholder, "existing-secret")

    def test_detail_page_masks_secret(self):
        organization = create_organization()
        account = create_email_account(organization, encrypted_secret_placeholder="super-secret-password")

        response = self.client.get(reverse("workspace:settings_email_account_detail", kwargs={"account_id": account.id}))

        self.assertContains(response, "su****rd")
        self.assertNotContains(response, "super-secret-password")

    def test_list_shows_account(self):
        organization = create_organization()
        create_email_account(organization, display_name="Visible mailbox", email_address="visible@example.com")

        response = self.client.get(reverse("workspace:settings_email_accounts"))

        self.assertContains(response, "Visible mailbox")
        self.assertContains(response, "visible@example.com")

    def test_no_secret_leaked_in_rendered_html(self):
        organization = create_organization()
        account = create_email_account(organization, encrypted_secret_placeholder="do-not-render-this")

        list_response = self.client.get(reverse("workspace:settings_email_accounts"))
        detail_response = self.client.get(reverse("workspace:settings_email_account_detail", kwargs={"account_id": account.id}))
        edit_response = self.client.get(reverse("workspace:settings_email_account_edit", kwargs={"account_id": account.id}))

        self.assertNotContains(list_response, "do-not-render-this")
        self.assertNotContains(detail_response, "do-not-render-this")
        self.assertNotContains(edit_response, "do-not-render-this")

    def test_invalid_form_shows_errors(self):
        create_organization()

        response = self.client.post(
            reverse("workspace:settings_email_account_create"),
            {
                "provider": EmailAccount.Provider.IMAP,
                "display_name": "",
                "email_address": "not-an-email",
                "secret": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "id_display_name_error")
        self.assertContains(response, "id_email_address_error")
        self.assertContains(response, "id_secret_error")

    def test_sync_button_rendered(self):
        organization = create_organization()
        account = create_email_account(organization)

        response = self.client.get(reverse("workspace:settings_email_accounts"))

        self.assertContains(response, "Sync Now")
        self.assertContains(response, f'name="email_account_id" value="{account.id}"')

    def test_settings_workspace_email_accounts_card_links_to_management_page(self):
        response = self.client.get(reverse("workspace:settings"))

        self.assertContains(response, reverse("workspace:settings_email_accounts"))

    def test_connection_test_endpoint_requires_post(self):
        organization = create_organization()
        account = create_email_account(organization)

        response = self.client.get(
            reverse("workspace:settings_email_account_test_connection", kwargs={"account_id": account.id})
        )

        self.assertEqual(response.status_code, 405)

    @patch("apps.workspace.views.IMAPEmailConnector")
    def test_imap_connector_connect_list_disconnect_called(self, connector_mock):
        organization = create_organization()
        account = create_email_account(organization)
        connector = connector_mock.return_value
        connector.list_mailboxes.return_value = ["INBOX", "Archive"]

        self.client.post(reverse("workspace:settings_email_account_test_connection", kwargs={"account_id": account.id}))

        connector_mock.assert_called_once_with(account)
        connector.connect.assert_called_once()
        connector.list_mailboxes.assert_called_once()
        connector.disconnect.assert_called_once()

    @patch("apps.workspace.views.IMAPEmailConnector")
    def test_disconnect_called_on_connection_test_failure(self, connector_mock):
        organization = create_organization()
        account = create_email_account(organization)
        connector = connector_mock.return_value
        connector.connect.side_effect = RuntimeError("failed with secret stored-secret")

        response = self.client.post(
            reverse("workspace:settings_email_account_test_connection", kwargs={"account_id": account.id}),
            follow=True,
        )

        connector.disconnect.assert_called_once()
        self.assertContains(response, "Email connection test failed. Check account settings and try again.")
        self.assertNotContains(response, "stored-secret")

    @patch("apps.workspace.views.IMAPEmailConnector")
    def test_success_message_contains_mailbox_count(self, connector_mock):
        organization = create_organization()
        account = create_email_account(organization)
        connector_mock.return_value.list_mailboxes.return_value = ["INBOX", "Sent", "Archive"]

        response = self.client.post(
            reverse("workspace:settings_email_account_test_connection", kwargs={"account_id": account.id}),
            follow=True,
        )

        self.assertContains(response, "Email connection successful. Mailboxes found: 3.")

    @patch("apps.workspace.views.IMAPEmailConnector")
    def test_provider_not_supported_handled_safely(self, connector_mock):
        organization = create_organization()
        account = create_email_account(organization, provider=EmailAccount.Provider.GMAIL)

        response = self.client.post(
            reverse("workspace:settings_email_account_test_connection", kwargs={"account_id": account.id}),
            follow=True,
        )

        connector_mock.assert_not_called()
        self.assertContains(response, "Connection test not implemented for this provider yet.")

    @patch("apps.workspace.views.IMAPEmailConnector")
    def test_error_handled_safely(self, connector_mock):
        organization = create_organization()
        account = create_email_account(organization, encrypted_secret_placeholder="very-secret-value")
        connector_mock.return_value.list_mailboxes.side_effect = RuntimeError("very-secret-value failed")

        response = self.client.post(
            reverse("workspace:settings_email_account_test_connection", kwargs={"account_id": account.id}),
            follow=True,
        )

        self.assertContains(response, "Email connection test failed. Check account settings and try again.")
        self.assertNotContains(response, "very-secret-value")

    def test_list_renders_test_connection_button(self):
        organization = create_organization()
        create_email_account(organization)

        response = self.client.get(reverse("workspace:settings_email_accounts"))

        self.assertContains(response, "Test connection")

    def test_detail_renders_test_connection_button(self):
        organization = create_organization()
        account = create_email_account(organization)

        response = self.client.get(reverse("workspace:settings_email_account_detail", kwargs={"account_id": account.id}))

        self.assertContains(response, "Test Connection")

    @patch("apps.workspace.views.IMAPEmailConnector")
    def test_connection_test_does_not_fetch_or_import_messages(self, connector_mock):
        organization = create_organization()
        account = create_email_account(organization)
        connector_mock.return_value.list_mailboxes.return_value = ["INBOX"]

        self.client.post(reverse("workspace:settings_email_account_test_connection", kwargs={"account_id": account.id}))

        self.assertFalse(EmailMessage.objects.exists())
        self.assertFalse(connector_mock.return_value.fetch_messages.called)


class AccountingIntegrationManagementUITests(TestCase):
    def test_list_returns_200(self):
        response = self.client.get(reverse("workspace:settings_accounting_integrations"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Accounting Integration Management")

    def test_create_page_returns_200(self):
        create_organization()

        response = self.client.get(reverse("workspace:settings_accounting_integration_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create Accounting Integration")

    def test_create_post_creates_accounting_integration(self):
        organization = create_organization()

        response = self.client.post(
            reverse("workspace:settings_accounting_integration_create"),
            {
                "provider": AccountingIntegration.Provider.MERIT,
                "display_name": "Merit settings",
                "api_base_url": "https://api.merit.test",
                "api_id": "api-id-123",
                "secret": "merit-secret-value",
                "project_dimension_id": "dim-project",
                "is_active": "on",
            },
        )

        integration = AccountingIntegration.objects.get(display_name="Merit settings")
        self.assertRedirects(
            response,
            reverse("workspace:settings_accounting_integration_detail", kwargs={"integration_id": integration.id}),
        )
        self.assertEqual(integration.organization, organization)
        self.assertEqual(integration.encrypted_secret_placeholder, "merit-secret-value")
        self.assertEqual(integration.metadata["project_dimension_id"], "dim-project")

    def test_edit_page_returns_200(self):
        organization = create_organization()
        integration = create_merit_integration(organization)

        response = self.client.get(
            reverse("workspace:settings_accounting_integration_edit", kwargs={"integration_id": integration.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit Accounting Integration")

    def test_edit_post_updates_non_secret_fields(self):
        organization = create_organization()
        integration = create_merit_integration(organization, metadata={"project_dimension_id": "old-dim"})

        response = self.client.post(
            reverse("workspace:settings_accounting_integration_edit", kwargs={"integration_id": integration.id}),
            {
                "provider": AccountingIntegration.Provider.MERIT,
                "display_name": "Updated Merit",
                "api_base_url": "https://updated.merit.test",
                "api_id": "updated-api-id",
                "secret": "",
                "project_dimension_id": "new-dim",
                "is_active": "on",
            },
        )

        integration.refresh_from_db()
        self.assertRedirects(
            response,
            reverse("workspace:settings_accounting_integration_detail", kwargs={"integration_id": integration.id}),
        )
        self.assertEqual(integration.display_name, "Updated Merit")
        self.assertEqual(integration.api_base_url, "https://updated.merit.test")
        self.assertEqual(integration.api_id, "updated-api-id")
        self.assertEqual(integration.encrypted_secret_placeholder, "api-secret")
        self.assertEqual(integration.metadata["project_dimension_id"], "new-dim")

    def test_edit_post_with_empty_secret_keeps_existing_secret(self):
        organization = create_organization()
        integration = create_merit_integration(organization)

        self.client.post(
            reverse("workspace:settings_accounting_integration_edit", kwargs={"integration_id": integration.id}),
            {
                "provider": AccountingIntegration.Provider.MERIT,
                "display_name": integration.display_name,
                "api_base_url": integration.api_base_url,
                "api_id": integration.api_id,
                "secret": "",
                "project_dimension_id": "",
                "is_active": "on",
            },
        )

        integration.refresh_from_db()
        self.assertEqual(integration.encrypted_secret_placeholder, "api-secret")

    def test_detail_page_masks_secret(self):
        organization = create_organization()
        integration = create_merit_integration(
            organization,
            metadata={"project_dimension_id": "dim-project"},
        )
        integration.encrypted_secret_placeholder = "super-secret-password"
        integration.save()

        response = self.client.get(
            reverse("workspace:settings_accounting_integration_detail", kwargs={"integration_id": integration.id})
        )

        self.assertContains(response, "su****rd")
        self.assertContains(response, "dim-project")
        self.assertNotContains(response, "super-secret-password")

    def test_list_shows_integration(self):
        organization = create_organization()
        create_merit_integration(organization)

        response = self.client.get(reverse("workspace:settings_accounting_integrations"))

        self.assertContains(response, "Merit Aktiva")
        self.assertContains(response, "https://merit.example.test")
        self.assertContains(response, "api-id")

    def test_no_secret_leaked_in_rendered_html(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        integration.encrypted_secret_placeholder = "do-not-render-this"
        integration.save()

        list_response = self.client.get(reverse("workspace:settings_accounting_integrations"))
        detail_response = self.client.get(
            reverse("workspace:settings_accounting_integration_detail", kwargs={"integration_id": integration.id})
        )
        edit_response = self.client.get(
            reverse("workspace:settings_accounting_integration_edit", kwargs={"integration_id": integration.id})
        )

        self.assertNotContains(list_response, "do-not-render-this")
        self.assertNotContains(detail_response, "do-not-render-this")
        self.assertNotContains(edit_response, "do-not-render-this")

    def test_invalid_form_shows_errors(self):
        create_organization()

        response = self.client.post(
            reverse("workspace:settings_accounting_integration_create"),
            {
                "provider": AccountingIntegration.Provider.MERIT,
                "display_name": "",
                "api_base_url": "not-a-url",
                "api_id": "",
                "secret": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "id_display_name_error")
        self.assertContains(response, "id_api_base_url_error")
        self.assertContains(response, "id_secret_error")

    def test_sync_dimensions_button_rendered(self):
        organization = create_organization()
        create_merit_integration(organization)

        response = self.client.get(reverse("workspace:settings_accounting_integrations"))

        self.assertContains(response, "Sync Dimensions")
        self.assertContains(response, reverse("workspace:merit_dimensions_sync"))

    def test_settings_workspace_accounting_cards_link_to_management_page(self):
        response = self.client.get(reverse("workspace:settings"))

        self.assertContains(response, reverse("workspace:settings_accounting_integrations"))

    def test_connection_test_endpoint_requires_post(self):
        organization = create_organization()
        integration = create_merit_integration(organization)

        response = self.client.get(
            reverse("workspace:settings_accounting_integration_test_connection", kwargs={"integration_id": integration.id})
        )

        self.assertEqual(response.status_code, 405)

    @patch("apps.workspace.views.MeritAPIClient")
    def test_merit_api_client_health_called(self, client_mock):
        organization = create_organization()
        integration = create_merit_integration(organization)
        client_mock.return_value.health.return_value = {
            "healthy": True,
            "provider": "merit",
            "mode": "local_check",
            "response_time_ms": 1.25,
        }

        self.client.post(
            reverse("workspace:settings_accounting_integration_test_connection", kwargs={"integration_id": integration.id})
        )

        client_mock.assert_called_once_with(integration)
        client_mock.return_value.health.assert_called_once()

    @patch("apps.workspace.views.MeritAPIClient")
    def test_success_message_rendered(self, client_mock):
        organization = create_organization()
        integration = create_merit_integration(organization)
        client_mock.return_value.health.return_value = {
            "healthy": True,
            "provider": "merit",
            "mode": "local_check",
            "response_time_ms": 2.5,
        }

        response = self.client.post(
            reverse("workspace:settings_accounting_integration_test_connection", kwargs={"integration_id": integration.id}),
            follow=True,
        )

        self.assertContains(response, "Merit connection/configuration check successful")
        self.assertContains(response, "provider merit")
        self.assertContains(response, "mode local_check")
        self.assertContains(response, "response time 2.5 ms")

    @patch("apps.workspace.views.MeritAPIClient")
    def test_unsupported_provider_handled_safely(self, client_mock):
        organization = create_organization()
        integration = AccountingIntegration.objects.create(
            organization=organization,
            provider=AccountingIntegration.Provider.XERO,
            display_name="Xero",
            encrypted_secret_placeholder="xero-secret",
        )

        response = self.client.post(
            reverse("workspace:settings_accounting_integration_test_connection", kwargs={"integration_id": integration.id}),
            follow=True,
        )

        client_mock.assert_not_called()
        self.assertContains(response, "Connection test not implemented for this provider yet.")
        self.assertNotContains(response, "xero-secret")

    @patch("apps.workspace.views.MeritAPIClient")
    def test_error_handled_safely(self, client_mock):
        organization = create_organization()
        integration = create_merit_integration(organization)
        integration.encrypted_secret_placeholder = "very-secret-value"
        integration.save()
        client_mock.return_value.health.side_effect = RuntimeError("very-secret-value failed")

        response = self.client.post(
            reverse("workspace:settings_accounting_integration_test_connection", kwargs={"integration_id": integration.id}),
            follow=True,
        )

        self.assertContains(response, "Merit connection test failed. Check integration settings and try again.")
        self.assertNotContains(response, "very-secret-value")

    def test_list_renders_test_connection_button(self):
        organization = create_organization()
        integration = create_merit_integration(organization)

        response = self.client.get(reverse("workspace:settings_accounting_integrations"))

        self.assertContains(response, "Test connection")
        self.assertContains(
            response,
            reverse("workspace:settings_accounting_integration_test_connection", kwargs={"integration_id": integration.id}),
        )

    def test_detail_renders_test_connection_button(self):
        organization = create_organization()
        integration = create_merit_integration(organization)

        response = self.client.get(
            reverse("workspace:settings_accounting_integration_detail", kwargs={"integration_id": integration.id})
        )

        self.assertContains(response, "Test Connection")
        self.assertContains(
            response,
            reverse("workspace:settings_accounting_integration_test_connection", kwargs={"integration_id": integration.id}),
        )

    @patch("apps.workspace.views.MeritAPIClient")
    def test_connection_test_does_not_sync_dimensions(self, client_mock):
        organization = create_organization()
        integration = create_merit_integration(organization)
        client_mock.return_value.health.return_value = {"healthy": True, "provider": "merit"}

        self.client.post(
            reverse("workspace:settings_accounting_integration_test_connection", kwargs={"integration_id": integration.id})
        )

        self.assertFalse(AccountingDimension.objects.exists())
        self.assertFalse(client_mock.return_value.list_dimensions.called)


class InboxMVPTests(TestCase):
    def test_inbox_returns_200_with_empty_db(self):
        response = self.client.get(reverse("workspace:inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No emails found")

    def test_inbox_ux_polish_renders_search_and_review_columns(self):
        organization = create_organization()
        create_email_message(organization, subject="UX polish email")

        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "Search subject, sender, body")
        self.assertContains(response, "Project Status")
        self.assertContains(response, "Review")

    def test_inbox_lists_imported_email(self):
        organization = create_organization()
        create_email_message(organization, subject="Imported inbox email")

        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "Imported inbox email")
        self.assertContains(response, "Sender Name")

    def test_inbox_shows_project_suggestion(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Project suggestion email")
        project = create_project(organization, code="26100", name="Inbox Project")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            status=EmailProjectLink.Status.SUGGESTED,
            confidence=90,
        )

        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "26100")
        self.assertContains(response, "suggested")

    def test_inbox_shows_confidence(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Confidence email")
        project = create_project(organization, code="26101", name="Confidence Project")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            confidence=75,
        )

        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "75%")

    def test_inbox_shows_question_count(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Question count email")
        EmailQuestion.objects.create(
            organization=organization,
            email_message=message,
            question_text="Kas saaks kinnitada?",
        )

        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "Question count email")
        self.assertContains(response, ">1<", html=False)

    def test_filter_has_questions_works(self):
        organization = create_organization()
        message_with_question = create_email_message(organization, subject="Has question")
        create_email_message(organization, subject="No question")
        EmailQuestion.objects.create(
            organization=organization,
            email_message=message_with_question,
            question_text="Can you confirm?",
        )

        response = self.client.get(reverse("workspace:inbox"), {"filter": "has_questions"})

        self.assertContains(response, "Has question")
        self.assertNotContains(response, "No question")

    def test_filter_no_project_works(self):
        organization = create_organization()
        no_project_message = create_email_message(organization, subject="No project email")
        project_message = create_email_message(organization, subject="With project email")
        project = create_project(organization, code="26102", name="Linked Project")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=project_message,
            project=project,
        )

        response = self.client.get(reverse("workspace:inbox"), {"filter": "no_project"})

        self.assertContains(response, no_project_message.subject)
        self.assertNotContains(response, project_message.subject)

    def test_search_by_subject_works(self):
        organization = create_organization()
        create_email_message(organization, subject="Kanarbiku search email")
        create_email_message(organization, subject="Unrelated email")

        response = self.client.get(reverse("workspace:inbox"), {"q": "Kanarbiku"})

        self.assertContains(response, "Kanarbiku search email")
        self.assertNotContains(response, "Unrelated email")

    def test_email_detail_route_returns_200(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Detail route email")

        response = self.client.get(reverse("workspace:inbox_detail", kwargs={"email_id": message.id}))

        self.assertEqual(response.status_code, 200)

    def test_email_detail_shows_subject_body_and_evidence(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Evidence detail email")
        message.body_text = "Detail body content"
        message.save(update_fields=["body_text"])
        project = create_project(organization, code="26103", name="Evidence Project")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            confidence=90,
            evidence={"matched": "subject"},
        )
        EmailQuestion.objects.create(
            organization=organization,
            email_message=message,
            question_text="Please confirm?",
            evidence={"keyword": "please"},
        )
        EmailAttachment.objects.create(
            organization=organization,
            email_message=message,
            original_filename="evidence.pdf",
        )

        response = self.client.get(reverse("workspace:inbox_detail", kwargs={"email_id": message.id}))

        self.assertContains(response, "Evidence detail email")
        self.assertContains(response, "Detail body content")
        self.assertContains(response, "matched")
        self.assertContains(response, "Please confirm?")
        self.assertContains(response, "evidence.pdf")


class ManualEmailSyncTests(TestCase):
    def test_sync_endpoint_requires_post(self):
        response = self.client.get(reverse("workspace:inbox_sync"))

        self.assertEqual(response.status_code, 405)

    @patch("apps.workspace.views.EmailSyncService.sync")
    def test_sync_endpoint_calls_email_sync_service(self, sync_mock):
        sync_mock.return_value = {
            "fetched_count": 2,
            "imported_count": 1,
            "processed_count": 1,
        }
        organization = create_organization()
        account = create_email_account(organization)

        self.client.post(reverse("workspace:inbox_sync"))

        sync_mock.assert_called_once()
        command = sync_mock.call_args.args[0]
        self.assertEqual(command.email_account, account)
        self.assertEqual(command.limit, 10)
        self.assertTrue(command.process_imported)

    @patch("apps.workspace.views.EmailSyncService.sync")
    def test_sync_success_redirects_and_message_contains_counts(self, sync_mock):
        sync_mock.return_value = {
            "fetched_count": 3,
            "imported_count": 2,
            "processed_count": 1,
        }
        organization = create_organization()
        create_email_account(organization)

        response = self.client.post(reverse("workspace:inbox_sync"), follow=True)

        self.assertRedirects(response, reverse("workspace:inbox"))
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("fetched 3" in message for message in messages))
        self.assertTrue(any("imported 2" in message for message in messages))
        self.assertTrue(any("processed 1" in message for message in messages))

    def test_sync_no_active_account_handled(self):
        response = self.client.post(reverse("workspace:inbox_sync"), follow=True)

        self.assertRedirects(response, reverse("workspace:inbox"))
        self.assertContains(response, "No active email account is configured yet")

    @patch("apps.workspace.views.EmailSyncService.sync")
    def test_sync_error_handled(self, sync_mock):
        sync_mock.side_effect = RuntimeError("secret connection detail")
        organization = create_organization()
        create_email_account(organization)

        response = self.client.post(reverse("workspace:inbox_sync"), follow=True)

        self.assertRedirects(response, reverse("workspace:inbox"))
        self.assertContains(response, "Email sync failed")
        self.assertNotContains(response, "secret connection detail")

    def test_dashboard_renders_sync_button(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Sync now")
        self.assertContains(response, reverse("workspace:inbox_sync"))
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_inbox_renders_sync_button(self):
        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "Sync now")
        self.assertContains(response, reverse("workspace:inbox_sync"))
        self.assertContains(response, "csrfmiddlewaretoken")


class ProjectListManagementUITests(TestCase):
    def test_projects_page_returns_200(self):
        response = self.client.get(reverse("workspace:projects"))

        self.assertEqual(response.status_code, 200)

    def test_project_list_shows_existing_project(self):
        organization = create_organization()
        create_project(organization, code="26124", name="Kanarbiku")

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "26124")
        self.assertContains(response, "Kanarbiku")

    def test_accounting_dimension_cache_appears(self):
        organization = create_organization()
        AccountingDimension.objects.create(
            organization=organization,
            code="26125",
            name="Merit cached project",
        )

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "26125")
        self.assertContains(response, "Merit cached project")
        self.assertContains(response, "Merit cache")

    def test_dimension_with_matching_project_shows_linked(self):
        organization = create_organization()
        create_project(organization, code="26126", name="Linked project")
        AccountingDimension.objects.create(
            organization=organization,
            code="26126",
            name="Linked project",
        )

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "linked")

    def test_dimension_without_project_shows_missing_in_workspace(self):
        organization = create_organization()
        AccountingDimension.objects.create(
            organization=organization,
            code="26127",
            name="Missing Workspace project",
        )

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "missing_in_workspace")

    def test_workspace_project_without_dimension_shows_workspace_only(self):
        organization = create_organization()
        create_project(organization, code="26128", name="Workspace only project")

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "workspace_only")

    def test_create_page_returns_200(self):
        create_organization()

        response = self.client.get(reverse("workspace:project_create"))

        self.assertEqual(response.status_code, 200)

    def test_suggested_code_is_shown(self):
        organization = create_organization()
        create_project(organization, code="26129", name="Existing project")

        response = self.client.get(reverse("workspace:project_create"))

        self.assertContains(response, "Suggested next code")
        self.assertContains(response, "26130")

    def test_create_page_without_active_merit_integration_disables_checkbox(self):
        create_organization()

        response = self.client.get(reverse("workspace:project_create"))

        self.assertContains(response, "No active Merit integration configured.")
        self.assertContains(response, 'name="create_merit_dimension"', html=False)
        self.assertContains(response, "disabled", html=False)

    def test_create_page_with_merit_integration_shows_dimension_option(self):
        organization = create_organization()
        create_merit_integration(organization, metadata={"project_dimension_id": "dim-project"})

        response = self.client.get(reverse("workspace:project_create"))

        self.assertContains(response, "Create matching Merit dimension value")
        self.assertContains(response, "dim-project")
        self.assertNotContains(response, "No active Merit integration configured.")

    @patch("apps.workspace.views.ProjectCreationService.create_with_suggested_code")
    def test_submit_creates_project_through_service(self, create_mock):
        organization = create_organization()
        project = Project(
            id=1,
            organization=organization,
            code="26131",
            name="Created through service",
        )
        create_mock.return_value = CreateProjectWithSuggestedCodeResult(
            project=project,
            suggested_code="26131",
            allocation_summary={},
        )

        response = self.client.post(
            reverse("workspace:project_create"),
            {
                "name": "Created through service",
                "description": "Created from UI",
                "project_type": Project.Type.ELECTRICAL,
                "status": Project.Status.PLANNED,
                "min_code": "26131",
                "prefix": "26",
            },
        )

        self.assertRedirects(response, reverse("workspace:projects"))
        create_mock.assert_called_once()
        command = create_mock.call_args.args[0]
        self.assertEqual(command.organization, organization)
        self.assertEqual(command.name, "Created through service")
        self.assertEqual(command.description, "Created from UI")
        self.assertEqual(command.project_type, Project.Type.ELECTRICAL)
        self.assertEqual(command.status, Project.Status.PLANNED)
        self.assertEqual(command.min_code, "26131")
        self.assertEqual(command.prefix, "26")

    @patch("apps.workspace.views.AccountingDimensionValueService.create")
    @patch("apps.workspace.views.ProjectCreationService.create_with_suggested_code")
    def test_create_project_without_merit_dimension_does_not_call_merit_service(self, create_mock, merit_mock):
        organization = create_organization()
        project = Project(id=1, organization=organization, code="26140", name="Workspace only")
        create_mock.return_value = CreateProjectWithSuggestedCodeResult(
            project=project,
            suggested_code="26140",
            allocation_summary={},
        )

        response = self.client.post(
            reverse("workspace:project_create"),
            {"name": "Workspace only"},
            follow=True,
        )

        self.assertRedirects(response, reverse("workspace:projects"))
        create_mock.assert_called_once()
        merit_mock.assert_not_called()
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Project 26140 Workspace only created." in message for message in messages))

    @patch("apps.workspace.views.AccountingDimensionValueService.create")
    @patch("apps.workspace.views.ProjectCreationService.create_with_suggested_code")
    def test_create_project_with_merit_dimension_calls_accounting_service(self, create_mock, merit_mock):
        organization = create_organization()
        integration = create_merit_integration(organization, metadata={"project_dimension_id": "dim-project"})
        project = Project(id=1, organization=organization, code="26141", name="With Merit")
        create_mock.return_value = CreateProjectWithSuggestedCodeResult(
            project=project,
            suggested_code="26141",
            allocation_summary={},
        )
        merit_mock.return_value = CreateAccountingDimensionValueResult(
            dimension=object(),
            dto=object(),
            created=True,
            updated=False,
            metadata={},
        )

        response = self.client.post(
            reverse("workspace:project_create"),
            {
                "name": "With Merit",
                "project_type": Project.Type.ELECTRICAL,
                "status": Project.Status.ACTIVE,
                "create_merit_dimension": "on",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("workspace:projects"))
        merit_mock.assert_called_once()
        command = merit_mock.call_args.args[0]
        self.assertEqual(command.integration, integration)
        self.assertEqual(command.code, "26141")
        self.assertEqual(command.name, "With Merit")
        self.assertEqual(command.dimension_type, "project")
        self.assertEqual(command.dimension_id, "dim-project")
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Merit dimension value synced" in message for message in messages))

    @patch("apps.workspace.views.AccountingDimensionValueService.create")
    @patch("apps.workspace.views.ProjectCreationService.create_with_suggested_code")
    def test_missing_project_dimension_id_handled_safely(self, create_mock, merit_mock):
        organization = create_organization()
        create_merit_integration(organization)
        project = Project(id=1, organization=organization, code="26142", name="Missing dim id")
        create_mock.return_value = CreateProjectWithSuggestedCodeResult(
            project=project,
            suggested_code="26142",
            allocation_summary={},
        )

        response = self.client.post(
            reverse("workspace:project_create"),
            {"name": "Missing dim id", "create_merit_dimension": "on"},
            follow=True,
        )

        self.assertRedirects(response, reverse("workspace:projects"))
        merit_mock.assert_not_called()
        self.assertContains(response, "Merit project dimension id is missing")

    @patch("apps.workspace.views.AccountingDimensionValueService.create")
    @patch("apps.workspace.views.ProjectCreationService.create_with_suggested_code")
    def test_merit_service_error_handled_safely(self, create_mock, merit_mock):
        organization = create_organization()
        create_merit_integration(organization, metadata={"project_dimension_id": "dim-project"})
        project = Project(id=1, organization=organization, code="26143", name="Merit fails")
        create_mock.return_value = CreateProjectWithSuggestedCodeResult(
            project=project,
            suggested_code="26143",
            allocation_summary={},
        )
        merit_mock.side_effect = RuntimeError("secret api error")

        response = self.client.post(
            reverse("workspace:project_create"),
            {"name": "Merit fails", "create_merit_dimension": "on"},
            follow=True,
        )

        self.assertRedirects(response, reverse("workspace:projects"))
        self.assertContains(response, "Project was created, but Merit dimension value creation failed.")
        self.assertNotContains(response, "secret api error")

    def test_project_create_get_does_not_mutate(self):
        create_organization()

        with patch("apps.workspace.views.ProjectCreationService.create_with_suggested_code") as create_mock:
            with patch("apps.workspace.views.AccountingDimensionValueService.create") as merit_mock:
                response = self.client.get(reverse("workspace:project_create"))

        self.assertEqual(response.status_code, 200)
        create_mock.assert_not_called()
        merit_mock.assert_not_called()

    def test_project_detail_page_returns_200(self):
        organization = create_organization()
        project = create_project(organization, code="26132", name="Detail project")

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Detail project")
        self.assertContains(response, "Parties")
        self.assertContains(response, "Communications")

    def test_filter_active_works(self):
        organization = create_organization()
        create_project(organization, code="26133", name="Active project")
        Project.objects.create(
            organization=organization,
            code="26134",
            name="Planned project",
            status=Project.Status.PLANNED,
        )

        response = self.client.get(reverse("workspace:projects"), {"filter": "active"})

        self.assertContains(response, "Active project")
        self.assertNotContains(response, "Planned project")

    def test_filter_missing_in_workspace_works(self):
        organization = create_organization()
        create_project(organization, code="26135", name="Workspace project")
        AccountingDimension.objects.create(
            organization=organization,
            code="26136",
            name="Missing project dimension",
        )

        response = self.client.get(reverse("workspace:projects"), {"filter": "missing_in_workspace"})

        self.assertContains(response, "Missing project dimension")
        self.assertNotContains(response, "26135")

    def test_search_works(self):
        organization = create_organization()
        create_project(organization, code="26137", name="Searchable Workspace")
        AccountingDimension.objects.create(
            organization=organization,
            code="26138",
            name="Searchable Dimension",
        )
        create_project(organization, code="26139", name="Other project")

        response = self.client.get(reverse("workspace:projects"), {"q": "Dimension"})

        self.assertContains(response, "Searchable Dimension")
        self.assertNotContains(response, "Searchable Workspace")
        self.assertNotContains(response, "Other project")

    def test_project_list_defaults_to_code_descending(self):
        organization = create_organization()
        create_project(organization, code="26110", name="Lower project")
        create_project(organization, code="26199", name="Higher project")

        response = self.client.get(reverse("workspace:projects"))
        content = response.content.decode()

        self.assertLess(content.index("26199"), content.index("26110"))

    def test_project_list_shows_database_id_updated_and_actions(self):
        organization = create_organization()
        project = create_project(organization, code="26144", name="Action project")

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "DB ID")
        self.assertContains(response, str(project.id))
        self.assertContains(response, "Updated")
        self.assertContains(response, reverse("workspace:project_edit", args=[project.id]))
        self.assertContains(response, reverse("workspace:project_financials", args=[project.id]))
        self.assertContains(response, "Change status")

    def test_search_by_project_id_and_description_works(self):
        organization = create_organization()
        project = Project.objects.create(
            organization=organization,
            code="26145",
            name="ID searchable",
            description="Unique project description marker",
        )
        create_project(organization, code="26146", name="Other project")

        id_response = self.client.get(reverse("workspace:projects"), {"q": str(project.id)})
        description_response = self.client.get(reverse("workspace:projects"), {"q": "description marker"})

        self.assertContains(id_response, "ID searchable")
        self.assertContains(description_response, "ID searchable")
        self.assertNotContains(description_response, "Other project")

    def test_filter_completed_and_archived_work(self):
        organization = create_organization()
        completed = create_project(organization, code="26147", name="Completed project")
        archived = create_project(organization, code="26148", name="Archived project")
        completed.status = Project.Status.COMPLETED
        archived.status = Project.Status.ARCHIVED
        completed.save(update_fields=["status", "updated_at"])
        archived.save(update_fields=["status", "updated_at"])

        completed_response = self.client.get(reverse("workspace:projects"), {"filter": "completed"})
        archived_response = self.client.get(reverse("workspace:projects"), {"filter": "archived"})

        self.assertContains(completed_response, "Completed project")
        self.assertNotContains(completed_response, "Archived project")
        self.assertContains(archived_response, "Archived project")
        self.assertNotContains(archived_response, "Completed project")

    def test_merit_only_row_has_no_edit_or_status_action(self):
        organization = create_organization()
        AccountingDimension.objects.create(
            organization=organization,
            code="26149",
            name="Only in Merit",
        )

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "Only in Merit")
        self.assertContains(response, "Create Workspace Project")
        self.assertNotContains(response, "/workspace/projects/26149/edit/")

    def test_missing_dimension_row_shows_dimension_details_and_create_action(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        dimension = AccountingDimension.objects.create(
            organization=organization,
            integration=integration,
            code="26156",
            name="Merit only detail",
            provider=AccountingDimension.Provider.MERIT,
            is_active=True,
        )

        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, f"#{dimension.id}")
        self.assertContains(response, "merit")
        self.assertContains(response, "Merit Aktiva")
        self.assertContains(response, "active")
        self.assertContains(response, reverse("workspace:project_create_from_dimension", args=[dimension.id]))
        self.assertContains(response, "Create Workspace Project")

    def test_create_from_dimension_get_does_not_mutate(self):
        organization = create_organization()
        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26157",
            name="GET no mutate",
        )

        response = self.client.get(reverse("workspace:project_create_from_dimension", args=[dimension.id]))

        self.assertEqual(response.status_code, 405)
        self.assertFalse(Project.objects.filter(code="26157").exists())

    @patch("apps.workspace.views.ProjectDimensionImportService.create_project")
    def test_create_from_dimension_post_calls_service(self, import_mock):
        organization = create_organization()
        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26158",
            name="Import through UI",
        )
        project = Project.objects.create(
            organization=organization,
            code="26158",
            name="Import through UI",
        )
        import_mock.return_value = CreateProjectFromAccountingDimensionResult(
            project=project,
            accounting_dimension=dimension,
            created=True,
            linked_allocation_count=0,
            message="created",
        )

        response = self.client.post(reverse("workspace:project_create_from_dimension", args=[dimension.id]))

        self.assertRedirects(response, reverse("workspace:project_detail", args=[project.id]))
        import_mock.assert_called_once()
        command = import_mock.call_args.args[0]
        self.assertEqual(command.accounting_dimension, dimension)
        self.assertEqual(command.status, Project.Status.ACTIVE)
        self.assertEqual(command.project_type, Project.Type.ELECTRICAL)

    def test_create_from_dimension_relinks_gl_and_financials_are_available(self):
        organization = create_organization()
        project_code = "26159"
        integration, _batch, _entry, allocation = create_gl_account(
            organization,
            account_code="4002",
            account_name="Materials",
        )
        allocation.dimension_code = project_code
        allocation.dimension_name = "Imported Merit project"
        allocation.project = None
        allocation.save(update_fields=["dimension_code", "dimension_name", "project"])
        AccountingAccountClassification.objects.create(
            organization=organization,
            integration=integration,
            account_code="4002",
            account_name="Materials",
            category=AccountingAccountClassification.Category.MATERIAL_COST,
            reporting_sign="1",
        )
        dimension = AccountingDimension.objects.create(
            organization=organization,
            integration=integration,
            code=project_code,
            name="Imported Merit project",
        )
        allocation.accounting_dimension = dimension
        allocation.save(update_fields=["accounting_dimension"])

        response = self.client.post(reverse("workspace:project_create_from_dimension", args=[dimension.id]))

        project = Project.objects.get(code=project_code)
        self.assertRedirects(response, reverse("workspace:project_detail", args=[project.id]))
        allocation.refresh_from_db()
        self.assertEqual(allocation.project, project)
        financials = self.client.get(
            reverse("workspace:project_financials", args=[project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30"},
        )
        self.assertEqual(financials.status_code, 200)
        self.assertContains(financials, "75,00")

    def test_projects_list_changes_to_linked_after_dimension_import(self):
        organization = create_organization()
        dimension = AccountingDimension.objects.create(
            organization=organization,
            code="26160",
            name="Linked after import",
        )

        before = self.client.get(reverse("workspace:projects"))
        self.assertContains(before, "missing_in_workspace")

        self.client.post(reverse("workspace:project_create_from_dimension", args=[dimension.id]))
        after = self.client.get(reverse("workspace:projects"))

        project = Project.objects.get(code="26160")
        self.assertContains(after, str(project.id))
        self.assertContains(after, "active")
        self.assertContains(after, "linked")
        self.assertContains(after, reverse("workspace:project_edit", args=[project.id]))
        self.assertContains(after, reverse("workspace:project_financials", args=[project.id]))

    def test_project_edit_page_returns_200_and_shows_read_only_identity(self):
        organization = create_organization()
        project = create_project(organization, code="26150", name="Editable project")

        response = self.client.get(reverse("workspace:project_edit", args=[project.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Read-only identity")
        self.assertContains(response, "26150")
        self.assertContains(response, "Use the Lifecycle panel to change project status")

    def test_project_edit_post_updates_safe_fields_not_code(self):
        organization = create_organization()
        project = create_project(organization, code="26151", name="Old name")

        response = self.client.post(
            reverse("workspace:project_edit", args=[project.id]),
            {
                "name": "New name",
                "description": "Updated description",
                "project_type": Project.Type.ELECTRICAL,
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            },
        )

        self.assertRedirects(response, reverse("workspace:project_detail", args=[project.id]))
        project.refresh_from_db()
        self.assertEqual(project.code, "26151")
        self.assertEqual(project.name, "New name")
        self.assertEqual(project.description, "Updated description")
        self.assertEqual(project.project_type, Project.Type.ELECTRICAL)
        self.assertEqual(project.status, Project.Status.ACTIVE)
        self.assertTrue(AuditEvent.objects.filter(event_type="project.details_updated").exists())

    def test_status_endpoint_requires_post_and_get_does_not_mutate(self):
        organization = create_organization()
        project = create_project(organization, code="26152", name="Status project")

        response = self.client.get(reverse("workspace:project_status", args=[project.id]))

        self.assertEqual(response.status_code, 405)
        project.refresh_from_db()
        self.assertEqual(project.status, Project.Status.ACTIVE)

    def test_status_endpoint_changes_status_through_service(self):
        organization = create_organization()
        project = create_project(organization, code="26153", name="Status service project")

        with patch.object(ProjectStatusService, "change_status", wraps=ProjectStatusService.change_status) as change_mock:
            response = self.client.post(
                reverse("workspace:project_status", args=[project.id]),
                {"new_status": Project.Status.COMPLETED, "reason": "Finished"},
            )

        self.assertRedirects(response, reverse("workspace:project_detail", args=[project.id]))
        change_mock.assert_called_once()
        command = change_mock.call_args.args[0]
        self.assertIsInstance(command, ChangeProjectStatusCommand)
        project.refresh_from_db()
        self.assertEqual(project.status, Project.Status.COMPLETED)

    def test_completed_and_archived_financials_still_return_200(self):
        organization = create_organization()
        completed = create_project(organization, code="26154", name="Completed financials")
        archived = create_project(organization, code="26155", name="Archived financials")
        completed.status = Project.Status.COMPLETED
        archived.status = Project.Status.ARCHIVED
        completed.save(update_fields=["status", "updated_at"])
        archived.save(update_fields=["status", "updated_at"])

        self.assertEqual(self.client.get(reverse("workspace:project_financials", args=[completed.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("workspace:project_financials", args=[archived.id])).status_code, 200)


class MeritDimensionSyncUITests(TestCase):
    def _result(self, integration, conflict_count=0):
        return SyncAccountingDimensionsResult(
            integration=integration,
            created_count=2,
            updated_count=1,
            unchanged_count=3,
            archived_count=1,
            conflict_count=conflict_count,
            dimensions=[],
            conflicts=[{"type": "duplicate_incoming_code"}] if conflict_count else [],
            metadata={},
        )

    def test_sync_endpoint_requires_post(self):
        response = self.client.get(reverse("workspace:merit_dimensions_sync"))

        self.assertEqual(response.status_code, 405)

    @patch("apps.workspace.views.AccountingDimensionSyncService.sync")
    def test_sync_endpoint_calls_accounting_dimension_sync_service(self, sync_mock):
        organization = create_organization()
        integration = create_merit_integration(organization)
        sync_mock.return_value = self._result(integration)

        self.client.post(reverse("workspace:merit_dimensions_sync"))

        sync_mock.assert_called_once()
        command = sync_mock.call_args.args[0]
        self.assertEqual(command.integration, integration)
        self.assertEqual(command.metadata, {"source": "workspace_merit_dimension_sync"})

    @patch("apps.workspace.views.AccountingDimensionSyncService.sync")
    def test_sync_success_redirects_to_projects_and_message_contains_counts(self, sync_mock):
        organization = create_organization()
        integration = create_merit_integration(organization)
        sync_mock.return_value = self._result(integration)

        response = self.client.post(reverse("workspace:merit_dimensions_sync"), follow=True)

        self.assertRedirects(response, reverse("workspace:projects"))
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("created 2" in message for message in messages))
        self.assertTrue(any("updated 1" in message for message in messages))
        self.assertTrue(any("unchanged 3" in message for message in messages))
        self.assertTrue(any("archived 1" in message for message in messages))
        self.assertTrue(any("conflicts 0" in message for message in messages))

    def test_no_active_merit_integration_handled_safely(self):
        response = self.client.post(reverse("workspace:merit_dimensions_sync"), follow=True)

        self.assertRedirects(response, reverse("workspace:projects"))
        self.assertContains(response, "No active Merit integration is configured yet")

    @patch("apps.workspace.views.AccountingDimensionSyncService.sync")
    def test_sync_error_handled_safely(self, sync_mock):
        organization = create_organization()
        create_merit_integration(organization)
        sync_mock.side_effect = RuntimeError("secret api error")

        response = self.client.post(reverse("workspace:merit_dimensions_sync"), follow=True)

        self.assertRedirects(response, reverse("workspace:projects"))
        self.assertContains(response, "Merit dimension sync failed")
        self.assertNotContains(response, "secret api error")

    def test_projects_page_renders_sync_button(self):
        response = self.client.get(reverse("workspace:projects"))

        self.assertContains(response, "Sync Merit dimensions")
        self.assertContains(response, reverse("workspace:merit_dimensions_sync"))
        self.assertContains(response, "csrfmiddlewaretoken")

    @patch("apps.workspace.views.AccountingDimensionSyncService.sync")
    def test_conflicts_produce_warning_message(self, sync_mock):
        organization = create_organization()
        integration = create_merit_integration(organization)
        sync_mock.return_value = self._result(integration, conflict_count=2)

        response = self.client.post(reverse("workspace:merit_dimensions_sync"), follow=True)

        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any(message.level_tag == "warning" for message in messages))
        self.assertTrue(any("conflicts 2" in str(message) for message in messages))
        self.assertTrue(any("Review dimension conflicts" in str(message) for message in messages))


class AccountingDimensionConflictReviewUITests(TestCase):
    def _sync_event(self, organization, conflicts):
        return AuditEvent.objects.create(
            organization=organization,
            event_type="accounting_dimension_sync_completed",
            object_type="AccountingIntegration",
            object_id="1",
            message="Completed accounting dimension sync for Merit Aktiva.",
            metadata={
                "source": "workspace_merit_dimension_sync",
                "conflict_count": len(conflicts),
                "conflicts": conflicts,
            },
        )

    def test_conflicts_page_returns_200(self):
        response = self.client.get(reverse("workspace:accounting_dimension_conflicts"))

        self.assertEqual(response.status_code, 200)

    def test_empty_state_renders(self):
        response = self.client.get(reverse("workspace:accounting_dimension_conflicts"))

        self.assertContains(response, "No dimension conflicts found.")

    def test_conflict_from_latest_sync_audit_metadata_renders(self):
        organization = create_organization()
        self._sync_event(
            organization,
            [{"type": "duplicate_incoming_code", "code": "26000", "dimension_type": "project"}],
        )
        self._sync_event(
            organization,
            [
                {
                    "type": "same_code_different_external_id",
                    "code": "26124",
                    "dimension_type": "project",
                    "existing_external_id": "m-existing",
                    "incoming_external_id": "m-new",
                }
            ],
        )

        response = self.client.get(reverse("workspace:accounting_dimension_conflicts"))

        self.assertContains(response, "same_code_different_external_id")
        self.assertContains(response, "26124")
        self.assertContains(response, "m-existing / m-new")
        self.assertNotContains(response, "26000")

    def test_local_dimension_is_shown_when_matched(self):
        organization = create_organization()
        create_merit_integration(organization)
        AccountingDimension.objects.create(
            organization=organization,
            provider=AccountingIntegration.Provider.MERIT,
            external_id="m-existing",
            code="26124",
            name="Local Kanarbiku",
        )
        self._sync_event(
            organization,
            [
                {
                    "type": "same_code_different_external_id",
                    "code": "26124",
                    "dimension_type": "project",
                    "existing_external_id": "m-existing",
                    "incoming_external_id": "m-new",
                }
            ],
        )

        response = self.client.get(reverse("workspace:accounting_dimension_conflicts"))

        self.assertContains(response, "Local Kanarbiku")

    def test_links_to_conflict_page_render_from_relevant_pages(self):
        organization = create_organization()
        integration = create_merit_integration(organization)
        conflict_url = reverse("workspace:accounting_dimension_conflicts")

        self.assertContains(self.client.get(reverse("workspace:projects")), conflict_url)
        self.assertContains(self.client.get(reverse("workspace:settings")), conflict_url)
        self.assertContains(
            self.client.get(
                reverse("workspace:settings_accounting_integration_detail", kwargs={"integration_id": integration.id})
            ),
            conflict_url,
        )

    def test_no_secret_leaked(self):
        organization = create_organization()
        create_merit_integration(organization)
        self._sync_event(
            organization,
            [{"type": "duplicate_incoming_code", "code": "26124", "dimension_type": "project"}],
        )

        response = self.client.get(reverse("workspace:accounting_dimension_conflicts"))

        self.assertNotContains(response, "api-secret")

    def test_get_does_not_mutate_database(self):
        organization = create_organization()
        self._sync_event(
            organization,
            [{"type": "duplicate_incoming_code", "code": "26124", "dimension_type": "project"}],
        )
        audit_count = AuditEvent.objects.count()
        dimension_count = AccountingDimension.objects.count()

        self.client.get(reverse("workspace:accounting_dimension_conflicts"))

        self.assertEqual(AuditEvent.objects.count(), audit_count)
        self.assertEqual(AccountingDimension.objects.count(), dimension_count)


class ProjectWorkspaceTests(TestCase):
    def test_project_workspace_returns_200(self):
        organization = create_organization()
        project = create_project(organization, code="26200", name="Workspace detail")

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertEqual(response.status_code, 200)

    def test_overview_shows_project_code_and_name(self):
        organization = create_organization()
        project = create_project(organization, code="26201", name="Overview project")

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "26201")
        self.assertContains(response, "Overview project")
        self.assertContains(response, "Overview")

    def test_shows_parties(self):
        organization = create_organization()
        project = create_project(organization, code="26202", name="People project")
        ProjectParty.objects.create(
            organization=organization,
            project=project,
            role=ProjectParty.Role.SUPPLIER,
            name="Project Supplier",
            company_name="Supplier OÜ",
            email="supplier@example.com",
            phone="+372 5555",
        )

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "Project Supplier")
        self.assertContains(response, "supplier")
        self.assertContains(response, "Supplier OÜ")

    def test_shows_addresses(self):
        organization = create_organization()
        project = create_project(organization, code="26203", name="Address project")
        ProjectAddress.objects.create(
            organization=organization,
            project=project,
            address_type=ProjectAddress.Type.SITE,
            label="Main site",
            city="Tallinn",
            street="Example 1",
            is_primary=True,
        )

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "Main site")
        self.assertContains(response, "Tallinn")
        self.assertContains(response, "primary")

    def test_shows_related_emails(self):
        organization = create_organization()
        project = create_project(organization, code="26204", name="Email project")
        message = create_email_message(organization, subject="Project communication")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            confidence=88,
            status=EmailProjectLink.Status.SUGGESTED,
        )

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "Project communication")
        self.assertContains(response, "88%")
        self.assertContains(response, "suggested")

    def test_shows_questions(self):
        organization = create_organization()
        project = create_project(organization, code="26205", name="Question project")
        message = create_email_message(organization, subject="Question communication")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
        )
        EmailQuestion.objects.create(
            organization=organization,
            email_message=message,
            question_text="Kas saab kinnitada?",
            evidence={"keyword": "kas"},
        )

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "Questions")
        self.assertContains(response, ">1<", html=False)

    def test_shows_evidence(self):
        organization = create_organization()
        project = create_project(organization, code="26206", name="Evidence project")
        message = create_email_message(organization, subject="Evidence communication")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
            confidence=90,
            evidence={"matched_project_code": "26206"},
        )

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "Evidence")
        self.assertContains(response, "email_project_link")
        self.assertContains(response, "matched_project_code")

    def test_shows_documents_when_attachments_linked_to_documents(self):
        organization = create_organization()
        project = create_project(organization, code="26207", name="Document project")
        message = create_email_message(organization, subject="Document communication")
        EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=project,
        )
        document = Document.objects.create(
            organization=organization,
            title="Project contract",
            original_filename="contract.pdf",
            source=Document.Source.MANUAL_UPLOAD,
            status=Document.Status.PARSED,
        )
        EmailAttachment.objects.create(
            organization=organization,
            email_message=message,
            document=document,
            original_filename="contract.pdf",
        )

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "Project contract")
        self.assertContains(response, "contract.pdf")
        self.assertContains(response, "parsed")

    def test_empty_project_renders_empty_states(self):
        organization = create_organization()
        project = create_project(organization, code="26208", name="Empty project")

        response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertContains(response, "No timeline yet")
        self.assertContains(response, "No related emails")
        self.assertContains(response, "No related documents")
        self.assertContains(response, "No people yet")
        self.assertContains(response, "No addresses yet")
        self.assertContains(response, "No evidence yet")

    def test_project_knowledge_builder_is_used(self):
        organization = create_organization()
        project = create_project(organization, code="26209", name="Knowledge builder project")

        with patch(
            "apps.workspace.services.projects.ProjectKnowledgeBuilder.build",
            wraps=ProjectKnowledgeBuilder.build,
        ) as build_mock:
            response = self.client.get(reverse("workspace:project_detail", kwargs={"project_id": project.id}))

        self.assertEqual(response.status_code, 200)
        build_mock.assert_called_once()


class ProjectLinkReviewUITests(TestCase):
    def _suggested_link(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Review suggestion email")
        suggested_project = create_project(organization, code="26300", name="Suggested Project")
        other_project = create_project(organization, code="26301", name="Correct Project")
        link = EmailProjectLink.objects.create(
            organization=organization,
            email_message=message,
            project=suggested_project,
            status=EmailProjectLink.Status.SUGGESTED,
            confidence=91,
            evidence={"matched_project_code": "26300"},
        )
        return link, other_project

    def test_confirm_endpoint_requires_post(self):
        link, _other_project = self._suggested_link()

        response = self.client.get(reverse("workspace:project_link_confirm", kwargs={"link_id": link.id}))

        self.assertEqual(response.status_code, 405)

    def test_reject_endpoint_requires_post(self):
        link, _other_project = self._suggested_link()

        response = self.client.get(reverse("workspace:project_link_reject", kwargs={"link_id": link.id}))

        self.assertEqual(response.status_code, 405)

    def test_correct_endpoint_requires_post(self):
        link, _other_project = self._suggested_link()

        response = self.client.get(reverse("workspace:project_link_correct", kwargs={"link_id": link.id}))

        self.assertEqual(response.status_code, 405)

    def test_confirm_changes_link_status(self):
        link, _other_project = self._suggested_link()

        response = self.client.post(
            reverse("workspace:project_link_confirm", kwargs={"link_id": link.id}),
            {"next": reverse("workspace:reviews")},
            follow=True,
        )

        link.refresh_from_db()
        self.assertRedirects(response, reverse("workspace:reviews"))
        self.assertEqual(link.status, EmailProjectLink.Status.CONFIRMED)
        self.assertIsNotNone(link.confirmed_at)

    def test_reject_changes_link_status(self):
        link, _other_project = self._suggested_link()

        response = self.client.post(
            reverse("workspace:project_link_reject", kwargs={"link_id": link.id}),
            {"reason": "Wrong project", "next": reverse("workspace:reviews")},
            follow=True,
        )

        link.refresh_from_db()
        self.assertRedirects(response, reverse("workspace:reviews"))
        self.assertEqual(link.status, EmailProjectLink.Status.REJECTED)
        self.assertEqual(link.metadata["rejection_reason"], "Wrong project")

    def test_correct_creates_confirmed_link_for_new_project(self):
        link, other_project = self._suggested_link()

        response = self.client.post(
            reverse("workspace:project_link_correct", kwargs={"link_id": link.id}),
            {
                "new_project_id": other_project.id,
                "reason": "Better match",
                "next": reverse("workspace:reviews"),
            },
            follow=True,
        )

        link.refresh_from_db()
        confirmed_link = EmailProjectLink.objects.get(email_message=link.email_message, project=other_project)
        self.assertRedirects(response, reverse("workspace:reviews"))
        self.assertEqual(link.status, EmailProjectLink.Status.CORRECTED)
        self.assertEqual(confirmed_link.status, EmailProjectLink.Status.CONFIRMED)

    def test_inbox_renders_confirm_action_for_suggested_link(self):
        self._suggested_link()

        response = self.client.get(reverse("workspace:inbox"))

        self.assertContains(response, "Confirm")
        self.assertContains(response, "Reject")
        self.assertContains(response, "Change project")

    def test_email_detail_renders_project_link_actions(self):
        link, other_project = self._suggested_link()

        response = self.client.get(reverse("workspace:inbox_detail", kwargs={"email_id": link.email_message_id}))

        self.assertContains(response, "matched_project_code")
        self.assertContains(response, "Confirm")
        self.assertContains(response, "Reject")
        self.assertContains(response, f"{other_project.code} {other_project.name}")

    def test_reviews_page_lists_pending_project_links(self):
        link, _other_project = self._suggested_link()

        response = self.client.get(reverse("workspace:reviews"))

        self.assertContains(response, "Pending Project Link Suggestions")
        self.assertContains(response, link.email_message.subject)
        self.assertContains(response, "Suggested Project")
        self.assertContains(response, "matched_project_code")

    def test_messages_are_created(self):
        link, _other_project = self._suggested_link()

        response = self.client.post(
            reverse("workspace:project_link_confirm", kwargs={"link_id": link.id}),
            {"next": reverse("workspace:reviews")},
            follow=True,
        )

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Project link confirmed" in message for message in messages))

    def test_invalid_project_id_handled_safely(self):
        link, _other_project = self._suggested_link()

        response = self.client.post(
            reverse("workspace:project_link_correct", kwargs={"link_id": link.id}),
            {"new_project_id": "999999", "next": reverse("workspace:reviews")},
            follow=True,
        )

        link.refresh_from_db()
        self.assertEqual(link.status, EmailProjectLink.Status.SUGGESTED)
        self.assertContains(response, "choose a valid project")

    def test_no_get_mutation(self):
        link, _other_project = self._suggested_link()

        self.client.get(reverse("workspace:project_link_confirm", kwargs={"link_id": link.id}))

        link.refresh_from_db()
        self.assertEqual(link.status, EmailProjectLink.Status.SUGGESTED)


class EmailReplyDraftUITests(TestCase):
    def _email_with_question(self):
        organization = create_organization()
        message = create_email_message(organization, subject="Reply draft email")
        question = EmailQuestion.objects.create(
            organization=organization,
            email_message=message,
            question_text="Can you confirm the schedule?",
            evidence={"keyword": "confirm"},
        )
        return message, question

    def _draft(self, status=EmailAnswerDraft.Status.DRAFT):
        message, question = self._email_with_question()
        draft = EmailAnswerDraft.objects.create(
            organization=message.organization,
            email_message=message,
            question=question,
            status=status,
            draft_text="Initial draft reply",
        )
        return draft

    def test_email_detail_shows_detected_questions(self):
        message, _question = self._email_with_question()

        response = self.client.get(reverse("workspace:inbox_detail", kwargs={"email_id": message.id}))

        self.assertContains(response, "Can you confirm the schedule?")
        self.assertContains(response, "Questions")

    def test_email_detail_shows_create_draft_form(self):
        message, _question = self._email_with_question()

        response = self.client.get(reverse("workspace:inbox_detail", kwargs={"email_id": message.id}))

        self.assertContains(response, "Create Draft Reply")
        self.assertContains(response, reverse("workspace:email_draft_create", kwargs={"email_id": message.id}))
        self.assertContains(response, 'name="draft_text"', html=False)

    def test_create_draft_endpoint_requires_post(self):
        message, _question = self._email_with_question()

        response = self.client.get(reverse("workspace:email_draft_create", kwargs={"email_id": message.id}))

        self.assertEqual(response.status_code, 405)

    def test_create_draft_creates_email_answer_draft(self):
        message, _question = self._email_with_question()

        response = self.client.post(
            reverse("workspace:email_draft_create", kwargs={"email_id": message.id}),
            {"draft_text": "Please find my reply below."},
            follow=True,
        )

        self.assertRedirects(response, reverse("workspace:inbox_detail", kwargs={"email_id": message.id}))
        draft = EmailAnswerDraft.objects.get(email_message=message)
        self.assertEqual(draft.draft_text, "Please find my reply below.")
        self.assertEqual(draft.generated_by, EmailAnswerDraft.GeneratedBy.RULE_BASED)

    def test_create_draft_includes_selected_question(self):
        message, question = self._email_with_question()

        self.client.post(
            reverse("workspace:email_draft_create", kwargs={"email_id": message.id}),
            {
                "question_id": question.id,
                "draft_text": "Question-specific reply.",
            },
        )

        draft = EmailAnswerDraft.objects.get(email_message=message)
        self.assertEqual(draft.question, question)

    def test_create_draft_stores_context_snapshot(self):
        message, question = self._email_with_question()
        project = create_project(message.organization, code="26400", name="Context Project")
        EmailProjectLink.objects.create(
            organization=message.organization,
            email_message=message,
            project=project,
            evidence={"matched_project_code": "26400"},
        )

        self.client.post(
            reverse("workspace:email_draft_create", kwargs={"email_id": message.id}),
            {"question_id": question.id, "draft_text": "Context-aware reply."},
        )

        draft = EmailAnswerDraft.objects.get(email_message=message)
        self.assertEqual(draft.context_snapshot["email_message_id"], message.id)
        self.assertEqual(draft.context_snapshot["question_ids"], [question.id])
        self.assertEqual(draft.context_snapshot["evidence_count"], 2)

    def test_needs_review_endpoint_requires_post(self):
        draft = self._draft()

        response = self.client.get(reverse("workspace:draft_needs_review", kwargs={"draft_id": draft.id}))

        self.assertEqual(response.status_code, 405)

    def test_approve_endpoint_requires_post(self):
        draft = self._draft()

        response = self.client.get(reverse("workspace:draft_approve", kwargs={"draft_id": draft.id}))

        self.assertEqual(response.status_code, 405)

    def test_reject_endpoint_requires_post(self):
        draft = self._draft()

        response = self.client.get(reverse("workspace:draft_reject", kwargs={"draft_id": draft.id}))

        self.assertEqual(response.status_code, 405)

    def test_needs_review_changes_status(self):
        draft = self._draft()

        response = self.client.post(
            reverse("workspace:draft_needs_review", kwargs={"draft_id": draft.id}),
            follow=True,
        )

        draft.refresh_from_db()
        self.assertRedirects(response, reverse("workspace:inbox_detail", kwargs={"email_id": draft.email_message_id}))
        self.assertEqual(draft.status, EmailAnswerDraft.Status.NEEDS_REVIEW)

    def test_approve_changes_status(self):
        draft = self._draft(status=EmailAnswerDraft.Status.NEEDS_REVIEW)

        response = self.client.post(
            reverse("workspace:draft_approve", kwargs={"draft_id": draft.id}),
            {"final_text": "Approved final reply"},
            follow=True,
        )

        draft.refresh_from_db()
        self.assertRedirects(response, reverse("workspace:inbox_detail", kwargs={"email_id": draft.email_message_id}))
        self.assertEqual(draft.status, EmailAnswerDraft.Status.APPROVED)
        self.assertEqual(draft.final_text, "Approved final reply")
        self.assertIsNotNone(draft.approved_at)

    def test_reject_changes_status(self):
        draft = self._draft(status=EmailAnswerDraft.Status.NEEDS_REVIEW)

        response = self.client.post(
            reverse("workspace:draft_reject", kwargs={"draft_id": draft.id}),
            {"reason": "Needs a better answer"},
            follow=True,
        )

        draft.refresh_from_db()
        self.assertRedirects(response, reverse("workspace:inbox_detail", kwargs={"email_id": draft.email_message_id}))
        self.assertEqual(draft.status, EmailAnswerDraft.Status.REJECTED)
        self.assertEqual(draft.metadata["rejection_reason"], "Needs a better answer")

    def test_reviews_page_lists_drafts_needing_review(self):
        draft = self._draft(status=EmailAnswerDraft.Status.NEEDS_REVIEW)

        response = self.client.get(reverse("workspace:reviews"))

        self.assertContains(response, "Answer Drafts Needing Review")
        self.assertContains(response, draft.email_message.subject)
        self.assertContains(response, "Initial draft reply")
        self.assertContains(response, reverse("workspace:draft_approve", kwargs={"draft_id": draft.id}))

    def test_no_get_mutation(self):
        draft = self._draft()

        self.client.get(reverse("workspace:draft_approve", kwargs={"draft_id": draft.id}))
        self.client.get(reverse("workspace:draft_reject", kwargs={"draft_id": draft.id}))
        self.client.get(reverse("workspace:draft_needs_review", kwargs={"draft_id": draft.id}))

        draft.refresh_from_db()
        self.assertEqual(draft.status, EmailAnswerDraft.Status.DRAFT)


class ManagementAllocationWorkspaceTests(TestCase):
    def setUp(self):
        self.organization = create_organization()
        self.integration = create_merit_integration(self.organization)
        self.pool = ManagementCostPool.objects.create(
            organization=self.organization,
            name="Office",
            default_strategy=AllocationStrategy.EQUAL,
        )
        self.first_project = create_project(self.organization, code="26124", name="First Project")
        self.second_project = create_project(self.organization, code="26125", name="Second Project")
        self.third_project = create_project(self.organization, code="26126", name="Third Project")

    def _classification(self, account_code, category, reporting_sign):
        return AccountingAccountClassification.objects.create(
            organization=self.organization,
            integration=self.integration,
            account_code=account_code,
            account_name=f"Account {account_code}",
            category=category,
            reporting_sign=Decimal(str(reporting_sign)),
        )

    def _financial_allocation(self, project, account_code, amount, *, batch_date="2026-06-15", suffix="1"):
        batch = AccountingGLBatch.objects.create(
            organization=self.organization,
            integration=self.integration,
            external_id=f"mgmt-preselect-batch-{project.code}-{account_code}-{suffix}",
            batch_date=timezone.datetime.fromisoformat(batch_date).date(),
            currency_code="EUR",
        )
        entry = AccountingGLEntry.objects.create(
            organization=self.organization,
            integration=self.integration,
            batch=batch,
            external_id=f"mgmt-preselect-entry-{project.code}-{account_code}-{suffix}",
            account_code=account_code,
            account_name=f"Account {account_code}",
        )
        return AccountingGLAllocation.objects.create(
            organization=self.organization,
            integration=self.integration,
            entry=entry,
            external_id=f"mgmt-preselect-allocation-{project.code}-{account_code}-{suffix}",
            dimension_code=project.code,
            dimension_name=project.name,
            amount=Decimal(str(amount)),
            project=project,
        )

    def _setup_financial_activity(self):
        self._classification("3000", AccountingAccountClassification.Category.REVENUE, "-1")
        self._classification("5000", AccountingAccountClassification.Category.MATERIAL_COST, "1")
        self._financial_allocation(self.first_project, "3000", "-300.000000", suffix="first-rev")
        self._financial_allocation(self.second_project, "3000", "50.000000", suffix="second-negative-rev")
        self._financial_allocation(self.third_project, "5000", "80.000000", suffix="third-cost")

    def _draft_version(self):
        period = ManagementAllocationPeriod.objects.create(organization=self.organization, year=2026, month=6)
        version = ManagementAllocationVersion.objects.create(
            period=period,
            pool=self.pool,
            version_number=1,
            metadata={
                "strategy": AllocationStrategy.EQUAL,
                "source_amount": "100.00",
                "source_amount_origin": "manual",
                "selected_project_ids": [self.first_project.id, self.second_project.id],
                "calculation_diagnostics": {"warnings": [], "source": {"mapped_account_codes": ["5000"]}},
            },
        )
        ManagementAllocationEntry.objects.create(
            version=version,
            project=self.first_project,
            percentage=Decimal("50.0000"),
            amount=Decimal("50.00"),
        )
        ManagementAllocationEntry.objects.create(
            version=version,
            project=self.second_project,
            percentage=Decimal("50.0000"),
            amount=Decimal("50.00"),
        )
        return version

    def test_list_route_returns_200_and_sidebar_link_rendered(self):
        response = self.client.get(reverse("workspace:management_allocations"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Management Allocations")

    def test_list_filters_and_summary_render(self):
        version = self._draft_version()

        response = self.client.get(
            reverse("workspace:management_allocations"),
            {"month": "2026-06", "pool": self.pool.id, "status": VersionStatus.DRAFT},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, version.pool.name)
        self.assertContains(response, "100,00 EUR")

    def test_create_page_returns_200_and_requires_explicit_project_selection(self):
        response = self.client.get(reverse("workspace:management_allocation_create"))
        post_response = self.client.post(
            reverse("workspace:management_allocation_create"),
            {
                "pool_id": self.pool.id,
                "month": "2026-06",
                "strategy": AllocationStrategy.EQUAL,
                "source_amount_mode": "manual",
                "source_amount": "100.00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.first_project.code)
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, "Choose at least one participating Project explicitly")

    def test_positive_revenue_project_selected_by_default_and_no_match_message(self):
        self._setup_financial_activity()

        response = self.client.get(reverse("workspace:management_allocation_create"), {"month": "2026-06"})
        empty_month = self.client.get(reverse("workspace:management_allocation_create"), {"month": "2026-07"})

        rows = {row["project"].code: row for row in response.context["projects"]}
        self.assertTrue(rows[self.first_project.code]["selected"])
        self.assertFalse(rows[self.second_project.code]["selected"])
        self.assertFalse(rows[self.third_project.code]["selected"])
        self.assertContains(empty_month, "No Projects with positive revenue were found for the selected month.")

    def test_recipient_preselection_criteria(self):
        self._setup_financial_activity()
        self.first_project.status = Project.Status.COMPLETED
        self.first_project.save(update_fields=["status"])
        self.second_project.status = Project.Status.ARCHIVED
        self.second_project.save(update_fields=["status"])

        none = self.client.get(
            reverse("workspace:management_allocation_create"),
            {"month": "2026-06", "recipient_preselection": "none"},
        )
        any_revenue = self.client.get(
            reverse("workspace:management_allocation_create"),
            {"month": "2026-06", "recipient_preselection": "any_revenue"},
        )
        financial_activity = self.client.get(
            reverse("workspace:management_allocation_create"),
            {"month": "2026-06", "recipient_preselection": "financial_activity"},
        )
        active_projects = self.client.get(
            reverse("workspace:management_allocation_create"),
            {"month": "2026-06", "recipient_preselection": "active_projects"},
        )

        self.assertFalse(any(row["selected"] for row in none.context["projects"]))
        self.assertEqual(
            {row["project"].code for row in any_revenue.context["projects"] if row["selected"]},
            {self.first_project.code, self.second_project.code},
        )
        self.assertEqual(
            {row["project"].code for row in financial_activity.context["projects"] if row["selected"]},
            {self.first_project.code, self.second_project.code, self.third_project.code},
        )
        self.assertEqual(
            {row["project"].code for row in active_projects.context["projects"] if row["selected"]},
            {self.third_project.code},
        )

    def test_source_project_excluded_from_preselection(self):
        self._setup_financial_activity()

        response = self.client.get(
            reverse("workspace:management_allocation_create"),
            {
                "month": "2026-06",
                "source_type": AllocationSourceType.WORKSPACE_PROJECT,
                "source_project_id": self.first_project.id,
            },
        )

        source_row = next(row for row in response.context["projects"] if row["project"] == self.first_project)
        self.assertFalse(source_row["selected"])
        self.assertTrue(source_row["is_source_project"])
        self.assertContains(response, "Source Project cannot receive its own redistributed cost.")

    def test_invalid_post_preserves_manual_project_selection(self):
        self._setup_financial_activity()

        response = self.client.post(
            reverse("workspace:management_allocation_create"),
            {
                "pool_id": "",
                "month": "2026-06",
                "strategy": AllocationStrategy.EQUAL,
                "recipient_preselection": "positive_revenue",
                "project_ids": [self.second_project.id],
            },
        )

        rows = {row["project"].code: row for row in response.context["projects"]}
        self.assertEqual(response.status_code, 200)
        self.assertFalse(rows[self.first_project.code]["selected"])
        self.assertTrue(rows[self.second_project.code]["selected"])
        self.assertFalse(rows[self.third_project.code]["selected"])

    def test_filters_sorting_get_read_only_and_no_merit_api(self):
        self._setup_financial_activity()
        counts = (
            ManagementAllocationVersion.objects.count(),
            ManagementAllocationEntry.objects.count(),
            Project.objects.count(),
            AccountingGLAllocation.objects.count(),
        )

        with patch.object(MeritAPIClient, "request") as request_mock:
            response = self.client.get(
                reverse("workspace:management_allocation_create"),
                {
                    "month": "2026-06",
                    "project_filter": "financial_activity",
                    "project_q": "Third",
                    "sort": "bad",
                },
            )

        request_mock.assert_not_called()
        self.assertEqual(counts, (
            ManagementAllocationVersion.objects.count(),
            ManagementAllocationEntry.objects.count(),
            Project.objects.count(),
            AccountingGLAllocation.objects.count(),
        ))
        self.assertEqual([row["project"].code for row in response.context["projects"]], [self.third_project.code])

    def test_default_sort_revenue_descending_and_status_filter(self):
        self._setup_financial_activity()
        self.third_project.status = Project.Status.PLANNED
        self.third_project.save(update_fields=["status"])

        default_response = self.client.get(reverse("workspace:management_allocation_create"), {"month": "2026-06"})
        status_response = self.client.get(
            reverse("workspace:management_allocation_create"),
            {"month": "2026-06", "project_status": Project.Status.PLANNED},
        )

        self.assertEqual(
            [row["project"].code for row in default_response.context["projects"]],
            [self.first_project.code, self.third_project.code, self.second_project.code],
        )
        self.assertEqual([row["project"].code for row in status_response.context["projects"]], [self.third_project.code])

    def test_explicit_submitted_project_ids_remain_authoritative(self):
        self._setup_financial_activity()

        response = self.client.post(
            reverse("workspace:management_allocation_create"),
            {
                "pool_id": self.pool.id,
                "month": "2026-06",
                "strategy": AllocationStrategy.EQUAL,
                "source_amount_mode": "manual",
                "source_amount": "100.00",
                "recipient_preselection": "positive_revenue",
                "suggested_project_ids": str(self.first_project.id),
                "project_ids": [self.second_project.id],
            },
        )

        version = ManagementAllocationVersion.objects.get()
        self.assertRedirects(response, reverse("workspace:management_allocation_detail", args=[version.id]))
        self.assertEqual(list(version.entries.values_list("project_id", flat=True)), [self.second_project.id])
        self.assertEqual(version.metadata["input_metadata"]["recipient_preselection_criterion"], "positive_revenue")
        self.assertEqual(version.metadata["input_metadata"]["suggested_project_ids"], [self.first_project.id])
        self.assertEqual(version.metadata["input_metadata"]["final_selected_project_ids"], [self.second_project.id])

    def test_valid_equal_proposal_generated_and_redirects_to_review(self):
        response = self.client.post(
            reverse("workspace:management_allocation_create"),
            {
                "pool_id": self.pool.id,
                "month": "2026-06",
                "strategy": AllocationStrategy.EQUAL,
                "source_amount_mode": "manual",
                "source_amount": "100.00",
                "project_ids": [self.first_project.id, self.second_project.id],
            },
        )

        version = ManagementAllocationVersion.objects.get()
        self.assertRedirects(response, reverse("workspace:management_allocation_detail", args=[version.id]))
        self.assertEqual(version.status, VersionStatus.DRAFT)
        self.assertEqual(version.entries.count(), 2)

    def test_workspace_project_source_preview_and_create_form_render(self):
        response = self.client.get(
            reverse("workspace:management_allocation_source_preview"),
            {
                "month": "2026-06",
                "source_type": AllocationSourceType.WORKSPACE_PROJECT,
                "source_project_id": self.first_project.id,
                "source_currency": "EUR",
            },
        )
        create_response = self.client.get(
            reverse("workspace:management_allocation_create"),
            {
                "month": "2026-06",
                "source_type": AllocationSourceType.WORKSPACE_PROJECT,
                "source_project_id": self.first_project.id,
                "source_currency": "EUR",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Allocation source preview")
        self.assertContains(response, self.first_project.code)
        self.assertContains(create_response, "Workspace Project source")
        self.assertContains(create_response, "Source Project cannot receive its own redistributed cost.")

    def test_workspace_project_source_create_rejects_source_as_target(self):
        response = self.client.post(
            reverse("workspace:management_allocation_create"),
            {
                "source_type": AllocationSourceType.WORKSPACE_PROJECT,
                "source_project_id": self.first_project.id,
                "month": "2026-06",
                "strategy": AllocationStrategy.EQUAL,
                "source_amount_basis": "project_direct_cost",
                "source_currency": "EUR",
                "project_ids": [self.first_project.id, self.second_project.id],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "source Project cannot also be selected")
        self.assertFalse(ManagementAllocationVersion.objects.exists())

    def test_create_calls_proposal_service_once_and_no_merit_api(self):
        with patch.object(ManagementAllocationProposalService, "generate", wraps=ManagementAllocationProposalService().generate) as generate_mock:
            with patch("apps.accounting.connectors.MeritAPIClient.request") as merit_mock:
                self.client.post(
                    reverse("workspace:management_allocation_create"),
                    {
                        "pool_id": self.pool.id,
                        "month": "2026-06",
                        "strategy": AllocationStrategy.EQUAL,
                        "source_amount_mode": "manual",
                        "source_amount": "100.00",
                        "project_ids": [self.first_project.id, self.second_project.id],
                    },
                )

        self.assertEqual(generate_mock.call_count, 1)
        merit_mock.assert_not_called()

    def test_wizard_navigation_preview_is_read_only_and_final_create_clears_state(self):
        create_url = reverse("workspace:management_allocation_create")

        first = self.client.post(
            create_url,
            {
                "_wizard_action": "continue",
                "source_type": AllocationSourceType.COST_POOL,
                "pool_id": self.pool.id,
            },
        )
        second = self.client.post(
            create_url,
            {
                "_wizard_action": "continue",
                "month": "2026-06",
                "source_amount_mode": "manual",
                "source_amount": "120.00",
                "source_currency": "EUR",
                "reason": "Monthly redistribution",
            },
        )
        preview_response = self.client.post(
            create_url,
            {
                "_wizard_action": "preview",
                "strategy": AllocationStrategy.EQUAL,
                "project_ids": [self.first_project.id, self.second_project.id],
                "suggested_project_ids": f"{self.first_project.id},{self.second_project.id}",
            },
        )

        self.assertRedirects(first, create_url)
        self.assertRedirects(second, create_url)
        self.assertRedirects(preview_response, create_url)
        self.assertFalse(ManagementAllocationVersion.objects.exists())
        self.assertFalse(ManagementAllocationEntry.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(event_type="management_allocation_proposal_generated").exists())
        preview_page = self.client.get(create_url)
        self.assertContains(preview_page, "Preview fresh")
        self.assertContains(preview_page, "60,00 EUR")

        with patch.object(ManagementAllocationProposalService, "generate", wraps=ManagementAllocationProposalService().generate) as generate_mock:
            final = self.client.post(create_url, {"_wizard_action": "create_draft"})

        version = ManagementAllocationVersion.objects.get()
        self.assertRedirects(final, reverse("workspace:management_allocation_detail", args=[version.id]))
        self.assertEqual(generate_mock.call_count, 1)
        self.assertEqual(list(version.entries.values_list("amount", flat=True)), [Decimal("60.000000"), Decimal("60.000000")])
        self.assertNotIn("management_allocation_wizard", self.client.session)

    def test_wizard_cannot_skip_required_steps_and_cancel_clears_state(self):
        create_url = reverse("workspace:management_allocation_create")

        skip = self.client.post(create_url, {"_wizard_action": "preview"})
        self.assertRedirects(skip, create_url)
        self.assertFalse(ManagementAllocationVersion.objects.exists())
        self.assertIn("management_allocation_wizard", self.client.session)

        cancel = self.client.post(create_url, {"_wizard_action": "cancel"})

        self.assertRedirects(cancel, reverse("workspace:management_allocations"))
        self.assertNotIn("management_allocation_wizard", self.client.session)
        self.assertFalse(ManagementAllocationVersion.objects.exists())

    def test_detail_route_shows_source_entries_totals_warnings_and_history(self):
        version = self._draft_version()

        response = self.client.get(reverse("workspace:management_allocation_detail", args=[version.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Source amount")
        self.assertContains(response, self.first_project.code)
        self.assertContains(response, "Totals")
        self.assertContains(response, "Version history")
        self.assertNotContains(response, "api-secret")

    def test_edit_draft_percentages_authoritative(self):
        version = self._draft_version()

        response = self.client.post(
            reverse("workspace:management_allocation_edit", args=[version.id]),
            {
                "edit_mode": "percentages_authoritative",
                "project_ids": [self.first_project.id, self.second_project.id],
                f"percentage_{self.first_project.id}": "60",
                f"percentage_{self.second_project.id}": "40",
                f"amount_{self.first_project.id}": "0",
                f"amount_{self.second_project.id}": "0",
                f"manual_override_{self.first_project.id}": "on",
                "reason": "Reviewed split",
            },
        )

        self.assertRedirects(response, reverse("workspace:management_allocation_detail", args=[version.id]))
        amounts = list(version.entries.order_by("project__code").values_list("amount", flat=True))
        self.assertEqual(amounts, [Decimal("60.000000"), Decimal("40.000000")])
        self.assertEqual(AuditEvent.objects.filter(event_type="management_allocation_draft_edited").count(), 1)

    def test_edit_rejects_approved_version(self):
        version = self._draft_version()
        ManagementAllocationVersionService.approve(ApproveManagementAllocationVersionCommand(version=version))

        response = self.client.post(
            reverse("workspace:management_allocation_edit", args=[version.id]),
            {
                "edit_mode": "percentages_authoritative",
                "project_ids": [self.first_project.id],
                f"percentage_{self.first_project.id}": "100",
                f"amount_{self.first_project.id}": "100",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Only draft management allocation versions can be edited")

    def test_approval_post_only_and_supersedes_prior(self):
        first = self._draft_version()
        ManagementAllocationVersionService.approve(ApproveManagementAllocationVersionCommand(version=first))
        second = ManagementAllocationVersion.objects.create(
            period=first.period,
            pool=self.pool,
            version_number=2,
            metadata=first.metadata,
        )
        ManagementAllocationEntry.objects.create(
            version=second,
            project=self.first_project,
            percentage=Decimal("100.0000"),
            amount=Decimal("100.00"),
        )

        get_response = self.client.get(reverse("workspace:management_allocation_approve", args=[second.id]))
        post_response = self.client.post(reverse("workspace:management_allocation_approve", args=[second.id]))
        first.refresh_from_db()
        second.refresh_from_db()

        self.assertEqual(get_response.status_code, 405)
        self.assertRedirects(post_response, reverse("workspace:management_allocation_detail", args=[second.id]))
        self.assertEqual(second.status, VersionStatus.APPROVED)
        self.assertEqual(first.status, VersionStatus.SUPERSEDED)
        self.assertEqual(
            ManagementAllocationVersion.objects.filter(period=first.period, pool=self.pool, status=VersionStatus.APPROVED).count(),
            1,
        )

    def test_revision_creates_new_draft_and_keeps_old_version(self):
        version = self._draft_version()
        ManagementAllocationVersionService.approve(ApproveManagementAllocationVersionCommand(version=version))

        response = self.client.post(reverse("workspace:management_allocation_revise", args=[version.id]), {"reason": "Correction"})
        revision = ManagementAllocationVersion.objects.order_by("-version_number").first()
        version.refresh_from_db()

        self.assertRedirects(response, reverse("workspace:management_allocation_edit", args=[revision.id]))
        self.assertEqual(revision.status, VersionStatus.DRAFT)
        self.assertEqual(revision.entries.count(), version.entries.count())
        self.assertEqual(version.status, VersionStatus.APPROVED)
        self.assertEqual(revision.metadata["revision_source_version_id"], version.id)

    def test_financial_boundary_project_financials_unchanged(self):
        version = self._draft_version()
        before = ProjectFinancialAggregationService().aggregate(
            AggregateProjectFinancialsCommand(
                project=self.first_project,
                period_start=timezone.datetime(2026, 6, 1).date(),
                period_end=timezone.datetime(2026, 6, 30).date(),
            )
        )
        ManagementAllocationVersionService.approve(ApproveManagementAllocationVersionCommand(version=version))
        after = ProjectFinancialAggregationService().aggregate(
            AggregateProjectFinancialsCommand(
                project=self.first_project,
                period_start=timezone.datetime(2026, 6, 1).date(),
                period_end=timezone.datetime(2026, 6, 30).date(),
            )
        )

        self.assertEqual(before.revenue, after.revenue)
        self.assertEqual(before.total_cost, after.total_cost)


class FinancialAlertWorkspaceUITests(TestCase):
    def setUp(self):
        self.organization = create_organization()
        self.project = create_project(self.organization, code="26900", name="Alert Project")
        self.alert = create_financial_alert(self.project)

    def test_alert_list_returns_200_and_shows_active_alert(self):
        FinancialAlertEvaluationRun.objects.create(
            organization=self.organization,
            status=FinancialAlertEvaluationRunStatus.COMPLETED,
            evaluation_date=timezone.datetime(2026, 6, 30).date(),
            opened_count=1,
        )

        with patch("apps.accounting.connectors.MeritAPIClient.request") as request_mock:
            response = self.client.get(reverse("workspace:financial_alerts"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Financial Alerts")
        self.assertContains(response, self.alert.title)
        self.assertContains(response, "Latest evaluation run")
        request_mock.assert_not_called()

    def test_alert_list_filters_by_status_and_search(self):
        dismissed = create_financial_alert(
            self.project,
            status=FinancialAlertStatus.DISMISSED,
            fingerprint="dismissed-alert",
            title="Dismissed old alert",
        )

        response = self.client.get(reverse("workspace:financial_alerts"), {"status": "dismissed", "q": "old"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, dismissed.title)
        self.assertNotContains(response, self.alert.title)

    def test_margin_alert_list_displays_percentage_and_filter_choice(self):
        margin_alert = create_financial_alert(
            self.project,
            alert_type=FinancialAlertType.PROJECT_MARGIN_BELOW_THRESHOLD,
            fingerprint="margin-alert",
            title="Project margin below threshold",
            currency="%",
            accounting_amount=Decimal("11.80"),
            management_amount=Decimal("8.40"),
            evaluated_amount=Decimal("8.40"),
            threshold_amount=Decimal("10.00"),
            metadata={"threshold_percentage": "10.00", "evaluated_margin": "8.40"},
        )

        response = self.client.get(
            reverse("workspace:financial_alerts"),
            {"alert_type": FinancialAlertType.PROJECT_MARGIN_BELOW_THRESHOLD},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, margin_alert.title)
        self.assertContains(response, "8.40%")
        self.assertContains(response, "10.00%")
        self.assertContains(response, "Project margin below threshold")

    def test_project_alert_route_is_project_scoped(self):
        other_project = create_project(self.organization, code="26901", name="Other Project")
        other_alert = create_financial_alert(other_project, fingerprint="other-alert", title="Other project alert")

        response = self.client.get(reverse("workspace:project_alerts", args=[self.project.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.alert.title)
        self.assertNotContains(response, other_alert.title)

    def test_alert_detail_shows_safe_metadata_without_secret(self):
        response = self.client.get(reverse("workspace:financial_alert_detail", args=[self.alert.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Safe Diagnostics")
        self.assertContains(response, "review result")
        self.assertNotContains(response, "never-render")
        self.assertNotContains(response, "api_secret")
        self.assertNotContains(response, "signature")

    def test_acknowledge_requires_post_and_creates_audit_event(self):
        get_response = self.client.get(reverse("workspace:financial_alert_acknowledge", args=[self.alert.id]))
        post_response = self.client.post(reverse("workspace:financial_alert_acknowledge", args=[self.alert.id]))
        self.alert.refresh_from_db()

        self.assertEqual(get_response.status_code, 405)
        self.assertRedirects(post_response, reverse("workspace:financial_alert_detail", args=[self.alert.id]))
        self.assertEqual(self.alert.status, FinancialAlertStatus.ACKNOWLEDGED)
        self.assertIsNotNone(self.alert.acknowledged_at)
        self.assertTrue(AuditEvent.objects.filter(event_type="financial_alert_acknowledged").exists())

    def test_dismiss_requires_post_reason_and_creates_audit_event(self):
        missing_reason = self.client.post(reverse("workspace:financial_alert_dismiss", args=[self.alert.id]), {"reason": ""})
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, FinancialAlertStatus.OPEN)
        self.assertRedirects(missing_reason, reverse("workspace:financial_alert_detail", args=[self.alert.id]))

        response = self.client.post(reverse("workspace:financial_alert_dismiss", args=[self.alert.id]), {"reason": "Reviewed"})
        self.alert.refresh_from_db()

        self.assertRedirects(response, reverse("workspace:financial_alert_detail", args=[self.alert.id]))
        self.assertEqual(self.alert.status, FinancialAlertStatus.DISMISSED)
        self.assertEqual(self.alert.resolution_reason, "Reviewed")
        self.assertTrue(AuditEvent.objects.filter(event_type="financial_alert_dismissed").exists())

    def test_project_workspace_shows_alert_summary(self):
        response = self.client.get(reverse("workspace:project_detail", args=[self.project.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Financial Alerts")
        self.assertContains(response, "Active alerts")
        self.assertContains(response, self.alert.title)

    def test_project_financials_banner_includes_lifetime_and_month_alerts(self):
        month_alert = create_financial_alert(
            self.project,
            alert_type=FinancialAlertType.PROJECT_CURRENT_MONTH_NEGATIVE,
            fingerprint="month-alert",
            title="June month alert",
            period_start=timezone.datetime(2026, 6, 1).date(),
            period_end=timezone.datetime(2026, 6, 30).date(),
        )
        resolved_alert = create_financial_alert(
            self.project,
            alert_type=FinancialAlertType.PROJECT_CURRENT_MONTH_NEGATIVE,
            fingerprint="resolved-month-alert",
            title="Resolved month alert",
            period_start=timezone.datetime(2026, 6, 1).date(),
            period_end=timezone.datetime(2026, 6, 30).date(),
            status=FinancialAlertStatus.RESOLVED,
        )

        response = self.client.get(
            reverse("workspace:project_financials", args=[self.project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Financial alerts for this view")
        self.assertContains(response, self.alert.title)
        self.assertContains(response, month_alert.title)
        self.assertNotContains(response, resolved_alert.title)

    def test_project_financials_banner_shows_margin_required_copy(self):
        margin_alert = create_financial_alert(
            self.project,
            alert_type=FinancialAlertType.PROJECT_MARGIN_BELOW_THRESHOLD,
            fingerprint="project-margin-banner",
            title="Project margin below threshold",
            period_start=timezone.datetime(2026, 6, 1).date(),
            period_end=timezone.datetime(2026, 6, 30).date(),
            currency="%",
            evaluated_amount=Decimal("8.40"),
            threshold_amount=Decimal("10.00"),
        )

        response = self.client.get(
            reverse("workspace:project_financials", args=[self.project.id]),
            {"period": "custom", "start": "2026-06-01", "end": "2026-06-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, margin_alert.title)
        self.assertContains(response, "Margin 8.40%")
        self.assertContains(response, "Required 10.00%")

    def test_financial_dashboard_shows_project_alert_count(self):
        response = self.client.get(reverse("workspace:financial_dashboard"), {"show_no_data": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 active")

    def test_alert_read_pages_do_not_evaluate_alerts(self):
        with patch("apps.accounting.services.financial_alerts.FinancialAlertEvaluationService.evaluate") as evaluate_mock:
            response = self.client.get(reverse("workspace:financial_alert_detail", args=[self.alert.id]))

        self.assertEqual(response.status_code, 200)
        evaluate_mock.assert_not_called()

    def test_financial_alert_rule_settings_page_and_edit(self):
        rule = FinancialAlertRule.objects.create(
            organization=self.organization,
            alert_type=FinancialAlertType.PROJECT_MARGIN_BELOW_THRESHOLD,
            name="Project margin below threshold",
            financial_basis=FinancialAlertBasis.MANAGEMENT,
            severity=FinancialAlertSeverity.WARNING,
            threshold_percentage=Decimal("10.00"),
        )

        response = self.client.get(reverse("workspace:settings_financial_alert_rules"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Financial Alert Rules")
        self.assertContains(response, "Project margin below threshold")
        self.assertContains(response, "10.00%")

        edit_response = self.client.get(reverse("workspace:settings_financial_alert_rule_edit", args=[rule.id]))
        self.assertEqual(edit_response.status_code, 200)
        self.assertContains(edit_response, "Margin threshold help")

        post_response = self.client.post(
            reverse("workspace:settings_financial_alert_rule_edit", args=[rule.id]),
            {
                "name": "Margin warning",
                "is_active": "on",
                "financial_basis": FinancialAlertBasis.ACCOUNTING,
                "severity": FinancialAlertSeverity.CRITICAL,
                "threshold_amount": "",
                "threshold_percentage": "15.00",
                "grace_day": "5",
                "candidate_scope": "active_projects_with_month_activity",
                "configuration_text": '{"owner": "finance"}',
            },
        )
        rule.refresh_from_db()
        self.assertRedirects(post_response, reverse("workspace:settings_financial_alert_rules"))
        self.assertEqual(rule.name, "Margin warning")
        self.assertEqual(rule.financial_basis, FinancialAlertBasis.ACCOUNTING)
        self.assertEqual(rule.threshold_percentage, Decimal("15.00"))
        self.assertEqual(rule.configuration, {"owner": "finance"})
        self.assertTrue(AuditEvent.objects.filter(event_type="financial_alert_rule_updated").exists())

    def test_financial_alert_rule_settings_validation_and_reevaluate_post_only(self):
        rule = FinancialAlertRule.objects.create(
            organization=self.organization,
            alert_type=FinancialAlertType.PROJECT_MARGIN_BELOW_THRESHOLD,
            name="Project margin below threshold",
            threshold_percentage=Decimal("10.00"),
        )
        invalid = self.client.post(
            reverse("workspace:settings_financial_alert_rule_edit", args=[rule.id]),
            {
                "name": "Bad margin",
                "is_active": "on",
                "financial_basis": FinancialAlertBasis.MANAGEMENT,
                "severity": FinancialAlertSeverity.WARNING,
                "threshold_amount": "",
                "threshold_percentage": "101",
                "grace_day": "",
                "candidate_scope": "active_projects_with_month_activity",
                "configuration_text": "{}",
            },
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, "Percentage must be between 0 and 100")

        get_response = self.client.get(reverse("workspace:settings_financial_alert_rules_evaluate"))
        self.assertEqual(get_response.status_code, 405)

        result = SimpleNamespace(
            evaluated_projects=2,
            evaluated_rules=1,
            opened_count=1,
            updated_count=2,
            reopened_count=0,
            resolved_count=1,
            unchanged_count=3,
            failed_count=0,
        )
        with patch("apps.workspace.views.FinancialAlertEvaluationService.evaluate", return_value=result) as evaluate_mock:
            post_response = self.client.post(reverse("workspace:settings_financial_alert_rules_evaluate"))

        self.assertRedirects(post_response, reverse("workspace:settings_financial_alert_rules"))
        evaluate_mock.assert_called_once()
