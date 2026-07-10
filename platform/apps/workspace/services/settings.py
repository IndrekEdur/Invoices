from apps.accounting.models import AccountingDimension, AccountingIntegration
from apps.accounting.services import ProjectCodeAllocationService, SuggestNextProjectCodeCommand
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
