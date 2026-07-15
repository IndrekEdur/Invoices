from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from apps.communications.models import (
    CommunicationIntelligenceCandidate,
    EmailAccount,
    EmailAnswerDraft,
    EmailMessage,
    EmailProjectLink,
    EmailQuestion,
)
from apps.communications.connectors import IMAPEmailConnector
from apps.communications.services import (
    ApproveEmailAnswerDraftCommand,
    BuildConversationContextCommand,
    ConfirmEmailProjectLinkCommand,
    ConversationContextBuilder,
    CorrectEmailProjectLinkCommand,
    CreateEmailAnswerDraftCommand,
    EmailAnswerDraftService,
    EmailProjectLinkService,
    EmailSyncService,
    MarkEmailAnswerDraftNeedsReviewCommand,
    RejectEmailAnswerDraftCommand,
    RejectEmailProjectLinkCommand,
    ReviewCommunicationCandidateCommand,
    CommunicationCandidateReviewService,
    SyncEmailAccountCommand,
)
from apps.accounting.models import (
    AccountingAccountClassification,
    AccountingIntegration,
    AccountingSyncState,
    AllocationSourceType,
    AllocationStrategy,
    FinancialAlert,
    FinancialAlertRule,
    ManagementAllocationVersion,
    ManagementCostPool,
    VersionStatus,
)
from apps.accounting.models import AccountingDimension
from apps.accounting.connectors import MeritAPIClient
from apps.accounting.services import (
    AccountingDimensionSyncService,
    AccountingDimensionValueService,
    AccountingAccountClassificationManagementService,
    AcknowledgeFinancialAlertCommand,
    ApproveManagementAllocationVersionCommand,
    CreateManagementAllocationRevisionCommand,
    CreateAccountingDimensionValueCommand,
    DismissFinancialAlertCommand,
    FinancialAlertActionService,
    FinancialAlertEvaluationService,
    FinancialAlertRuleService,
    GenerateManagementAllocationProposalCommand,
    GeneralLedgerSyncService,
    ManagementAllocationDraftService,
    ManagementAllocationProposalService,
    ManagementAllocationVersionService,
    SaveAccountingAccountClassificationCommand,
    SyncGeneralLedgerCommand,
    SyncAccountingDimensionsCommand,
    EvaluateFinancialAlertsCommand,
    UpdateFinancialAlertRuleCommand,
    UpdateManagementAllocationDraftCommand,
)
from apps.core.models import Organization
from apps.projects.models import Project
from apps.projects.services import (
    ChangeProjectStatusCommand,
    CreateProjectFromAccountingDimensionCommand,
    CreateProjectWithSuggestedCodeCommand,
    ProjectDimensionImportService,
    ProjectCreationService,
    ProjectDetailsService,
    ProjectStatusService,
    UpdateProjectDetailsCommand,
)

from .forms import (
    AccountClassificationForm,
    AccountingIntegrationForm,
    EmailAccountForm,
    FinancialAlertRuleForm,
    MonthlyGLSyncForm,
    ProjectEditForm,
    ProjectStatusChangeForm,
)
from .services import (
    AccountingDimensionConflictContextBuilder,
    GLAccountClassificationContextBuilder,
    AccountingIntegrationSettingsContextBuilder,
    CommunicationCandidateContextBuilder,
    DashboardContextBuilder,
    EmailAccountSettingsContextBuilder,
    FinancialAlertsContextBuilder,
    InboxContextBuilder,
    OrganizationFinancialDashboardContextBuilder,
    ProjectLinkReviewContextBuilder,
    ProjectFinancialContextBuilder,
    ManagementAllocationContextBuilder,
    ProjectsContextBuilder,
    SettingsContextBuilder,
)
from .services.formatting import format_money, format_percent


class WorkspacePageView(TemplateView):
    """Thin workspace page view; business logic belongs in services."""

    page_title = ""
    section = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["current_section"] = self.section
        context["active_financial_alert_count"] = FinancialAlertsContextBuilder.active_count()
        return context


class DashboardView(WorkspacePageView):
    template_name = "workspace/dashboard.html"
    page_title = "Dashboard"
    section = "dashboard"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(DashboardContextBuilder.build())
        return context


class InboxView(WorkspacePageView):
    template_name = "workspace/inbox.html"
    page_title = "Inbox"
    section = "inbox"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            InboxContextBuilder.build(
                filter_value=self.request.GET.get("filter", "all"),
                query=self.request.GET.get("q", ""),
            )
        )
        return context


class InboxDetailView(WorkspacePageView):
    template_name = "workspace/inbox_detail.html"
    page_title = "Email Detail"
    section = "inbox"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(InboxContextBuilder.build_detail(email_id=self.kwargs["email_id"]))
        return context


class InboxSyncView(View):
    """Manual sync action; provider-specific sync logic remains in EmailSyncService."""

    def post(self, request, *args, **kwargs):
        email_account_id = request.POST.get("email_account_id")
        if email_account_id:
            email_account = get_object_or_404(EmailAccount, id=email_account_id)
        else:
            email_account = EmailAccount.objects.filter(is_active=True).order_by("id").first()
        redirect_to = request.POST.get("next") or "workspace:inbox"

        if not email_account:
            messages.warning(request, "No active email account is configured yet. Add an EmailAccount before syncing.")
            return redirect(redirect_to)
        if not email_account.is_active:
            messages.warning(request, "Selected email account is inactive. Activate it before syncing.")
            return redirect(redirect_to)

        actor = request.user if request.user.is_authenticated else None

        try:
            result = EmailSyncService.sync(
                SyncEmailAccountCommand(
                    email_account=email_account,
                    limit=10,
                    actor=actor,
                    metadata={"source": "workspace_manual_sync"},
                    process_imported=True,
                )
            )
        except Exception:
            messages.error(request, "Email sync failed. Check account configuration and try again.")
            return redirect(redirect_to)

        messages.success(
            request,
            "Email sync completed: "
            f"fetched {result['fetched_count']}, "
            f"imported {result['imported_count']}, "
            f"processed {result['processed_count']}.",
        )
        return redirect(redirect_to)


class ProjectLinkActionMixin:
    def _actor(self, request):
        return request.user if request.user.is_authenticated else None

    def _redirect_back(self, request):
        return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "workspace:inbox")

    def _link(self, link_id):
        return get_object_or_404(EmailProjectLink.objects.select_related("email_message", "project"), id=link_id)


class ProjectLinkConfirmView(ProjectLinkActionMixin, View):
    def post(self, request, link_id, *args, **kwargs):
        link = self._link(link_id)
        try:
            EmailProjectLinkService.confirm(
                ConfirmEmailProjectLinkCommand(
                    link=link,
                    actor=self._actor(request),
                    metadata={"source": "workspace_project_link_review"},
                )
            )
        except Exception:
            messages.error(request, "Project link confirmation failed.")
            return self._redirect_back(request)

        messages.success(request, f"Project link confirmed: {link.project.code} {link.project.name}.")
        return self._redirect_back(request)


class ProjectLinkRejectView(ProjectLinkActionMixin, View):
    def post(self, request, link_id, *args, **kwargs):
        link = self._link(link_id)
        try:
            EmailProjectLinkService.reject(
                RejectEmailProjectLinkCommand(
                    link=link,
                    actor=self._actor(request),
                    reason=request.POST.get("reason", "").strip(),
                    metadata={"source": "workspace_project_link_review"},
                )
            )
        except Exception:
            messages.error(request, "Project link rejection failed.")
            return self._redirect_back(request)

        messages.success(request, f"Project link rejected: {link.project.code} {link.project.name}.")
        return self._redirect_back(request)


class ProjectLinkCorrectView(ProjectLinkActionMixin, View):
    def post(self, request, link_id, *args, **kwargs):
        link = self._link(link_id)
        new_project = Project.objects.filter(
            organization=link.organization,
            id=request.POST.get("new_project_id"),
        ).first()

        if not new_project:
            messages.error(request, "Project link correction failed: choose a valid project.")
            return self._redirect_back(request)

        try:
            confirmed_link = EmailProjectLinkService.correct(
                CorrectEmailProjectLinkCommand(
                    link=link,
                    new_project=new_project,
                    actor=self._actor(request),
                    reason=request.POST.get("reason", "").strip(),
                    metadata={"source": "workspace_project_link_review"},
                )
            )
        except Exception:
            messages.error(request, "Project link correction failed.")
            return self._redirect_back(request)

        messages.success(
            request,
            f"Project link corrected and confirmed: {confirmed_link.project.code} {confirmed_link.project.name}.",
        )
        return self._redirect_back(request)


class ManagementAllocationListView(WorkspacePageView):
    template_name = "workspace/management_allocations.html"
    page_title = "Management Allocations"
    section = "management_allocations"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            ManagementAllocationContextBuilder.build_list(
                month=self.request.GET.get("month", ""),
                pool_id=self.request.GET.get("pool", ""),
                status=self.request.GET.get("status", ""),
                strategy=self.request.GET.get("strategy", ""),
                query=self.request.GET.get("q", ""),
            )
        )
        return context


