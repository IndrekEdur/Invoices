from django.db.models import Q
from django.urls import reverse

from apps.communications.models import CommunicationIntelligenceCandidate
from apps.projects.models import Project


class CommunicationCandidateContextBuilder:
    """Read-only context for communication intelligence candidate review visibility."""

    @staticmethod
    def build(*, project_id="", candidate_type="", confidence="", query=""):
        candidates = (
            CommunicationIntelligenceCandidate.objects.select_related("project", "email_message", "organization")
            .filter(status=CommunicationIntelligenceCandidate.Status.PENDING_REVIEW)
            .order_by("-created_at", "-id")
        )
        if project_id:
            candidates = candidates.filter(project_id=project_id)
        if candidate_type:
            candidates = candidates.filter(candidate_type=candidate_type)
        if confidence:
            candidates = candidates.filter(confidence_band=confidence)
        if query:
            candidates = candidates.filter(
                Q(title__icontains=query)
                | Q(source_evidence_summary__icontains=query)
                | Q(email_message__subject__icontains=query)
                | Q(project__code__icontains=query)
                | Q(project__name__icontains=query)
            )

        return {
            "candidate_rows": [CommunicationCandidateContextBuilder._row(candidate) for candidate in candidates[:100]],
            "projects": Project.objects.order_by("organization__name", "code", "id"),
            "candidate_types": CommunicationIntelligenceCandidate.Type.choices,
            "confidence_bands": CommunicationIntelligenceCandidate.ConfidenceBand.choices,
            "filters": {
                "project_id": project_id,
                "candidate_type": candidate_type,
                "confidence": confidence,
                "query": query,
            },
        }

    @staticmethod
    def _row(candidate):
        return {
            "candidate": candidate,
            "project": candidate.project,
            "email": candidate.email_message,
            "email_detail_url": reverse("workspace:inbox_detail", kwargs={"email_id": candidate.email_message_id}),
            "project_detail_url": reverse("workspace:project_detail", kwargs={"project_id": candidate.project_id}),
        }
