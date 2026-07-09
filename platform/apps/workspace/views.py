from django.contrib import messages
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView

from apps.communications.models import EmailAccount
from apps.communications.services import EmailSyncService, SyncEmailAccountCommand
from apps.projects.services import CreateProjectWithSuggestedCodeCommand, ProjectCreationService

from .services import DashboardContextBuilder, InboxContextBuilder, ProjectsContextBuilder


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
        return context

    def post(self, request, *args, **kwargs):
        organization = ProjectsContextBuilder.get_default_organization()
        if not organization:
            messages.error(request, "Create an Organization before creating projects.")
            return redirect("workspace:project_create")

        actor = request.user if request.user.is_authenticated else None

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

        messages.success(
            request,
            f"Project {result.project.code} {result.project.name} created. "
            "Merit dimension creation will be added in future integration step.",
        )
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