class ManagementAllocationCreateView(WorkspacePageView):
    template_name = "workspace/management_allocation_create.html"
    page_title = "Create Management Allocation"
    section = "management_allocations"
    session_key = "management_allocation_wizard"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        state = self._wizard_state()
        if self.request.GET:
            display_data = self._merge_wizard_state(state, self.request.GET)
            if "month" in self.request.GET or "recipient_preselection" in self.request.GET or "project_q" in self.request.GET:
                display_data["step"] = 3
        else:
            display_data = state
        selected_project_ids = display_data.get("project_ids") if display_data else None
        preserve_selection = bool(selected_project_ids)
        context.update(
            self._build_create_context(
                display_data,
                selected_project_ids=selected_project_ids,
                preserve_selection=preserve_selection,
            )
        )
        context.update(self._wizard_context(display_data, context))
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get("_wizard_action")
        if not action:
            return self._direct_create(request)
        if action in {"cancel", "start_over"}:
            self._clear_wizard()
            messages.info(request, "Management allocation wizard cleared.")
            return redirect("workspace:management_allocations")

        state = self._merge_wizard_state(self._wizard_state(), request.POST)
        current_step = int(state.get("step") or 1)
        try:
            if action == "back":
                state["step"] = max(1, current_step - 1)
                self._save_wizard(state)
                return redirect("workspace:management_allocation_create")
            if action == "continue":
                self._validate_wizard_state(state, through_step=current_step)
                state["step"] = min(5, current_step + 1)
                self._drop_preview(state)
                self._save_wizard(state)
                return redirect("workspace:management_allocation_create")
            if action == "preview":
                self._validate_wizard_state(state, through_step=3)
                preview = self._preview_from_state(state)
                state["preview_fingerprint"] = preview.metadata["fingerprint"]
                state["previewed_at"] = preview.metadata.get("generated_at", "")
                state["step"] = 5
                self._save_wizard(state)
                return redirect("workspace:management_allocation_create")
            if action == "create_draft":
                self._validate_wizard_state(state, through_step=5)
                preview = self._preview_from_state(state)
                if state.get("preview_fingerprint") != preview.metadata["fingerprint"]:
                    state["step"] = 4
                    self._drop_preview(state)
                    self._save_wizard(state)
                    messages.warning(request, "Preview is stale. Review the refreshed allocation preview before creating a draft.")
                    return redirect("workspace:management_allocation_create")
                result = ManagementAllocationProposalService().generate(
                    self._command_from_state(
                        state,
                        actor=request.user if request.user.is_authenticated else None,
                        metadata=self._wizard_metadata(state, preview),
                    )
                )
                self._clear_wizard()
                messages.success(request, f"Draft allocation proposal v{result.version.version_number} generated.")
                return redirect("workspace:management_allocation_detail", version_id=result.version.id)
        except Exception as exc:
            state["last_error"] = str(exc)
            self._save_wizard(state)
            messages.error(request, f"Management allocation wizard needs attention: {exc}")
            return redirect("workspace:management_allocation_create")

        messages.error(request, "Unsupported wizard action.")
        self._save_wizard(state)
        return redirect("workspace:management_allocation_create")

    def _direct_create(self, request):
        source_type = request.POST.get("source_type") or AllocationSourceType.COST_POOL
        pool = None
        source_project = None
        if source_type == AllocationSourceType.COST_POOL:
            pool_id = request.POST.get("pool_id")
            pool = ManagementCostPool.objects.filter(id=pool_id, is_active=True).first() if pool_id else None
        elif source_type == AllocationSourceType.WORKSPACE_PROJECT:
            source_project_id = request.POST.get("source_project_id")
            source_project = Project.objects.filter(id=source_project_id).first() if source_project_id else None
        else:
            messages.error(request, "Choose a valid management allocation source type.")
            return self.render_to_response(self._post_error_context(request))
        if source_type == AllocationSourceType.COST_POOL and not pool:
            messages.error(request, "Choose an active management cost pool.")
            return self.render_to_response(self._post_error_context(request))
        if source_type == AllocationSourceType.WORKSPACE_PROJECT and not source_project:
            messages.error(request, "Choose a source Project.")
            return self.render_to_response(self._post_error_context(request))
        project_ids = request.POST.getlist("project_ids")
        if not project_ids:
            messages.error(request, "Choose at least one participating Project explicitly.")
            return self.render_to_response(self._post_error_context(request))
        try:
            year, month = self._parse_month(request.POST.get("month"))
            result = ManagementAllocationProposalService().generate(
                GenerateManagementAllocationProposalCommand(
                    year=year,
                    month=month,
                    project_ids=[int(project_id) for project_id in project_ids],
                    pool=pool,
                    source_type=source_type,
                    source_project=source_project,
                    source_amount_basis=request.POST.get("source_amount_basis") or None,
                    source_currency=request.POST.get("source_currency", "").strip().upper(),
                    strategy=request.POST.get("strategy") or None,
                    source_amount=self._source_amount(request),
                    project_manager_id=request.POST.get("project_manager_id") or None,
                    manual_percentages=self._manual_values(request, "manual_percentage_"),
                    manual_amounts=self._manual_values(request, "manual_amount_"),
                    reason=request.POST.get("reason", "").strip(),
                    actor=request.user if request.user.is_authenticated else None,
                    metadata={
                        "source": "workspace_management_allocation_create",
                        "recipient_preselection_criterion": request.POST.get("recipient_preselection", ""),
                        "suggested_project_ids": self._ids_from_csv(request.POST.get("suggested_project_ids", "")),
                        "final_selected_project_ids": [int(project_id) for project_id in project_ids],
                        "user_changes_count": self._user_changes_count(
                            self._ids_from_csv(request.POST.get("suggested_project_ids", "")),
                            [int(project_id) for project_id in project_ids],
                        ),
                    },
                )
            )
        except Exception as exc:
            messages.error(request, f"Management allocation proposal could not be generated: {exc}")
            return self.render_to_response(self._post_error_context(request))

        messages.success(request, f"Draft allocation proposal v{result.version.version_number} generated.")
        return redirect("workspace:management_allocation_detail", version_id=result.version.id)

    def _wizard_state(self):
        state = self.request.session.get(self.session_key, {})
        if not isinstance(state, dict):
            return {}
        return state

    def _save_wizard(self, state):
        self.request.session[self.session_key] = state
        self.request.session.modified = True

    def _clear_wizard(self):
        self.request.session.pop(self.session_key, None)
        self.request.session.modified = True

    def _merge_wizard_state(self, current, data):
        state = dict(current or {})
        state["step"] = int(state.get("step") or 1)
        scalar_fields = [
            "source_type",
            "pool_id",
            "source_project_id",
            "month",
            "source_amount_basis",
            "source_currency",
            "source_amount_mode",
            "source_amount",
            "reason",
            "strategy",
            "project_manager_id",
            "recipient_preselection",
            "project_q",
            "project_status",
            "project_filter",
            "sort",
            "suggested_project_ids",
        ]
        for field in scalar_fields:
            if field in data:
                state[field] = data.get(field, "")
        if "project_ids" in data:
            state["project_ids"] = [str(item) for item in data.getlist("project_ids")]
        manual_percentages = {}
        manual_amounts = {}
        for key, value in data.items():
            if key.startswith("manual_percentage_") and value not in {"", None}:
                manual_percentages[key.replace("manual_percentage_", "")] = value
            if key.startswith("manual_amount_") and value not in {"", None}:
                manual_amounts[key.replace("manual_amount_", "")] = value
        if manual_percentages or "project_ids" in data:
            state["manual_percentages"] = manual_percentages
        if manual_amounts or "project_ids" in data:
            state["manual_amounts"] = manual_amounts
        state.setdefault("source_type", AllocationSourceType.COST_POOL)
        state.setdefault("source_amount_mode", "derive")
        state.setdefault("recipient_preselection", ManagementAllocationContextBuilder.PRESELECTION_POSITIVE_REVENUE)
        state.setdefault("strategy", AllocationStrategy.REVENUE)
        state.setdefault("project_ids", [])
        return state

    def _wizard_context(self, state, create_context):
        step = int(state.get("step") or 1)
        preview = None
        preview_error = ""
        if state.get("preview_fingerprint") or step >= 4:
            try:
                preview = self._preview_from_state(state)
            except Exception as exc:
                preview_error = str(exc)
        preview_rows = self._preview_rows(preview) if preview else []
        preview_fresh = bool(preview and state.get("preview_fingerprint") == preview.metadata["fingerprint"])
        return {
            "wizard_step": step,
            "wizard_steps": self._wizard_steps(step),
            "wizard_state": state,
            "selected_pool_id": str(state.get("pool_id", "")),
            "selected_strategy": state.get("strategy", AllocationStrategy.REVENUE),
            "selected_source_amount_basis": state.get("source_amount_basis", ""),
            "source_amount_mode": state.get("source_amount_mode", "derive"),
            "source_amount": state.get("source_amount", ""),
            "reason": state.get("reason", ""),
            "selected_project_manager_id": str(state.get("project_manager_id", "")),
            "manual_percentages": state.get("manual_percentages", {}),
            "manual_amounts": state.get("manual_amounts", {}),
            "preview": preview,
            "preview_rows": preview_rows,
            "preview_error": preview_error,
            "preview_fresh": preview_fresh,
            "preview_source_amount_display": format_money(preview.source_amount, preview.source_currency or "EUR") if preview else "",
            "preview_allocated_display": format_money(preview.allocated_amount, preview.source_currency or "EUR") if preview else "",
            "preview_unallocated_display": format_money(preview.unallocated_amount, preview.source_currency or "EUR") if preview else "",
            "preview_total_percentage_display": format_percent(preview.total_percentage, places=4) if preview else "",
            "can_create_draft": bool(preview and preview_fresh and not preview.blocking_errors),
            "selected_count": len(state.get("project_ids") or create_context.get("selected_project_ids") or []),
        }

    @staticmethod
    def _wizard_steps(current_step):
        labels = [
            (1, "Source"),
            (2, "Period and amount"),
            (3, "Recipient Projects"),
            (4, "Allocation preview"),
            (5, "Create draft"),
        ]
        return [
            {
                "number": number,
                "label": label,
                "current": number == current_step,
                "complete": number < current_step,
            }
            for number, label in labels
        ]

    def _validate_wizard_state(self, state, *, through_step):
        organization = ManagementAllocationContextBuilder.get_default_organization()
        if not organization:
            raise ValueError("No Organization is available for management allocations.")
        if through_step >= 1:
            source_type = state.get("source_type") or AllocationSourceType.COST_POOL
            if source_type == AllocationSourceType.COST_POOL:
                pool = ManagementCostPool.objects.filter(
                    organization=organization,
                    id=state.get("pool_id"),
                    is_active=True,
                ).first()
                if not pool:
                    raise ValueError("Choose an active management cost pool.")
            elif source_type == AllocationSourceType.WORKSPACE_PROJECT:
                source_project = Project.objects.filter(organization=organization, id=state.get("source_project_id")).first()
                if not source_project:
                    raise ValueError("Choose a source Project.")
            else:
                raise ValueError("Choose a valid management allocation source type.")
        if through_step >= 2:
            self._parse_month(state.get("month"))
            if state.get("source_amount_mode") == "manual" and state.get("source_amount", "") in {"", None}:
                raise ValueError("Enter a manual source amount or use derived source amount.")
        if through_step >= 3:
            project_ids = [int(item) for item in state.get("project_ids", [])]
            if not project_ids:
                raise ValueError("Choose at least one participating Project explicitly.")
            if state.get("source_type") == AllocationSourceType.WORKSPACE_PROJECT and state.get("source_project_id"):
                if int(state["source_project_id"]) in project_ids:
                    raise ValueError("A source Project cannot also be selected as a target Project.")
        if through_step >= 5:
            if not state.get("preview_fingerprint"):
                raise ValueError("Preview the allocation before creating a draft.")

    def _preview_from_state(self, state):
        return ManagementAllocationProposalService().preview(self._command_from_state(state))

    def _command_from_state(self, state, actor=None, metadata=None):
        organization = ManagementAllocationContextBuilder.get_default_organization()
        year, month = self._parse_month(state.get("month"))
        source_type = state.get("source_type") or AllocationSourceType.COST_POOL
        pool = None
        source_project = None
        if source_type == AllocationSourceType.COST_POOL:
            pool = ManagementCostPool.objects.filter(organization=organization, id=state.get("pool_id")).first()
        elif source_type == AllocationSourceType.WORKSPACE_PROJECT:
            source_project = Project.objects.filter(organization=organization, id=state.get("source_project_id")).first()
        return GenerateManagementAllocationProposalCommand(
            year=year,
            month=month,
            project_ids=[int(project_id) for project_id in state.get("project_ids", [])],
            pool=pool,
            source_type=source_type,
            source_project=source_project,
            source_amount_basis=state.get("source_amount_basis") or None,
            source_currency=str(state.get("source_currency", "")).strip().upper(),
            strategy=state.get("strategy") or None,
            source_amount=state.get("source_amount") if state.get("source_amount_mode") == "manual" else None,
            project_manager_id=state.get("project_manager_id") or None,
            manual_percentages=state.get("manual_percentages") or None,
            manual_amounts=state.get("manual_amounts") or None,
            reason=state.get("reason", "").strip(),
            actor=actor,
            metadata=metadata or {"source": "workspace_management_allocation_wizard"},
        )

    def _preview_rows(self, preview):
        rows = []
        currency = preview.source_currency or "EUR"
        for entry in preview.entries:
            rows.append(
                {
                    "entry": entry,
                    "basis_display": format_money(entry.basis_value, currency)
                    if preview.strategy not in {AllocationStrategy.MANUAL_PERCENT}
                    else format_percent(entry.basis_value, places=4),
                    "percentage_display": format_percent(entry.percentage, places=4),
                    "amount_display": format_money(entry.allocated_amount, currency),
                    "before_direct_cost_display": format_money(entry.before_direct_cost, currency),
                    "current_allocated_in_display": format_money(entry.current_allocated_in, currency),
                    "current_allocated_out_display": format_money(entry.current_allocated_out, currency),
                    "current_management_total_display": format_money(entry.current_management_total_cost, currency),
                    "projected_management_total_display": format_money(entry.projected_management_total_cost, currency),
                }
            )
        return rows

    def _wizard_metadata(self, state, preview):
        suggested_ids = self._ids_from_csv(state.get("suggested_project_ids", ""))
        final_ids = [int(project_id) for project_id in state.get("project_ids", [])]
        return {
            "source": "workspace_management_allocation_wizard",
            "recipient_preselection_criterion": state.get("recipient_preselection", ""),
            "suggested_project_ids": suggested_ids,
            "final_selected_project_ids": final_ids,
            "user_changes_count": self._user_changes_count(suggested_ids, final_ids),
            "source_preview_fingerprint": preview.metadata["fingerprint"],
            "preview_timestamp": state.get("previewed_at", ""),
        }

    @staticmethod
    def _drop_preview(state):
        state.pop("preview_fingerprint", None)
        state.pop("previewed_at", None)

    @staticmethod
    def _parse_month(value):
        year_text, month_text = str(value or "").split("-", 1)
        return int(year_text), int(month_text)

    def _post_error_context(self, request):
        context = self.get_context_data()
        context.update(
            self._build_create_context(
                request.POST,
                selected_project_ids=request.POST.getlist("project_ids"),
                preserve_selection=True,
            )
        )
        return context

    @staticmethod
    def _build_create_context(data, selected_project_ids=None, preserve_selection=False):
        return ManagementAllocationContextBuilder.build_create(
            month=data.get("month", ""),
            source_type=data.get("source_type", ""),
            source_project_id=data.get("source_project_id", ""),
            source_currency=data.get("source_currency", ""),
            recipient_preselection=data.get("recipient_preselection", ""),
            selected_project_ids=selected_project_ids,
            project_query=data.get("project_q", ""),
            project_status=data.get("project_status", ""),
            project_filter=data.get("project_filter", ""),
            sort=data.get("sort", ""),
            preserve_selection=preserve_selection,
        )

    @staticmethod
    def _source_amount(request):
        if request.POST.get("source_amount_mode") == "manual":
            return request.POST.get("source_amount") or "0"
        return None

    @staticmethod
    def _manual_values(request, prefix):
        values = {}
        for key, value in request.POST.items():
            if key.startswith(prefix) and value not in {"", None}:
                values[int(key.replace(prefix, ""))] = value
        return values or None

    @staticmethod
    def _ids_from_csv(value):
        ids = []
        for item in str(value or "").split(","):
            if not item:
                continue
            try:
                ids.append(int(item))
            except ValueError:
                continue
        return ids

    @staticmethod
    def _user_changes_count(suggested_ids, selected_ids):
        suggested = set(suggested_ids)
        selected = set(selected_ids)
        return len(suggested - selected) + len(selected - suggested)


