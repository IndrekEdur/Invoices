from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.communications.models import CommunicationIntelligenceCandidate
from apps.core.models import AuditEvent
from apps.projects.models import Project


class CommunicationCandidateContextBuilder:
    """Read-only context for communication intelligence candidate review visibility."""

    @staticmethod
    def build(
        *,
        project_id="",
        candidate_type="",
        confidence="",
        status="",
        extraction_method="",
        due_filter="",
        include_snoozed=False,
        query="",
        page=1,
        page_size=25,
    ):
        now = timezone.now()
        candidates = (
            CommunicationIntelligenceCandidate.objects.select_related(
                "project",
                "reviewed_project",
                "email_message",
                "organization",
                "reviewed_by",
                "merged_into",
            )
            .order_by("suggested_due_date", "created_at", "id")
        )
        if status:
            candidates = candidates.filter(status=status)
        else:
            candidates = candidates.filter(status=CommunicationIntelligenceCandidate.Status.PENDING_REVIEW)
        if not include_snoozed:
            candidates = candidates.filter(Q(review_snoozed_until__isnull=True) | Q(review_snoozed_until__lte=now))
        if project_id:
            candidates = candidates.filter(Q(project_id=project_id) | Q(reviewed_project_id=project_id))
        if candidate_type:
            candidates = candidates.filter(Q(candidate_type=candidate_type) | Q(reviewed_candidate_type=candidate_type))
        if confidence:
            candidates = candidates.filter(confidence_band=confidence)
        if extraction_method:
            candidates = candidates.filter(extraction_method=extraction_method)
        if due_filter == "has_due_date":
            candidates = candidates.filter(Q(suggested_due_date__isnull=False) | Q(reviewed_due_date__isnull=False))
        elif due_filter == "no_due_date":
            candidates = candidates.filter(suggested_due_date__isnull=True, reviewed_due_date__isnull=True)
        elif due_filter == "overdue":
            candidates = candidates.filter(
                Q(suggested_due_date__lt=now.date()) | Q(reviewed_due_date__lt=now.date())
            )
        if query:
            candidates = candidates.filter(
                Q(title__icontains=query)
                | Q(description__icontains=query)
                | Q(reviewed_title__icontains=query)
                | Q(reviewed_description__icontains=query)
                | Q(source_evidence_summary__icontains=query)
                | Q(evidence_excerpt__icontains=query)
                | Q(email_message__subject__icontains=query)
                | Q(email_message__sender_email__icontains=query)
                | Q(email_message__sender_name__icontains=query)
                | Q(project__code__icontains=query)
                | Q(project__name__icontains=query)
            )

        page = max(int(page or 1), 1)
        offset = (page - 1) * page_size
        total_count = candidates.count()
        rows = candidates[offset : offset + page_size]

        return {
            "candidate_rows": [CommunicationCandidateContextBuilder._row(candidate) for candidate in rows],
            "summary": CommunicationCandidateContextBuilder.summary(),
            "projects": Project.objects.order_by("organization__name", "code", "id"),
            "candidate_types": CommunicationIntelligenceCandidate.Type.choices,
            "confidence_bands": CommunicationIntelligenceCandidate.ConfidenceBand.choices,
            "statuses": CommunicationIntelligenceCandidate.Status.choices,
            "extraction_methods": CommunicationIntelligenceCandidate.ExtractionMethod.choices,
            "review_outcomes": CommunicationIntelligenceCandidate.ReviewOutcome.choices,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "has_previous": page > 1,
                "has_next": offset + page_size < total_count,
                "previous_page": page - 1,
                "next_page": page + 1,
            },
            "filters": {
                "project_id": project_id,
                "candidate_type": candidate_type,
                "confidence": confidence,
                "status": status,
                "extraction_method": extraction_method,
                "due_filter": due_filter,
                "include_snoozed": include_snoozed,
                "query": query,
            },
        }

    @staticmethod
    def detail(candidate):
        candidate = (
            CommunicationIntelligenceCandidate.objects.select_related(
                "organization",
                "project",
                "reviewed_project",
                "email_message",
                "email_thread",
                "reviewed_by",
                "merged_into",
            )
            .prefetch_related("email_message__project_links")
            .get(id=candidate.id)
        )
        duplicate_candidates = (
            CommunicationIntelligenceCandidate.objects.filter(organization=candidate.organization)
            .exclude(id=candidate.id)
            .filter(Q(project=candidate.project) | Q(email_message=candidate.email_message))
            .select_related("project", "email_message")
            .order_by("-created_at", "-id")[:10]
        )
        audit_events = AuditEvent.objects.filter(
            organization=candidate.organization,
            object_type="CommunicationIntelligenceCandidate",
            object_id=str(candidate.id),
        ).order_by("-created_at")[:10]
        return {
            "candidate": candidate,
            "projects": Project.objects.filter(organization=candidate.organization).order_by("code", "id"),
            "candidate_types": CommunicationIntelligenceCandidate.Type.choices,
            "review_outcomes": CommunicationIntelligenceCandidate.ReviewOutcome.choices,
            "duplicate_candidates": duplicate_candidates,
            "audit_events": audit_events,
            "email_detail_url": reverse("workspace:inbox_detail", kwargs={"email_id": candidate.email_message_id}),
            "project_detail_url": reverse("workspace:project_detail", kwargs={"project_id": candidate.project_id}),
        }

    @staticmethod
    def summary():
        today = timezone.localdate()
        base = CommunicationIntelligenceCandidate.objects.all()
        reviewed_today = base.filter(reviewed_at__date=today).count()
        approved = base.filter(
            status__in=[
                CommunicationIntelligenceCandidate.Status.APPROVED,
                CommunicationIntelligenceCandidate.Status.EDITED_AND_APPROVED,
            ]
        ).count()
        reviewed_total = base.exclude(status=CommunicationIntelligenceCandidate.Status.PENDING_REVIEW).count()
        approval_rate = round((approved / reviewed_total) * 100) if reviewed_total else 0
        return {
            "pending": base.filter(status=CommunicationIntelligenceCandidate.Status.PENDING_REVIEW).count(),
            "high_confidence": base.filter(
                status=CommunicationIntelligenceCandidate.Status.PENDING_REVIEW,
                confidence_band=CommunicationIntelligenceCandidate.ConfidenceBand.HIGH,
            ).count(),
            "questions": base.filter(candidate_type=CommunicationIntelligenceCandidate.Type.QUESTION).count(),
            "task_requests": base.filter(candidate_type=CommunicationIntelligenceCandidate.Type.TASK_REQUEST).count(),
            "commitments": base.filter(candidate_type=CommunicationIntelligenceCandidate.Type.COMMITMENT).count(),
            "decisions": base.filter(candidate_type=CommunicationIntelligenceCandidate.Type.DECISION).count(),
            "risks_blockers": base.filter(
                candidate_type__in=[
                    CommunicationIntelligenceCandidate.Type.RISK,
                    CommunicationIntelligenceCandidate.Type.BLOCKER,
                ]
            ).count(),
            "snoozed": base.filter(review_snoozed_until__gt=timezone.now()).count(),
            "reviewed_today": reviewed_today,
            "approval_rate": approval_rate,
        }

    @staticmethod
    def _row(candidate):
        return {
            "candidate": candidate,
            "project": candidate.project,
            "email": candidate.email_message,
            "email_detail_url": reverse("workspace:inbox_detail", kwargs={"email_id": candidate.email_message_id}),
            "project_detail_url": reverse("workspace:project_detail", kwargs={"project_id": candidate.project_id}),
            "review_url": reverse("workspace:communication_candidate_review", kwargs={"candidate_id": candidate.id}),
            "review_post_url": reverse(
                "workspace:communication_candidate_review_post",
                kwargs={"candidate_id": candidate.id},
            ),
        }
