from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import TemplateView

from apps.communications.models import (
    EmailAccount,
    EmailAnswerDraft,
    EmailMessage,
    EmailProjectLink,
    EmailQuestion,
)
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
from apps.accounting.models import AccountingIntegration
from apps.accounting.services import (
    AccountingDimensionSyncService,
    AccountingDimensionValueService,
    CreateAccountingDimensionValueCommand,
    SyncAccountingDimensionsCommand,
)
from apps.projects.models import Project
from apps.projects.services import CreateProjectWithSuggestedCodeCommand, ProjectCreationService

from .services import (
    DashboardContextBuilder,
    InboxContextBuilder,
    ProjectLinkReviewContextBuilder,
    ProjectsContextBuilder,
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
        email_account = EmailAccount.objects.filter(is_active=True).order_by("id").first()
        redirect_to = request.POST.get("next") or "workspace:inbox"

        if not email_account:
            messages.warning(request, "No active email account is configured yet. Add an EmailAccount before syncing.")
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
            )
        )
        return context


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
            messages.warning(request, message)
        else:
            messages.success(request, message)
        return redirect("workspace:projects")


class ProjectDetailView(WorkspacePageView):
    template_name = "workspace/project_detail.html"
    page_title = "Project Detail"
    section = "projects"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(ProjectsContextBuilder.build_detail(project_id=self.kwargs["project_id"]))
        return context


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
    page_title = "Administration"
    section = "settings"


class DesignSystemView(WorkspacePageView):
    template_name = "workspace/design_system.html"
    page_title = "Design System"
    section = "design_system"