class ManagementAllocationSourcePreviewView(WorkspacePageView):
    template_name = "workspace/management_allocation_source_preview.html"
    page_title = "Allocation Source Preview"
    section = "management_allocations"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            ManagementAllocationContextBuilder.build_create(
                month=self.request.GET.get("month", ""),
                source_type=self.request.GET.get("source_type", AllocationSourceType.WORKSPACE_PROJECT),
                source_project_id=self.request.GET.get("source_project_id", ""),
                source_currency=self.request.GET.get("source_currency", ""),
                recipient_preselection=self.request.GET.get("recipient_preselection", ""),
                project_query=self.request.GET.get("project_q", ""),
                project_status=self.request.GET.get("project_status", ""),
                project_filter=self.request.GET.get("project_filter", ""),
                sort=self.request.GET.get("sort", ""),
            )
        )
        return context


class ManagementAllocationDetailView(WorkspacePageView):
    template_name = "workspace/management_allocation_detail.html"
    page_title = "Management Allocation"
    section = "management_allocations"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(ManagementAllocationContextBuilder.build_detail(self.kwargs["version_id"]))
        return context


class ManagementAllocationEditView(WorkspacePageView):
    template_name = "workspace/management_allocation_edit.html"
    page_title = "Edit Management Allocation"
    section = "management_allocations"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(ManagementAllocationContextBuilder.build_detail(self.kwargs["version_id"]))
        if context["version"].status != VersionStatus.DRAFT:
            context["edit_blocked"] = True
        return context

    def post(self, request, version_id, *args, **kwargs):
        version = get_object_or_404(ManagementAllocationVersion, id=version_id)
        entries = []
        for project_id in request.POST.getlist("project_ids"):
            entries.append(
                {
                    "project_id": int(project_id),
                    "percentage": request.POST.get(f"percentage_{project_id}", "0"),
                    "amount": request.POST.get(f"amount_{project_id}", "0"),
                    "manual_override": request.POST.get(f"manual_override_{project_id}") == "on",
                    "notes": request.POST.get(f"notes_{project_id}", ""),
                }
            )
        try:
            ManagementAllocationDraftService.update(
                UpdateManagementAllocationDraftCommand(
                    version=version,
                    entries=entries,
                    edit_mode=request.POST.get("edit_mode") or ManagementAllocationDraftService.EDIT_PERCENTAGES,
                    reason=request.POST.get("reason", "").strip(),
                    actor=request.user if request.user.is_authenticated else None,
                    metadata={"source": "workspace_management_allocation_edit"},
                )
            )
        except Exception as exc:
            messages.error(request, f"Draft allocation could not be saved: {exc}")
            return self.render_to_response(self.get_context_data())

        messages.success(request, "Draft allocation updated.")
        return redirect("workspace:management_allocation_detail", version_id=version.id)


