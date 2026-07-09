from django.urls import reverse

from apps.communications.models import EmailAnswerDraft, EmailProjectLink
from apps.projects.models import Project


class ProjectLinkReviewContextBuilder:
    """Read-only builder for e-mail to project review decisions."""

    @staticmethod
    def build():
        links = ProjectLinkReviewContextBuilder.pending_links()
        drafts = ProjectLinkReviewContextBuilder.answer_drafts_needing_review()
        return {
            "pending_project_links": [
                ProjectLinkReviewContextBuilder.link_row(link) for link in links
            ],
            "answer_drafts_needing_review": [
                ProjectLinkReviewContextBuilder.answer_draft_row(draft)
                for draft in drafts
            ],
            "projects": Project.objects.order_by("organization__name", "code", "id"),
        }

    @staticmethod
    def pending_links():
        return (
            EmailProjectLink.objects.filter(status=EmailProjectLink.Status.SUGGESTED)
            .select_related("email_message", "project", "organization")
            .order_by("-confidence", "-created_at", "-id")
        )

    @staticmethod
    def answer_drafts_needing_review():
        return (
            EmailAnswerDraft.objects.filter(status=EmailAnswerDraft.Status.NEEDS_REVIEW)
            .select_related("email_message", "question", "organization")
            .order_by("-created_at", "-id")
        )

    @staticmethod
    def link_row(link):
        return {
            "link": link,
            "email": link.email_message,
            "project": link.project,
            "confidence": link.confidence,
            "status": link.status,
            "evidence": link.evidence,
            "confirm_url": reverse("workspace:project_link_confirm", kwargs={"link_id": link.id}),
            "reject_url": reverse("workspace:project_link_reject", kwargs={"link_id": link.id}),
            "correct_url": reverse("workspace:project_link_correct", kwargs={"link_id": link.id}),
            "email_detail_url": reverse("workspace:inbox_detail", kwargs={"email_id": link.email_message_id}),
            "projects": Project.objects.filter(organization=link.organization).order_by("code", "id"),
        }

    @staticmethod
    def answer_draft_row(draft):
        return {
            "draft": draft,
            "email": draft.email_message,
            "question": draft.question,
            "email_detail_url": reverse("workspace:inbox_detail", kwargs={"email_id": draft.email_message_id}),
            "approve_url": reverse("workspace:draft_approve", kwargs={"draft_id": draft.id}),
            "reject_url": reverse("workspace:draft_reject", kwargs={"draft_id": draft.id}),
        }
