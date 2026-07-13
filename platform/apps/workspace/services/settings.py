from decimal import Decimal

from django.db.models import Count, Max, Min, Sum

from apps.accounting.models import (
    AccountingAccountClassification,
    AccountingDimension,
    AccountingGLAllocation,
    AccountingGLEntry,
    AccountingIntegration,
)
from apps.accounting.secrets import SecretProvider
from apps.accounting.services import AccountClassificationService, ProjectCodeAllocationService, SuggestNextProjectCodeCommand
from apps.communications.models import EmailAccount
from apps.core.models import AuditEvent, Organization
from apps.documents.models import Document
from apps.projects.models import Project


class SettingsContextBuilder:
    """Read-only context builder for the Platform Settings Workspace."""

    @staticmethod
    def build():
        organization = Organization.objects.order_by("id").first()
        project_dimensions = AccountingDimension.objects.filter(
            dimension_type=AccountingDimension.DimensionType.PROJECT,
            is_active=True,
        )
        if organization:
            project_dimensions = project_dimensions.filter(organization=organization)

        merit_integration = AccountingIntegration.objects.filter(
            provider=AccountingIntegration.Provider.MERIT,
            is_active=True,
        ).order_by("id").first()

        return {
            "organization": organization,
            "summary_cards": SettingsContextBuilder._summary_cards(),
            "settings_cards": SettingsContextBuilder._settings_cards(),
            "email_accounts": EmailAccount.objects.select_related("organization").order_by("display_name", "id"),
            "accounting_integrations": AccountingIntegration.objects.select_related("organization").order_by(
                "display_name",
                "id",
            ),
            "merit": SettingsContextBuilder._merit_context(merit_integration, project_dimensions),
            "project_numbering": SettingsContextBuilder._project_numbering_context(organization, project_dimensions),
            "system_health_cards": SettingsContextBuilder._system_health_cards(merit_integration),
        }

    @staticmethod
    def _summary_cards():
        return [
            {"title": "Organizations", "count": Organization.objects.count(), "status": "info"},
            {"title": "Email Accounts", "count": EmailAccount.objects.count(), "status": "info"},
            {
                "title": "Accounting Integrations",
                "count": AccountingIntegration.objects.count(),
                "status": "info",
            },
            {"title": "Projects", "count": Project.objects.count(), "status": "info"},
            {
                "title": "Accounting Dimensions",
                "count": AccountingDimension.objects.count(),
                "status": "info",
            },
            {"title": "Recent Audit Events", "count": AuditEvent.objects.count(), "status": "neutral"},
        ]

    @staticmethod
    def _settings_cards():
        return [
            {"slug": "general", "title": "General", "body": "Workspace defaults, locale and operating preferences.", "status": "ready"},
            {"slug": "organizations", "title": "Organizations", "body": "Tenant identity, legal details and default context.", "status": "ready"},
            {"slug": "email-accounts", "title": "Email Accounts", "body": "Mailbox providers, sync status and connection tests.", "status": "ready"},
            {"slug": "accounting", "title": "Accounting", "body": "Accounting providers, sync health and integration state.", "status": "ready"},
            {"slug": "merit", "title": "Merit", "body": "Merit API, project dimension id and dimension cache.", "status": "ready"},
            {
                "slug": "account-classifications",
                "title": "Financial Account Mapping",
                "body": "Map imported GL account codes into project financial reporting categories.",
                "status": "ready",
            },
            {"slug": "project-numbering", "title": "Project Numbering", "body": "Suggested project codes and collision awareness.", "status": "ready"},
            {"slug": "knowledge", "title": "Knowledge", "body": "Future memory, evidence and AI context configuration.", "status": "planned"},
            {"slug": "documents", "title": "Documents", "body": "Future storage, OCR and document workflow settings.", "status": "planned"},
            {
                "slug": "dropbox",
                "title": "Dropbox (Coming Soon)",
                "body": "Future project folder and file storage integration.",
                "status": "coming_soon",
            },
            {"slug": "users-roles", "title": "Users & Roles", "body": "Future role-based access and user administration.", "status": "planned"},
            {"slug": "security", "title": "Security", "body": "Future authentication, secrets and sensitive action rules.", "status": "planned"},
            {"slug": "audit", "title": "Audit", "body": "Traceable sensitive settings and platform actions.", "status": "ready"},
            {"slug": "system-health", "title": "System Health", "body": "Operational status for sync, storage and providers.", "status": "ready"},
        ]

    @staticmethod
    def _merit_context(integration, project_dimensions):
        project_dimension_id = (integration.metadata or {}).get("project_dimension_id") if integration else ""
        last_synced_dimension = project_dimensions.order_by("-last_synced_at", "-updated_at").first()
        return {
            "integration": integration,
            "project_dimension_id": project_dimension_id,
            "project_dimension_configured": bool(project_dimension_id),
            "dimension_cache_count": project_dimensions.count(),
            "last_sync_at": integration.last_sync_at if integration else None,
            "last_dimension_sync_at": last_synced_dimension.last_synced_at if last_synced_dimension else None,
            "last_error": "",
        }

    @staticmethod
    def _project_numbering_context(organization, project_dimensions):
        project_codes = []
        if organization:
            project_codes = [
                int(project.code)
                for project in Project.objects.filter(organization=organization)
                if project.code.isdigit()
            ]
        highest_project_code = max(project_codes) if project_codes else None
        suggestion = None
        if organization:
            suggestion = ProjectCodeAllocationService.suggest_next_code(
                SuggestNextProjectCodeCommand(
                    organization=organization,
                    metadata={"source": "workspace_settings"},
                )
            )

        return {
            "highest_project_code": highest_project_code,
            "next_suggested_code": suggestion.suggested_code if suggestion else "",
            "cached_project_dimensions": project_dimensions.count(),
            "source_summary": suggestion.source_summary if suggestion else {},
        }

    @staticmethod
    def _system_health_cards(merit_integration):
        email_accounts = EmailAccount.objects.all()
        active_email_accounts = email_accounts.filter(is_active=True)
        accounting_integrations = AccountingIntegration.objects.all()
        active_accounting_integrations = accounting_integrations.filter(is_active=True)

        return [
            {
                "title": "Email",
                "status": "healthy" if active_email_accounts.exists() else "warning",
                "body": f"{active_email_accounts.count()} active of {email_accounts.count()} configured accounts.",
            },
            {
                "title": "Accounting",
                "status": "healthy" if active_accounting_integrations.exists() else "warning",
                "body": f"{active_accounting_integrations.count()} active of {accounting_integrations.count()} integrations.",
            },
            {
                "title": "Knowledge",
                "status": "unknown",
                "body": "Knowledge builders are available; health checks will be added later.",
            },
            {
                "title": "Database",
                "status": "healthy",
                "body": "Database is reachable because this page loaded successfully.",
            },
            {
                "title": "Storage",
                "status": "healthy" if Document.objects.exists() else "unknown",
                "body": f"{Document.objects.count()} stored documents tracked.",
            },
        ]