class ManagementAllocationApproveView(View):
    def post(self, request, version_id, *args, **kwargs):
        version = get_object_or_404(ManagementAllocationVersion.objects.select_related("period", "pool"), id=version_id)
        try:
            ManagementAllocationVersionService.approve(
                ApproveManagementAllocationVersionCommand(
                    version=version,
                    actor=request.user if request.user.is_authenticated else None,
                    reason=request.POST.get("reason", "").strip(),
                    metadata={"source": "workspace_management_allocation_approval"},
                )
            )
        except Exception as exc:
            messages.error(request, f"Management allocation could not be approved: {exc}")
            return redirect("workspace:management_allocation_detail", version_id=version.id)

        messages.success(request, "Management allocation approved. Previous approved version was superseded if present.")
        return redirect("workspace:management_allocation_detail", version_id=version.id)


class ManagementAllocationReviseView(View):
    def post(self, request, version_id, *args, **kwargs):
        source = get_object_or_404(ManagementAllocationVersion, id=version_id)
        try:
            result = ManagementAllocationVersionService.create_revision(
                CreateManagementAllocationRevisionCommand(
                    source_version=source,
                    reason=request.POST.get("reason", "").strip(),
                    actor=request.user if request.user.is_authenticated else None,
                    metadata={"source": "workspace_management_allocation_revision"},
                )
            )
        except Exception as exc:
            messages.error(request, f"Revised draft could not be created: {exc}")
            return redirect("workspace:management_allocation_detail", version_id=source.id)

        messages.success(request, f"Revised draft v{result.version.version_number} created.")
        return redirect("workspace:management_allocation_edit", version_id=result.version.id)


class EmailDraftActionMixin:
    def _actor(self, request):
        return request.user if request.user.is_authenticated else None

    def _redirect_to_email(self, email_message):
        return redirect("workspace:inbox_detail", email_id=email_message.id)

    def _draft(self, draft_id):
        return get_object_or_404(
            EmailAnswerDraft.objects.select_related("email_message", "question"),
            id=draft_id,
        )


class EmailDraftCreateView(EmailDraftActionMixin, View):
    """Creates a stored answer draft through the communication service layer."""

    def post(self, request, email_id, *args, **kwargs):
        email_message = get_object_or_404(EmailMessage, id=email_id)
        question = self._selected_question(request, email_message)

        try:
            EmailAnswerDraftService.create_draft(
                CreateEmailAnswerDraftCommand(
                    email_message=email_message,
                    question=question,
                    draft_text=request.POST.get("draft_text", "").strip(),
                    evidence={
                        "source": "workspace_email_detail",
                        "question_id": question.id if question else None,
                    },
                    context_snapshot=self._context_snapshot(email_message),
                    generated_by=EmailAnswerDraft.GeneratedBy.RULE_BASED,
                    actor=self._actor(request),
                    metadata={"source": "workspace_email_detail"},
                )
            )
        except Exception:
            messages.error(request, "Draft reply creation failed.")
            return self._redirect_to_email(email_message)

        messages.success(request, "Draft reply created.")
        return self._redirect_to_email(email_message)

    def _selected_question(self, request, email_message):
        question_id = request.POST.get("question_id")
        if not question_id:
            return None
        return EmailQuestion.objects.filter(
            organization=email_message.organization,
            email_message=email_message,
            id=question_id,
        ).first()

    def _context_snapshot(self, email_message):
        context = ConversationContextBuilder.build(
            BuildConversationContextCommand(email_message=email_message)
        )
        return {
            "email_message_id": email_message.id,
            "thread_message_ids": [message.id for message in context.thread_messages],
            "project_link_ids": [link.id for link in context.project_links],
            "question_ids": [question.id for question in context.questions],
            "attachment_ids": [attachment.id for attachment in context.attachments],
            "document_ids": [document.id for document in context.documents],
            "evidence_count": len(context.evidence),
        }


class EmailDraftNeedsReviewView(EmailDraftActionMixin, View):
    def post(self, request, draft_id, *args, **kwargs):
        draft = self._draft(draft_id)
        try:
            EmailAnswerDraftService.mark_needs_review(
                MarkEmailAnswerDraftNeedsReviewCommand(
                    draft=draft,
                    actor=self._actor(request),
                    metadata={"source": "workspace_email_detail"},
                )
            )
        except Exception:
            messages.error(request, "Draft review status update failed.")
            return self._redirect_to_email(draft.email_message)

        messages.success(request, "Draft marked as needing review.")
        return self._redirect_to_email(draft.email_message)


class EmailDraftApproveView(EmailDraftActionMixin, View):
    def post(self, request, draft_id, *args, **kwargs):
        draft = self._draft(draft_id)
        final_text = request.POST.get("final_text")
        if final_text is not None:
            final_text = final_text.strip()

        try:
            EmailAnswerDraftService.approve(
                ApproveEmailAnswerDraftCommand(
                    draft=draft,
                    actor=self._actor(request),
                    final_text=final_text or None,
                    metadata={"source": "workspace_email_detail"},
                )
            )
        except Exception:
            messages.error(request, "Draft approval failed.")
            return self._redirect_to_email(draft.email_message)

        messages.success(request, "Draft approved. Sending will be added later.")
        return self._redirect_to_email(draft.email_message)


class EmailDraftRejectView(EmailDraftActionMixin, View):
    def post(self, request, draft_id, *args, **kwargs):
        draft = self._draft(draft_id)
        try:
            EmailAnswerDraftService.reject(
                RejectEmailAnswerDraftCommand(
                    draft=draft,
                    actor=self._actor(request),
                    reason=request.POST.get("reason", "").strip(),
                    metadata={"source": "workspace_email_detail"},
                )
            )
        except Exception:
            messages.error(request, "Draft rejection failed.")
            return self._redirect_to_email(draft.email_message)

        messages.success(request, "Draft rejected.")
        return self._redirect_to_email(draft.email_message)


class ProjectsView(WorkspacePageView):
    template_name = "workspace/projects.html"
    page_title = "Projects"
    section = "projects"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            ProjectsContextBuilder.build(
                filter_value=self.request.GET.get("filter", "all"),
                query=self.request.GET.get("q", ""),
                sort=self.request.GET.get("sort", "code"),
                direction=self.request.GET.get("direction", "desc"),
            )
        )
        return context


