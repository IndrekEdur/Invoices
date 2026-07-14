from django.db.models import Q
from django.urls import reverse

from apps.communications.models import EmailAnswerDraft, EmailProjectLink
from apps.projects.models import Project


class ProjectLinkReviewContextBuilder:
    """Read-only builder for e-mail to project review decisions."""

    @staticmethod
    def build(*, project_id="", account_id="", source="", confidence_band="", status="", conflict_only=False, query=""):
        links = ProjectLinkReviewContextBuilder.pending_links(
            project_id=project_id,
            account_id=account_id,
            source=source,
            confidence_band=confidence_band,
            status=status,
            conflict_only=conflict_only,
            query=query,
        )
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
            "sources": EmailProjectLink.Source.choices,
            "confidence_bands": EmailProjectLink.ConfidenceBand.choices,
            "statuses": EmailProjectLink.Status.choices,
            "filters": {
                "project_id": project_id,
                "account_id": account_id,
                "source": source,
                "confidence_band": confidence_band,
                "status": status,
                "conflict_only": conflict_only,
                "query": query,
            },
        }

    @staticmethod
    def pending_links(*, project_id="", account_id="", source="", confidence_band="", status="", conflict_only=False, query=""):
        qs = (
            EmailProjectLink.objects.filter(status=status or EmailProjectLink.Status.SUGGESTED)
            .select_related("email_message", "project", "organization")
        )
        if project_id:
            qs = qs.filter(project_id=project_id)
        if account_id:
            qs = qs.filter(email_message__account_id=account_id)
        if source:
            qs = qs.filter(source=source)
        if confidence_band:
            qs = qs.filter(confidence_band=confidence_band)
        if query:
            qs = qs.filter(
                Q(email_message__subject__icontains=query)
                | Q(email_message__sender_email__icontains=query)
                | Q(project__code__icontains=query)
                | Q(project__name__icontains=query)
            )
        if conflict_only:
            qs = qs.filter(evidence__warnings__isnull=False)
        return qs.order_by("-confidence", "-created_at", "-id")

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
            "confidence_band": link.confidence_band or ProjectLinkReviewContextBuilder.confidence_label(link.confidence),
            "source": link.source,
            "evidence_summary": link.evidence_summary,
            "status": link.status,
            "evidence": link.evidence,
            "has_conflict": bool((link.evidence or {}).get("warnings")),
            "confirm_url": reverse("workspace:project_link_confirm", kwargs={"link_id": link.id}),
            "reject_url": reverse("workspace:project_link_reject", kwargs={"link_id": link.id}),
            "correct_url": reverse("workspace:project_link_correct", kwargs={"link_id": link.id}),
            "email_detail_url": reverse("workspace:inbox_detail", kwargs={"email_id": link.email_message_id}),
            "projects": Project.objects.filter(organization=link.organization).order_by("code", "id"),
        }

    @staticmethod
    def confidence_label(confidence):
        if confidence >= 95:
            return "exact"
        if confidence >= 80:
            return "high"
        if confidence >= 60:
            return "medium"
        return "low"

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
