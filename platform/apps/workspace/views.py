from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from apps.communications.models import (
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
    SyncEmailAccountCommand,
)
from apps.accounting.models import AccountingAccountClassification, AccountingIntegration, AccountingSyncState
from apps.accounting.models import AccountingDimension
from apps.accounting.connectors import MeritAPIClient
from apps.accounting.services import (
    AccountingDimensionSyncService,
    AccountingDimensionValueService,
    AccountingAccountClassificationManagementService,
    CreateAccountingDimensionValueCommand,
    GeneralLedgerSyncService,
    SaveAccountingAccountClassificationCommand,
    SyncGeneralLedgerCommand,
    SyncAccountingDimensionsCommand,
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
    MonthlyGLSyncForm,
    ProjectEditForm,
    ProjectStatusChangeForm,
)
from .services import (
    AccountingDimensionConflictContextBuilder,
    GLAccountClassificationContextBuilder,
    AccountingIntegrationSettingsContextBuilder,
    DashboardContextBuilder,
    EmailAccountSettingsContextBuilder,
    InboxContextBuilder,
    OrganizationFinancialDashboardContextBuilder,
    ProjectLinkReviewContextBuilder,
    ProjectFinancialContextBuilder,
    ProjectsContextBuilder,
    SettingsContextBuilder,
)


class WorkspacePageView(TemplateView):
    """Thin workspace page view; business logic belongs in services."""

    page_title = ""
    section = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["current_section"] = self.section
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
        return context


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
        return context


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