class ProjectEditView(WorkspacePageView):
    template_name = "workspace/project_edit.html"
    page_title = "Edit Project"
    section = "projects"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(ProjectsContextBuilder.build_detail(project_id=self.kwargs["project_id"]))
        context["form"] = kwargs.get("form") or ProjectEditForm(instance=context["project"])
        return context

    def post(self, request, project_id, *args, **kwargs):
        context = ProjectsContextBuilder.build_detail(project_id=project_id)
        project = context["project"]
        form = ProjectEditForm(request.POST, instance=project)
        if not form.is_valid():
            messages.error(request, "Project could not be saved. Check the highlighted fields.")
            render_context = self.get_context_data(form=form)
            return self.render_to_response(render_context)

        try:
            ProjectDetailsService.update(
                UpdateProjectDetailsCommand(
                    project=project,
                    name=form.cleaned_data["name"],
                    description=form.cleaned_data["description"],
                    project_type=form.cleaned_data["project_type"],
                    start_date=form.cleaned_data["start_date"],
                    end_date=form.cleaned_data["end_date"],
                    actor=request.user if request.user.is_authenticated else None,
                    metadata={"source": "workspace_project_edit"},
                )
            )
        except Exception:
            messages.error(request, "Project save failed.")
            render_context = self.get_context_data(form=form)
            return self.render_to_response(render_context)

        messages.success(request, f"Project {project.code} updated.")
        return redirect("workspace:project_detail", project_id=project.id)


class ProjectStatusView(View):
    def post(self, request, project_id, *args, **kwargs):
        try:
            project = ProjectsContextBuilder.build_detail(project_id=project_id)["project"]
        except Project.DoesNotExist:
            messages.error(request, "Project was not found.")
            return redirect("workspace:projects")

        form = ProjectStatusChangeForm(request.POST, project=project)
        if not form.is_valid():
            messages.error(request, "Choose a valid status transition.")
            return redirect("workspace:project_detail", project_id=project.id)

        try:
            result = ProjectStatusService.change_status(
                ChangeProjectStatusCommand(
                    project=project,
                    new_status=form.cleaned_data["new_status"],
                    reason=form.cleaned_data["reason"],
                    actor=request.user if request.user.is_authenticated else None,
                    metadata={"source": "workspace_project_status"},
                )
            )
        except Exception:
            messages.error(request, "Project status change failed.")
            return redirect("workspace:project_detail", project_id=project.id)

        if result.changed:
            messages.success(
                request,
                f"Project status changed from {result.previous_status} to {result.new_status}.",
            )
        else:
            messages.info(request, result.message)
        return redirect("workspace:project_detail", project_id=project.id)


class ProjectCreateFromDimensionView(View):
    def post(self, request, dimension_id, *args, **kwargs):
        organization = ProjectsContextBuilder.get_default_organization()
        dimension = AccountingDimension.objects.filter(id=dimension_id)
        if organization:
            dimension = dimension.filter(organization=organization)
        dimension = dimension.select_related("organization", "integration").first()
        if not dimension:
            messages.error(request, "Accounting dimension was not found.")
            return redirect("workspace:projects")

        try:
            result = ProjectDimensionImportService.create_project(
                CreateProjectFromAccountingDimensionCommand(
                    accounting_dimension=dimension,
                    project_name=request.POST.get("project_name") or None,
                    project_type=request.POST.get("project_type") or Project.Type.ELECTRICAL,
                    status=Project.Status.ACTIVE,
                    description=request.POST.get("description", ""),
                    actor=request.user if request.user.is_authenticated else None,
                    metadata={"source": "workspace_project_from_dimension"},
                )
            )
        except Exception:
            messages.error(request, "Workspace project could not be created from the accounting dimension.")
            return redirect("workspace:projects")

        messages.success(
            request,
            f"{result.message} Linked GL allocations: {result.linked_allocation_count}.",
        )
        return redirect("workspace:project_detail", project_id=result.project.id)


class ProjectCreateView(WorkspacePageView):
    template_name = "workspace/project_create.html"
    page_title = "Create Project"
    section = "projects"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            ProjectsContextBuilder.build_create_context(
                prefix=self.request.GET.get("prefix", ""),
                min_code=self.request.GET.get("min_code") or None,
            )
        )
        context.update(self._merit_context())
        return context

    def post(self, request, *args, **kwargs):
        organization = ProjectsContextBuilder.get_default_organization()
        if not organization:
            messages.error(request, "Create an Organization before creating projects.")
            return redirect("workspace:project_create")

        actor = request.user if request.user.is_authenticated else None
        create_merit_dimension = request.POST.get("create_merit_dimension") == "on"

        try:
            result = ProjectCreationService.create_with_suggested_code(
                CreateProjectWithSuggestedCodeCommand(
                    organization=organization,
                    name=request.POST.get("name", "").strip(),
                    description=request.POST.get("description", "").strip(),
                    project_type=request.POST.get("project_type", "other"),
                    status=request.POST.get("status", "active"),
                    min_code=request.POST.get("min_code") or None,
                    prefix=request.POST.get("prefix", "").strip(),
                    actor=actor,
                    metadata={"source": "workspace_project_create"},
                )
            )
        except Exception:
            messages.error(request, "Project creation failed. Check project data and try again.")
            return redirect("workspace:project_create")

        if create_merit_dimension:
            merit_result = self._create_merit_dimension_value(request, result.project, actor)
            if merit_result is None:
                return redirect("workspace:projects")

            messages.success(
                request,
                f"Project {result.project.code} {result.project.name} created and Merit dimension value synced.",
            )
            return redirect("workspace:projects")

        messages.success(request, f"Project {result.project.code} {result.project.name} created.")
        return redirect("workspace:projects")

    def _merit_context(self):
        integration = self._active_merit_integration()
        return {
            "merit_integration": integration,
            "merit_project_dimension_id": self._project_dimension_id(integration) if integration else "",
        }

    def _active_merit_integration(self):
        return AccountingIntegration.objects.filter(
            provider=AccountingIntegration.Provider.MERIT,
            is_active=True,
        ).order_by("id").first()

    def _project_dimension_id(self, integration):
        return (integration.metadata or {}).get("project_dimension_id") if integration else ""

    def _create_merit_dimension_value(self, request, project, actor):
        integration = self._active_merit_integration()
        if not integration:
            messages.error(request, "No active Merit integration configured.")
            return None

        project_dimension_id = self._project_dimension_id(integration)
        if not project_dimension_id:
            messages.error(request, "Merit project dimension id is missing in integration settings.")
            return None

        try:
            # Project creation and the external Merit API call cannot be made
            # one atomic database transaction. If Merit fails, the Workspace
            # project remains and the user can retry dimension creation later.
            return AccountingDimensionValueService.create(
                CreateAccountingDimensionValueCommand(
                    integration=integration,
                    code=project.code,
                    name=project.name,
                    dimension_type="project",
                    dimension_id=project_dimension_id,
                    actor=actor,
                    metadata={"source": "workspace_project_create"},
                )
            )
        except Exception:
            messages.error(request, "Project was created, but Merit dimension value creation failed.")
            return None


class MeritDimensionSyncView(View):
    """Manual Merit dimension sync action; sync and API logic stay in accounting services."""

    def post(self, request, *args, **kwargs):
        integration = AccountingIntegration.objects.filter(
            provider=AccountingIntegration.Provider.MERIT,
            is_active=True,
        ).order_by("id").first()

        if not integration:
            messages.warning(request, "No active Merit integration is configured yet.")
            return redirect("workspace:projects")

        actor = request.user if request.user.is_authenticated else None

        try:
            result = AccountingDimensionSyncService.sync(
                SyncAccountingDimensionsCommand(
                    integration=integration,
                    actor=actor,
                    metadata={"source": "workspace_merit_dimension_sync"},
                )
            )
        except Exception:
            messages.error(request, "Merit dimension sync failed. Check integration configuration and try again.")
            return redirect("workspace:projects")

        message = (
            "Merit dimension sync completed: "
            f"created {result.created_count}, "
            f"updated {result.updated_count}, "
            f"unchanged {result.unchanged_count}, "
            f"archived {result.archived_count}, "
            f"conflicts {result.conflict_count}."
        )
        if result.conflict_count:
            messages.warning(
                request,
                message + " Review dimension conflicts before attempting manual corrections.",
            )
        else:
            messages.success(request, message)
        return redirect("workspace:projects")


class AccountingDimensionConflictsView(WorkspacePageView):
    template_name = "workspace/accounting_dimension_conflicts.html"
    page_title = "Dimension Conflicts"
    section = "projects"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(AccountingDimensionConflictContextBuilder.build())
        return context


class ProjectDetailView(WorkspacePageView):
    template_name = "workspace/project_detail.html"
    page_title = "Project Detail"
    section = "projects"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(ProjectsContextBuilder.build_detail(project_id=self.kwargs["project_id"]))
        context["financial_alert_summary"] = FinancialAlertsContextBuilder.project_summary(context["project"])
        pending_candidates = (
            CommunicationIntelligenceCandidate.objects.filter(
                project=context["project"],
                status=CommunicationIntelligenceCandidate.Status.PENDING_REVIEW,
            )
            .select_related("email_message")
            .order_by("-created_at", "-id")
        )
        context["pending_communication_candidate_count"] = pending_candidates.count()
        context["latest_pending_communication_candidates"] = pending_candidates[:5]
        context["communication_candidate_review_url"] = (
            reverse("workspace:communication_ai_review") + f"?project={context['project'].id}"
        )
        return context