class EmailAccountSettingsContextBuilder:
    """Read-only context builder for e-mail account settings pages."""

    @staticmethod
    def build_list():
        return {
            "email_accounts": EmailAccount.objects.select_related("organization").order_by("display_name", "id"),
        }

    @staticmethod
    def build_detail(email_account):
        return {
            "email_account": email_account,
            "masked_secret": EmailAccountSettingsContextBuilder.mask_secret(
                email_account.encrypted_secret_placeholder
            ),
        }

    @staticmethod
    def mask_secret(value):
        if not value:
            return ""
        if len(value) <= 4:
            return "****"
        return f"{value[:2]}****{value[-2:]}"


class AccountingIntegrationSettingsContextBuilder:
    """Read-only context builder for accounting integration settings pages."""

    @staticmethod
    def build_list():
        return {
            "integrations": AccountingIntegration.objects.select_related("organization").order_by("display_name", "id"),
        }

    @staticmethod
    def build_detail(integration):
        return {
            "integration": integration,
            "project_dimension_id": (integration.metadata or {}).get("project_dimension_id", ""),
            "masked_secret": AccountingIntegrationSettingsContextBuilder.mask_secret(
                integration.encrypted_secret_placeholder
            ),
        }

    @staticmethod
    def mask_secret(value):
        return SecretProvider.mask_secret(value)