class ProjectFinancialsView(WorkspacePageView):
    template_name = "workspace/project_financials.html"
    page_title = "Project Financials"
    section = "projects"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            ProjectFinancialContextBuilder.build(
                project_id=self.kwargs["project_id"],
                params=self.request.GET,
            )
        )
        context["financial_alert_banner"] = FinancialAlertsContextBuilder.project_financial_banner(
            project=context["project"],
            period_start=context["period"]["start"],
            period_end=context["period"]["end"],
        )
        return context


class FinancialAlertsView(WorkspacePageView):
    template_name = "workspace/financial_alerts.html"
    page_title = "Financial Alerts"
    section = "alerts"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = Organization.objects.order_by("id").first()
        context.update(FinancialAlertsContextBuilder.build(self.request.GET, organization=organization))
        return context


class ProjectAlertsView(WorkspacePageView):
    template_name = "workspace/financial_alerts.html"
    page_title = "Project Financial Alerts"
    section = "projects"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        project = get_object_or_404(Project, id=self.kwargs["project_id"])
        context.update(FinancialAlertsContextBuilder.build(self.request.GET, project=project, organization=project.organization))
        return context


class FinancialAlertDetailView(WorkspacePageView):
    template_name = "workspace/financial_alert_detail.html"
    page_title = "Financial Alert"
    section = "alerts"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        alert = get_object_or_404(FinancialAlert, id=self.kwargs["alert_id"])
        context.update(FinancialAlertsContextBuilder.build_detail(alert))
        return context


class FinancialAlertActionMixin:
    def _alert(self):
        return get_object_or_404(FinancialAlert, id=self.kwargs["alert_id"])

    def _actor(self, request):
        return request.user if request.user.is_authenticated else None

    def _safe_redirect(self, request, alert):
        fallback = reverse("workspace:financial_alert_detail", kwargs={"alert_id": alert.id})
        target = request.POST.get("next") or request.META.get("HTTP_REFERER") or fallback
        if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
            return target
        return fallback


class FinancialAlertAcknowledgeView(FinancialAlertActionMixin, View):
    def post(self, request, *args, **kwargs):
        alert = self._alert()
        try:
            result = FinancialAlertActionService.acknowledge(
                AcknowledgeFinancialAlertCommand(
                    alert=alert,
                    actor=self._actor(request),
                    metadata={"source": "workspace_financial_alerts"},
                )
            )
            if result.changed:
                messages.success(request, "Financial alert acknowledged.")
            else:
                messages.info(request, result.message)
        except Exception as exc:
            messages.error(request, f"Financial alert could not be acknowledged: {exc}")
        return redirect(self._safe_redirect(request, alert))


class FinancialAlertDismissView(FinancialAlertActionMixin, View):
    def post(self, request, *args, **kwargs):
        alert = self._alert()
        try:
            FinancialAlertActionService.dismiss(
                DismissFinancialAlertCommand(
                    alert=alert,
                    actor=self._actor(request),
                    reason=request.POST.get("reason", ""),
                    metadata={"source": "workspace_financial_alerts"},
                )
            )
            messages.success(request, "Financial alert dismissed.")
        except Exception as exc:
            messages.error(request, f"Financial alert could not be dismissed: {exc}")
        return redirect(self._safe_redirect(request, alert))


class ProjectFinancialAllocationsView(WorkspacePageView):
    template_name = "workspace/project_financial_allocations.html"
    page_title = "Project Financial Allocations"
    section = "projects"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            ProjectFinancialContextBuilder.build_allocations(
                project_id=self.kwargs["project_id"],
                params=self.request.GET,
            )
        )
        return context


class FinancialDashboardView(WorkspacePageView):
    template_name = "workspace/financial_dashboard.html"
    page_title = "Financial Dashboard"
    section = "financials"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(OrganizationFinancialDashboardContextBuilder.build(self.request.GET))
        context["monthly_gl_sync_form"] = MonthlyGLSyncForm(
            organization=context.get("organization"),
            selected_month=context["filters"]["month"],
        )
        return context


class FinancialDashboardSyncMonthView(View):
    """Manual one-month GL sync action; GeneralLedgerSyncService remains authoritative."""

    def post(self, request, *args, **kwargs):
        organization = Organization.objects.order_by("id").first()
        form = MonthlyGLSyncForm(request.POST, organization=organization, selected_month=request.POST.get("month", ""))
        redirect_to = self._safe_redirect(request)

        if not form.is_valid():
            messages.error(request, "Merit GL sync could not start. Check the selected month and integration.")
            return redirect(redirect_to)

        integration = form.cleaned_data["integration"]
        sync_state = AccountingSyncState.objects.filter(
            integration=integration,
            source_type=AccountingSyncState.SourceType.GL,
        ).first()
        if sync_state and sync_state.sync_status == AccountingSyncState.SyncStatus.RUNNING:
            messages.warning(request, "A Merit GL sync is already running for this integration.")
            return redirect(redirect_to)

        month = form.cleaned_data["month"]
        month_start = form.month_start
        month_end = form.month_end
        actor = request.user if request.user.is_authenticated else None

        try:
            result = GeneralLedgerSyncService().sync(
                SyncGeneralLedgerCommand(
                    integration=integration,
                    period_start=month_start,
                    period_end=month_end,
                    mode="period_resync",
                    date_type="document_date",
                    with_lines=True,
                    with_cost_allocations=True,
                    initial_import=False,
                    actor=actor,
                    metadata={
                        "source": "workspace_financial_dashboard",
                        "selected_month": month,
                    },
                )
            )
        except Exception:
            latest_run = self._latest_month_run(integration, month_start, month_end)
            if latest_run and latest_run.status == "partial":
                messages.error(
                    request,
                    f"Merit GL sync for {month} failed after partial progress. Earlier completed data was preserved.",
                )
            else:
                messages.error(request, f"Merit GL sync for {month} failed. No new completion state was recorded.")
            return redirect(redirect_to)

        messages.success(
            request,
            f"Merit GL sync completed for {month}: "
            f"discovered {result.discovered_batch_count} provider batches, "
            f"created {result.created_count}, "
            f"updated {result.updated_count}, "
            f"unchanged {result.unchanged_count}, "
            f"failed {result.failed_count}.",
        )
        return redirect(redirect_to)

    @staticmethod
    def _latest_month_run(integration, month_start, month_end):
        return integration.sync_runs.filter(
            source_type=AccountingSyncState.SourceType.GL,
            requested_period_start=month_start,
            requested_period_end=month_end,
        ).order_by("-started_at", "-id").first()

    @staticmethod
    def _safe_redirect(request):
        fallback = reverse("workspace:financial_dashboard")
        target = request.POST.get("next") or fallback
        if not target.startswith(reverse("workspace:financial_dashboard")):
            return fallback
        if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
            return fallback
        return target


class DocumentsView(WorkspacePageView):
    template_name = "workspace/documents.html"
    page_title = "Documents"
    section = "documents"


class ReviewsView(WorkspacePageView):
    template_name = "workspace/reviews.html"
    page_title = "Reviews"
    section = "reviews"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(ProjectLinkReviewContextBuilder.build())
        context["communication_candidate_summary"] = CommunicationCandidateContextBuilder.summary()
        context["latest_communication_candidates"] = (
            CommunicationIntelligenceCandidate.objects.filter(
                status=CommunicationIntelligenceCandidate.Status.PENDING_REVIEW
            )
            .select_related("project", "email_message")
            .order_by("-created_at", "-id")[:5]
        )
        return context


class CommunicationProjectLinksView(WorkspacePageView):
    template_name = "workspace/communication_project_links.html"
    page_title = "Communication Project Links"
    section = "reviews"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            ProjectLinkReviewContextBuilder.build(
                project_id=self.request.GET.get("project", ""),
                account_id=self.request.GET.get("account", ""),
                source=self.request.GET.get("source", ""),
                confidence_band=self.request.GET.get("confidence", ""),
                status=self.request.GET.get("status", ""),
                conflict_only=self.request.GET.get("conflict") == "1",
                query=self.request.GET.get("q", ""),
            )
        )
        return context


class CommunicationCandidatesView(WorkspacePageView):
    template_name = "workspace/communication_candidates.html"
    page_title = "Communication AI Review"
    section = "reviews"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            CommunicationCandidateContextBuilder.build(
                project_id=self.request.GET.get("project", ""),
                candidate_type=self.request.GET.get("type", ""),
                confidence=self.request.GET.get("confidence", ""),
                status=self.request.GET.get("status", ""),
                extraction_method=self.request.GET.get("method", ""),
                due_filter=self.request.GET.get("due", ""),
                include_snoozed=self.request.GET.get("include_snoozed") == "1",
                query=self.request.GET.get("q", ""),
                page=self.request.GET.get("page", 1),
            )
        )
        return context


class CommunicationCandidateDetailView(WorkspacePageView):
    template_name = "workspace/communication_candidate_detail.html"
    page_title = "Communication Candidate Review"
    section = "reviews"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        candidate = get_object_or_404(CommunicationIntelligenceCandidate, id=self.kwargs["candidate_id"])
        context.update(CommunicationCandidateContextBuilder.detail(candidate))
        return context


class CommunicationCandidateReviewPostView(View):
    def post(self, request, candidate_id):
        candidate = get_object_or_404(CommunicationIntelligenceCandidate, id=candidate_id)
        try:
            command = self._command(request, candidate)
            result = CommunicationCandidateReviewService.review(command)
        except (ValidationError, ValueError) as exc:
            messages.error(request, self._safe_error(exc))
            return redirect("workspace:communication_candidate_review", candidate_id=candidate.id)
        except Exception:
            messages.error(request, "Communication candidate review failed.")
            return redirect("workspace:communication_candidate_review", candidate_id=candidate.id)

        if result.changed:
            messages.success(request, result.message)
        else:
            messages.info(request, result.message)
        return redirect(self._safe_redirect(request, candidate))

    def _command(self, request, candidate):
        outcome = request.POST.get("outcome", "")
        project = self._project(request, candidate)
        merge_target = self._merge_target(request, candidate)
        due_date = parse_date(request.POST.get("due_date") or "") if request.POST.get("due_date") else None
        snooze_until = self._snooze_until(request)
        return ReviewCommunicationCandidateCommand(
            candidate=candidate,
            outcome=outcome,
            project=project,
            candidate_type=request.POST.get("candidate_type") or None,
            title=request.POST.get("title") if "title" in request.POST else None,
            description=request.POST.get("description") if "description" in request.POST else None,
            responsible_party=request.POST.get("responsible_party") if "responsible_party" in request.POST else None,
            responsible_email=request.POST.get("responsible_email") if "responsible_email" in request.POST else None,
            due_date=due_date,
            clear_due_date=request.POST.get("clear_due_date") == "1",
            priority=request.POST.get("priority") if "priority" in request.POST else None,
            reason=request.POST.get("reason", ""),
            merge_target=merge_target,
            snooze_until=snooze_until,
            actor=self._actor(request),
            metadata={"source": "workspace_ai_review"},
        )

    def _project(self, request, candidate):
        project_id = request.POST.get("project_id")
        if not project_id:
            return None
        return Project.objects.get(id=project_id, organization=candidate.organization)

    def _merge_target(self, request, candidate):
        target_id = request.POST.get("merge_target_id")
        if not target_id:
            return None
        return CommunicationIntelligenceCandidate.objects.select_related("merged_into").get(
            id=target_id,
            organization=candidate.organization,
        )

    def _snooze_until(self, request):
        raw_value = request.POST.get("snooze_until") or ""
        if not raw_value:
            return None
        parsed = parse_datetime(raw_value)
        if not parsed:
            parsed_date = parse_date(raw_value)
            if not parsed_date:
                raise ValueError("Choose a valid snooze date.")
            parsed = timezone.datetime.combine(parsed_date, timezone.datetime.min.time())
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed

    def _actor(self, request):
        return request.user if request.user.is_authenticated else None

    def _safe_redirect(self, request, candidate):
        next_url = request.POST.get("next")
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return next_url
        return reverse("workspace:communication_candidate_review", kwargs={"candidate_id": candidate.id})

    def _safe_error(self, exc):
        if hasattr(exc, "messages"):
            return " ".join(exc.messages)
        return str(exc) or "Communication candidate review failed."


class SearchView(WorkspacePageView):
    template_name = "workspace/search.html"
    page_title = "Search"
    section = "search"


class AssistantView(WorkspacePageView):
    template_name = "workspace/assistant.html"
    page_title = "AI Assistant"
    section = "assistant"


class SettingsView(WorkspacePageView):
    template_name = "workspace/settings.html"
    page_title = "Settings"
    section = "settings"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(SettingsContextBuilder.build())
        return context


class SettingsSectionView(WorkspacePageView):
    template_name = "workspace/settings_section.html"
    page_title = "Settings"
    section = "settings"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["settings_section"] = self.kwargs["section_slug"]
        return context


class FinancialAlertRuleSettingsMixin:
    section = "settings"

    def _actor(self):
        return self.request.user if self.request.user.is_authenticated else None

    def _organization(self):
        return Organization.objects.order_by("id").first()