class GLAccountClassificationContextBuilder:
    """Read-only builder for imported GL account classification settings."""

    COST_CATEGORIES = {
        AccountingAccountClassification.Category.MATERIAL_COST,
        AccountingAccountClassification.Category.SUBCONTRACTOR_COST,
        AccountingAccountClassification.Category.LABOR_COST,
        AccountingAccountClassification.Category.EQUIPMENT_COST,
        AccountingAccountClassification.Category.TRANSPORT_COST,
        AccountingAccountClassification.Category.OTHER_DIRECT_COST,
    }
    FINANCIAL_CATEGORIES = {
        AccountingAccountClassification.Category.FINANCIAL_INCOME,
        AccountingAccountClassification.Category.FINANCIAL_COST,
        AccountingAccountClassification.Category.DEPRECIATION,
        AccountingAccountClassification.Category.TAX,
    }
    SORT_FIELDS = {
        "account_code": "account_code",
        "account_name": "account_name",
        "entry_count": "entry_count",
        "project_allocation_count": "project_allocation_count",
        "debit": "debit_total",
        "credit": "credit_total",
        "allocation_amount": "project_allocation_total",
        "category": "category",
    }

    @classmethod
    def build_list(cls, *, filter_value="all", query="", sort="account_code", integration_id=None):
        organization = Organization.objects.order_by("id").first()
        integrations = cls._integrations(organization)
        integration = cls._selected_integration(organization, integrations, integration_id)
        rows = cls._account_rows(organization, integration)
        rows = cls._apply_search(rows, query)
        rows = cls._apply_filter(rows, filter_value)
        rows = cls._sort_rows(rows, sort)

        return {
            "organization": organization,
            "integrations": integrations,
            "selected_integration": integration,
            "accounts": rows,
            "summary": cls._summary(rows),
            "filter_value": filter_value,
            "query": query,
            "sort": sort,
            "filter_options": cls._filter_options(),
            "sort_options": cls.SORT_FIELDS.keys(),
        }

    @classmethod
    def build_detail(cls, *, account_code, integration_id=None):
        organization = Organization.objects.order_by("id").first()
        integrations = cls._integrations(organization)
        integration = cls._selected_integration(organization, integrations, integration_id)
        rows = cls._account_rows(organization, integration)
        account = next((row for row in rows if row["account_code"] == account_code), None)
        if not account:
            return {
                "organization": organization,
                "integrations": integrations,
                "selected_integration": integration,
                "account": None,
                "recent_entries": [],
                "allocation_samples": [],
            }

        entries = (
            AccountingGLEntry.objects.filter(
                organization=organization,
                integration=integration,
                account_code=account_code,
            )
            .select_related("batch")
            .order_by("-batch__batch_date", "-id")[:10]
        )
        allocations = (
            AccountingGLAllocation.objects.filter(
                organization=organization,
                integration=integration,
                entry__account_code=account_code,
            )
            .select_related("entry__batch", "project")
            .order_by("-entry__batch__batch_date", "-id")[:10]
        )
        return {
            "organization": organization,
            "integrations": integrations,
            "selected_integration": integration,
            "account": account,
            "recent_entries": entries,
            "allocation_samples": allocations,
        }

    @classmethod
    def _integrations(cls, organization):
        if not organization:
            return AccountingIntegration.objects.none()
        return AccountingIntegration.objects.filter(organization=organization).order_by("-is_active", "display_name", "id")

    @classmethod
    def _selected_integration(cls, organization, integrations, integration_id):
        if not organization:
            return None
        if integration_id:
            selected = integrations.filter(id=integration_id).first()
            if selected:
                return selected
        return integrations.filter(provider=AccountingIntegration.Provider.MERIT, is_active=True).first() or integrations.first()

    @classmethod
    def _account_rows(cls, organization, integration):
        if not organization or not integration:
            return []

        accounts = list(
            AccountingGLEntry.objects.filter(organization=organization, integration=integration)
            .values("account_code")
            .annotate(
                account_name=Max("account_name"),
                entry_count=Count("id"),
                debit_total=Sum("debit_amount"),
                credit_total=Sum("credit_amount"),
                first_batch_date=Min("batch__batch_date"),
                last_batch_date=Max("batch__batch_date"),
            )
            .order_by("account_code")
        )
        account_codes = [account["account_code"] for account in accounts]
        allocation_stats = {
            item["entry__account_code"]: item
            for item in AccountingGLAllocation.objects.filter(
                organization=organization,
                integration=integration,
                entry__account_code__in=account_codes,
                project__isnull=False,
            )
            .values("entry__account_code")
            .annotate(
                project_allocation_count=Count("id"),
                project_allocation_total=Sum("amount"),
            )
        }
        currencies = {
            item["account_code"]: sorted(
                currency for currency in item["currencies"].split("|") if currency
            )
            for item in cls._currency_rows(organization, integration, account_codes)
        }
        direct_mappings = {
            classification.account_code: classification
            for classification in AccountingAccountClassification.objects.filter(
                organization=organization,
                integration=integration,
                account_code__in=account_codes,
            )
        }
        cache = AccountClassificationService.preload(organization, [integration])

        rows = []
        for account in accounts:
            account_code = account["account_code"]
            classification = AccountClassificationService.lookup_from_cache(cache, integration, account_code)
            direct_mapping = direct_mappings.get(account_code)
            allocation = allocation_stats.get(account_code, {})
            category = classification["category"]
            rows.append(
                {
                    "account_code": account_code,
                    "account_name": account["account_name"] or "",
                    "entry_count": account["entry_count"] or 0,
                    "debit_total": account["debit_total"] or Decimal("0"),
                    "credit_total": account["credit_total"] or Decimal("0"),
                    "project_allocation_count": allocation.get("project_allocation_count", 0),
                    "project_allocation_total": allocation.get("project_allocation_total") or Decimal("0"),
                    "first_batch_date": account["first_batch_date"],
                    "last_batch_date": account["last_batch_date"],
                    "category": category,
                    "reporting_sign": classification["reporting_sign"],
                    "include_in_project_result": classification["include_in_project_result"],
                    "is_active": bool(classification["classification"]),
                    "classification": classification["classification"],
                    "direct_mapping": direct_mapping,
                    "source": cls._source_label(classification["classification"]),
                    "status": cls._status(category, classification["classification"], direct_mapping),
                    "currencies": currencies.get(account_code, []),
                    "currency_diagnostic": cls._currency_diagnostic(currencies.get(account_code, [])),
                }
            )
        return rows

    @classmethod
    def _currency_rows(cls, organization, integration, account_codes):
        rows = []
        for account_code in account_codes:
            currencies = (
                AccountingGLEntry.objects.filter(
                    organization=organization,
                    integration=integration,
                    account_code=account_code,
                )
                .values_list("batch__currency_code", flat=True)
                .distinct()
            )
            rows.append(
                {
                    "account_code": account_code,
                    "currencies": "|".join(cls._normalize_currencies(currencies)),
                }
            )
        return rows

    @staticmethod
    def _normalize_currencies(currencies):
        return sorted(
            {
                str(currency).strip().upper()
                for currency in currencies
                if currency is not None and str(currency).strip()
            }
        )

    @staticmethod
    def _currency_diagnostic(currencies):
        if not currencies:
            return {"label": "Currency unknown", "status": "neutral", "is_mixed": False}
        if len(currencies) == 1:
            return {"label": f"Currency: {currencies[0]}", "status": "info", "is_mixed": False}
        return {"label": f"Mixed currencies: {', '.join(currencies)}", "status": "needs_review", "is_mixed": True}

    @staticmethod
    def _source_label(classification):
        if not classification:
            return "no mapping"
        if classification.integration_id:
            return "integration-specific"
        return "organization fallback"

    @staticmethod
    def _status(category, classification, direct_mapping):
        if direct_mapping and not direct_mapping.is_active:
            return "inactive"
        if category == AccountingAccountClassification.Category.EXCLUDED:
            return "excluded"
        if not classification or category == AccountingAccountClassification.Category.UNCLASSIFIED:
            return "unclassified"
        return "classified"

    @classmethod
    def _apply_search(cls, rows, query):
        if not query:
            return rows
        needle = query.lower()
        return [
            row
            for row in rows
            if needle in row["account_code"].lower() or needle in row["account_name"].lower()
        ]

    @classmethod
    def _apply_filter(cls, rows, filter_value):
        if filter_value == "unclassified":
            return [row for row in rows if row["status"] == "unclassified"]
        if filter_value == "classified":
            return [row for row in rows if row["status"] == "classified"]
        if filter_value == "excluded":
            return [row for row in rows if row["status"] == "excluded"]
        if filter_value == "active":
            return [row for row in rows if row["is_active"]]
        if filter_value == "inactive":
            return [row for row in rows if row["status"] == "inactive"]
        if filter_value == "has_project_allocations":
            return [row for row in rows if row["project_allocation_count"]]
        if filter_value == "no_project_allocations":
            return [row for row in rows if not row["project_allocation_count"]]
        if filter_value == "revenue":
            return [row for row in rows if row["category"] == AccountingAccountClassification.Category.REVENUE]
        if filter_value == "costs":
            return [row for row in rows if row["category"] in cls.COST_CATEGORIES]
        if filter_value == "overhead":
            return [row for row in rows if row["category"] == AccountingAccountClassification.Category.OVERHEAD]
        if filter_value == "financial":
            return [row for row in rows if row["category"] in cls.FINANCIAL_CATEGORIES]
        if filter_value == "balance_sheet_unmapped":
            return [row for row in rows if row["status"] == "unclassified"]
        return rows

    @classmethod
    def _sort_rows(cls, rows, sort):
        key = cls.SORT_FIELDS.get(sort, "account_code")
        return sorted(rows, key=lambda row: (row[key] is None, row[key]))

    @staticmethod
    def _summary(rows):
        return {
            "imported_accounts": len(rows),
            "classified_accounts": sum(1 for row in rows if row["status"] == "classified"),
            "unclassified_accounts": sum(1 for row in rows if row["status"] == "unclassified"),
            "accounts_with_project_allocations": sum(1 for row in rows if row["project_allocation_count"]),
            "unclassified_project_allocation_amount": sum(
                (row["project_allocation_total"] for row in rows if row["status"] == "unclassified"),
                Decimal("0"),
            ),
            "excluded_accounts": sum(1 for row in rows if row["status"] == "excluded"),
        }

    @staticmethod
    def _filter_options():
        return [
            ("all", "All"),
            ("unclassified", "Unclassified"),
            ("classified", "Classified"),
            ("excluded", "Excluded"),
            ("active", "Active mappings"),
            ("inactive", "Inactive mappings"),
            ("has_project_allocations", "Has project allocations"),
            ("no_project_allocations", "No project allocations"),
            ("revenue", "Revenue"),
            ("costs", "Costs"),
            ("overhead", "Overhead"),
            ("financial", "Financial"),
            ("balance_sheet_unmapped", "Balance-sheet/unmapped"),
        ]