class FinancialAlertRuleListView(FinancialAlertRuleSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_financial_alert_rules.html"
    page_title = "Financial Alert Rules"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self._organization()
        rules = FinancialAlertRule.objects.none()
        latest_run = None
        if organization:
            rules = FinancialAlertRule.objects.filter(organization=organization).order_by("alert_type", "name")
            latest_run = organization.financial_alert_evaluation_runs.order_by("-started_at", "-id").first()
        context.update(
            {
                "organization": organization,
                "rules": list(rules),
                "latest_run": latest_run,
                "profitability_rules": [rule for rule in rules if "negative" in rule.alert_type or "margin" in rule.alert_type],
                "revenue_rules": [rule for rule in rules if "revenue" in rule.alert_type],
            }
        )
        return context


class FinancialAlertRuleEditView(FinancialAlertRuleSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_financial_alert_rule_form.html"
    page_title = "Edit Financial Alert Rule"

    def _rule(self):
        return get_object_or_404(FinancialAlertRule, id=self.kwargs["rule_id"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rule = kwargs.get("rule") or self._rule()
        context["rule"] = rule
        context["form"] = kwargs.get("form") or FinancialAlertRuleForm(instance=rule)
        return context

    def post(self, request, rule_id, *args, **kwargs):
        rule = self._rule()
        form = FinancialAlertRuleForm(request.POST, instance=rule)
        if not form.is_valid():
            messages.error(request, "Financial alert rule could not be saved. Check the highlighted fields.")
            return self.render_to_response(self.get_context_data(rule=rule, form=form))
        FinancialAlertRuleService.update_rule(
            UpdateFinancialAlertRuleCommand(
                rule=rule,
                name=form.cleaned_data["name"],
                is_active=form.cleaned_data["is_active"],
                financial_basis=form.cleaned_data["financial_basis"],
                severity=form.cleaned_data["severity"],
                threshold_amount=form.cleaned_data["threshold_amount"],
                threshold_percentage=form.cleaned_data["threshold_percentage"],
                grace_day=form.cleaned_data["grace_day"],
                candidate_scope=form.cleaned_data["candidate_scope"],
                configuration=form.cleaned_data["configuration_text"],
                actor=self._actor(),
                metadata={"source": "workspace_financial_alert_rule_settings"},
            )
        )
        messages.success(request, "Financial alert rule saved. Re-evaluate alerts to apply the rule to current data.")
        return redirect("workspace:settings_financial_alert_rules")


class FinancialAlertRuleReevaluateView(FinancialAlertRuleSettingsMixin, View):
    def post(self, request, *args, **kwargs):
        organization = self._organization()
        if not organization:
            messages.error(request, "No organization is available for financial alert evaluation.")
            return redirect("workspace:settings_financial_alert_rules")
        result = FinancialAlertEvaluationService().evaluate(
            EvaluateFinancialAlertsCommand(
                organization=organization,
                evaluation_date=timezone.localdate(),
                actor=self._actor(),
                metadata={"source": "workspace_financial_alert_rule_settings"},
            )
        )
        messages.success(
            request,
            (
                "Financial alerts re-evaluated: "
                f"projects {result.evaluated_projects}, rules {result.evaluated_rules}, "
                f"opened {result.opened_count}, updated {result.updated_count}, "
                f"reopened {result.reopened_count}, resolved {result.resolved_count}, "
                f"unchanged {result.unchanged_count}, failed {result.failed_count}."
            ),
        )
        return redirect("workspace:settings_financial_alert_rules")


class AccountClassificationSettingsMixin:
    section = "settings"

    def _actor(self):
        return self.request.user if self.request.user.is_authenticated else None

    def _integration_id(self):
        return self.request.POST.get("integration_id") or self.request.GET.get("integration_id")

    def _detail_url(self, account_code):
        url = redirect("workspace:settings_account_classification_detail", account_code=account_code)
        return url


class AccountClassificationListView(AccountClassificationSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_account_classifications.html"
    page_title = "GL Account Classification"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            GLAccountClassificationContextBuilder.build_list(
                filter_value=self.request.GET.get("filter", "all"),
                query=self.request.GET.get("q", ""),
                sort=self.request.GET.get("sort", "account_code"),
                integration_id=self.request.GET.get("integration_id"),
            )
        )
        return context


class AccountClassificationDetailView(AccountClassificationSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_account_classification_detail.html"
    page_title = "GL Account Detail"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            GLAccountClassificationContextBuilder.build_detail(
                account_code=self.kwargs["account_code"],
                integration_id=self.request.GET.get("integration_id"),
            )
        )
        return context


class AccountClassificationEditView(AccountClassificationSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_account_classification_form.html"
    page_title = "Edit GL Account Classification"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            GLAccountClassificationContextBuilder.build_detail(
                account_code=self.kwargs["account_code"],
                integration_id=self._integration_id(),
            )
        )
        account = context.get("account")
        classification = account["direct_mapping"] if account else None
        context["form"] = kwargs.get("form") or AccountClassificationForm(classification=classification)
        return context

    def post(self, request, account_code, *args, **kwargs):
        context = GLAccountClassificationContextBuilder.build_detail(
            account_code=account_code,
            integration_id=self._integration_id(),
        )
        account = context.get("account")
        integration = context.get("selected_integration")
        organization = context.get("organization")
        if not account or not integration or not organization:
            messages.error(request, "Imported GL account was not found for the selected integration.")
            return redirect("workspace:settings_account_classifications")

        form = AccountClassificationForm(request.POST, classification=account["direct_mapping"])
        if not form.is_valid():
            messages.error(request, "Account classification could not be saved. Check the highlighted fields.")
            render_context = self.get_context_data(form=form)
            return self.render_to_response(render_context)

        try:
            AccountingAccountClassificationManagementService.save(
                SaveAccountingAccountClassificationCommand(
                    organization=organization,
                    integration=integration,
                    account_code=account["account_code"],
                    account_name=account["account_name"],
                    category=form.cleaned_data["category"],
                    reporting_sign=form.cleaned_data["reporting_sign"],
                    include_in_project_result=form.cleaned_data["include_in_project_result"],
                    is_active=form.cleaned_data["is_active"],
                    notes=form.cleaned_data["notes"],
                    actor=self._actor(),
                    metadata={"source": "workspace_account_classification_settings"},
                )
            )
        except Exception:
            messages.error(request, "Account classification save failed.")
            render_context = self.get_context_data(form=form)
            return self.render_to_response(render_context)

        messages.success(request, f"Classification saved for account {account['account_code']}.")
        return redirect(
            f"{request.POST.get('next') or request.path.replace('/edit/', '/')}"
            f"?integration_id={integration.id}"
        )


class EmailAccountSettingsMixin:
    section = "settings"

    def _current_organization(self):
        if self.request.user.is_authenticated and hasattr(self.request.user, "app_profile"):
            profile = self.request.user.app_profile
            if profile.active_organization:
                return profile.active_organization
        return Organization.objects.order_by("id").first()

    def _account(self):
        return get_object_or_404(EmailAccount.objects.select_related("organization"), id=self.kwargs["account_id"])


class EmailAccountListView(EmailAccountSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_email_accounts.html"
    page_title = "Email Accounts"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(EmailAccountSettingsContextBuilder.build_list())
        return context


class EmailAccountCreateView(EmailAccountSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_email_account_form.html"
    page_title = "Create Email Account"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = kwargs.get("form") or EmailAccountForm(organization=self._current_organization())
        context["mode"] = "create"
        context["masked_secret"] = ""
        return context

    def post(self, request, *args, **kwargs):
        organization = self._current_organization()
        if not organization:
            messages.error(request, "Create an Organization before adding email accounts.")
            return redirect("workspace:settings_email_accounts")

        form = EmailAccountForm(request.POST, organization=organization)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        email_account = form.save()
        messages.success(request, f"Email account {email_account.email_address} created.")
        return redirect("workspace:settings_email_account_detail", account_id=email_account.id)


class EmailAccountDetailView(EmailAccountSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_email_account_detail.html"
    page_title = "Email Account"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(EmailAccountSettingsContextBuilder.build_detail(self._account()))
        return context


class EmailAccountEditView(EmailAccountSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_email_account_form.html"
    page_title = "Edit Email Account"

    def get_context_data(self, **kwargs):
        email_account = self._account()
        context = super().get_context_data(**kwargs)
        context["email_account"] = email_account
        context["form"] = kwargs.get("form") or EmailAccountForm(instance=email_account)
        context["mode"] = "edit"
        context["masked_secret"] = EmailAccountSettingsContextBuilder.mask_secret(
            email_account.encrypted_secret_placeholder
        )
        return context

    def post(self, request, *args, **kwargs):
        email_account = self._account()
        form = EmailAccountForm(request.POST, instance=email_account)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        email_account = form.save()
        messages.success(request, f"Email account {email_account.email_address} updated.")
        return redirect("workspace:settings_email_account_detail", account_id=email_account.id)


class EmailAccountTestConnectionView(EmailAccountSettingsMixin, View):
    def post(self, request, account_id, *args, **kwargs):
        email_account = self._account()

        if email_account.provider != EmailAccount.Provider.IMAP:
            messages.warning(request, "Connection test not implemented for this provider yet.")
            return redirect("workspace:settings_email_account_detail", account_id=email_account.id)

        connector = IMAPEmailConnector(email_account)
        try:
            connector.connect()
            mailboxes = connector.list_mailboxes()
        except Exception:
            messages.error(request, "Email connection test failed. Check account settings and try again.")
            return redirect("workspace:settings_email_account_detail", account_id=email_account.id)
        finally:
            connector.disconnect()

        messages.success(request, f"Email connection successful. Mailboxes found: {len(mailboxes)}.")
        return redirect("workspace:settings_email_account_detail", account_id=email_account.id)


class AccountingIntegrationSettingsMixin:
    section = "settings"

    def _current_organization(self):
        if self.request.user.is_authenticated and hasattr(self.request.user, "app_profile"):
            profile = self.request.user.app_profile
            if profile.active_organization:
                return profile.active_organization
        return Organization.objects.order_by("id").first()

    def _integration(self):
        return get_object_or_404(
            AccountingIntegration.objects.select_related("organization"),
            id=self.kwargs["integration_id"],
        )


class AccountingIntegrationListView(AccountingIntegrationSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_accounting_integrations.html"
    page_title = "Accounting Integrations"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(AccountingIntegrationSettingsContextBuilder.build_list())
        return context


class AccountingIntegrationCreateView(AccountingIntegrationSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_accounting_integration_form.html"
    page_title = "Create Accounting Integration"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = kwargs.get("form") or AccountingIntegrationForm(
            organization=self._current_organization()
        )
        context["mode"] = "create"
        context["masked_secret"] = ""
        return context

    def post(self, request, *args, **kwargs):
        organization = self._current_organization()
        if not organization:
            messages.error(request, "Create an Organization before adding accounting integrations.")
            return redirect("workspace:settings_accounting_integrations")

        form = AccountingIntegrationForm(request.POST, organization=organization)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        integration = form.save()
        messages.success(request, f"Accounting integration {integration.display_name} created.")
        return redirect("workspace:settings_accounting_integration_detail", integration_id=integration.id)


class AccountingIntegrationDetailView(AccountingIntegrationSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_accounting_integration_detail.html"
    page_title = "Accounting Integration"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(AccountingIntegrationSettingsContextBuilder.build_detail(self._integration()))
        return context


class AccountingIntegrationEditView(AccountingIntegrationSettingsMixin, WorkspacePageView):
    template_name = "workspace/settings_accounting_integration_form.html"
    page_title = "Edit Accounting Integration"

    def get_context_data(self, **kwargs):
        integration = self._integration()
        context = super().get_context_data(**kwargs)
        context["integration"] = integration
        context["form"] = kwargs.get("form") or AccountingIntegrationForm(instance=integration)
        context["mode"] = "edit"
        context["masked_secret"] = AccountingIntegrationSettingsContextBuilder.mask_secret(
            integration.encrypted_secret_placeholder
        )
        return context

    def post(self, request, *args, **kwargs):
        integration = self._integration()
        form = AccountingIntegrationForm(request.POST, instance=integration)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        integration = form.save()
        messages.success(request, f"Accounting integration {integration.display_name} updated.")
        return redirect("workspace:settings_accounting_integration_detail", integration_id=integration.id)


class AccountingIntegrationTestConnectionView(AccountingIntegrationSettingsMixin, View):
    def post(self, request, integration_id, *args, **kwargs):
        integration = self._integration()

        if integration.provider != AccountingIntegration.Provider.MERIT:
            messages.warning(request, "Connection test not implemented for this provider yet.")
            return redirect("workspace:settings_accounting_integration_detail", integration_id=integration.id)

        try:
            health = MeritAPIClient(integration).health()
        except Exception:
            messages.error(request, "Merit connection test failed. Check integration settings and try again.")
            return redirect("workspace:settings_accounting_integration_detail", integration_id=integration.id)

        detail_parts = [f"provider {health.get('provider', integration.provider)}"]
        if health.get("mode"):
            detail_parts.append(f"mode {health['mode']}")
        if health.get("response_time_ms") is not None:
            detail_parts.append(f"response time {health['response_time_ms']} ms")

        messages.success(
            request,
            "Merit connection/configuration check successful: " + ", ".join(detail_parts) + ".",
        )
        return redirect("workspace:settings_accounting_integration_detail", integration_id=integration.id)


class DesignSystemView(WorkspacePageView):
    template_name = "workspace/design_system.html"
    page_title = "Design System"
    section = "design_system"