class AccountingDimensionConflictContextBuilder:
    """Build read-only context from the latest dimension sync audit metadata."""

    @staticmethod
    def build():
        sync_event = (
            AuditEvent.objects.filter(event_type="accounting_dimension_sync_completed")
            .order_by("-created_at", "-id")
            .first()
        )
        conflicts = []
        if sync_event:
            for conflict in (sync_event.metadata or {}).get("conflicts", []):
                conflicts.append(AccountingDimensionConflictContextBuilder._row(conflict, sync_event))

        return {
            "sync_event": sync_event,
            "conflicts": conflicts,
        }

    @staticmethod
    def _row(conflict, sync_event):
        code = conflict.get("code") or conflict.get("incoming_code") or conflict.get("existing_code") or ""
        external_id = AccountingDimensionConflictContextBuilder._external_id(conflict)
        dimension_type = conflict.get("dimension_type", "")
        local_dimension = AccountingDimensionConflictContextBuilder._local_dimension(
            sync_event=sync_event,
            code=code,
            external_id=external_id,
            dimension_type=dimension_type,
        )

        return {
            "type": conflict.get("type", "unknown"),
            "code": code,
            "external_id": external_id,
            "dimension_type": dimension_type,
            "local_dimension": local_dimension,
            "raw_summary": AccountingDimensionConflictContextBuilder._raw_summary(conflict),
            "explanation": AccountingDimensionConflictContextBuilder._explanation(conflict),
            "suggested_action": AccountingDimensionConflictContextBuilder._suggested_action(conflict),
            "sync_event": sync_event,
        }

    @staticmethod
    def _external_id(conflict):
        if conflict.get("external_id"):
            return conflict["external_id"]
        if conflict.get("incoming_external_id") or conflict.get("existing_external_id"):
            return " / ".join(
                value
                for value in [conflict.get("existing_external_id"), conflict.get("incoming_external_id")]
                if value
            )
        external_ids = conflict.get("external_ids") or []
        return " / ".join(str(value) for value in external_ids if value)

    @staticmethod
    def _local_dimension(*, sync_event, code, external_id, dimension_type):
        queryset = AccountingDimension.objects.all()
        if sync_event and sync_event.organization_id:
            queryset = queryset.filter(organization=sync_event.organization)
        if dimension_type:
            queryset = queryset.filter(dimension_type=dimension_type)

        if code:
            dimension = queryset.filter(code=code).first()
            if dimension:
                return dimension

        external_candidates = [value.strip() for value in str(external_id).split("/") if value.strip()]
        for candidate in external_candidates:
            dimension = queryset.filter(external_id=candidate).first()
            if dimension:
                return dimension
        return None

    @staticmethod
    def _raw_summary(conflict):
        return [
            {"key": key, "value": value}
            for key, value in conflict.items()
            if key not in {"type", "code", "dimension_type"}
        ]

    @staticmethod
    def _explanation(conflict):
        conflict_type = conflict.get("type")
        if conflict_type == "duplicate_incoming_code":
            return "Merit returned more than one dimension value with the same code."
        if conflict_type == "same_code_different_external_id":
            return "The local cache already has this code with a different Merit external id."
        if conflict_type == "same_external_id_different_code":
            return "The local cache already has this Merit external id with a different code."
        return "The sync detected a dimension conflict that needs manual review."

    @staticmethod
    def _suggested_action(conflict):
        conflict_type = conflict.get("type")
        if conflict_type == "duplicate_incoming_code":
            return "Review duplicate codes in Merit, keep the intended value, then run sync again."
        if conflict_type == "same_code_different_external_id":
            return "Compare Merit and Workspace cache before changing either external id or code."
        if conflict_type == "same_external_id_different_code":
            return "Check whether the Merit dimension was renamed or re-coded before updating local cache."
        return "Review Merit and Workspace data manually before attempting another sync."
