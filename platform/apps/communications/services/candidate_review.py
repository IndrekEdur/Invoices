from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.services import AuditService

from ..models import CommunicationIntelligenceCandidate


@dataclass(frozen=True)
class ReviewCommunicationCandidateResult:
    candidate: object
    previous_status: str
    new_status: str
    outcome: str
    changed: bool
    corrected_fields: dict
    feedback: dict
    message: str
    metadata: dict


class CommunicationCandidateReviewService:
    """Review CommunicationIntelligenceCandidate without operationalizing it."""

    TERMINAL_FOR_NORMAL_REVIEW = {
        CommunicationIntelligenceCandidate.Status.DUPLICATE,
        CommunicationIntelligenceCandidate.Status.MERGED,
        CommunicationIntelligenceCandidate.Status.EXPIRED,
    }

    @staticmethod
    @transaction.atomic
    def review(command):
        candidate = command.candidate
        outcome = command.outcome
        metadata = dict(command.metadata or {})

        CommunicationCandidateReviewService._validate_lifecycle(candidate)
        CommunicationCandidateReviewService._validate_outcome(command)
        CommunicationCandidateReviewService._validate_project(candidate, command.project)
        CommunicationCandidateReviewService._validate_merge_target(candidate, command.merge_target)

        previous_status = candidate.status
        original_snapshot = CommunicationCandidateReviewService._snapshot(candidate)
        if CommunicationCandidateReviewService._is_idempotent_review(candidate, command):
            return ReviewCommunicationCandidateResult(
                candidate=candidate,
                previous_status=previous_status,
                new_status=candidate.status,
                outcome=outcome,
                changed=False,
                corrected_fields={},
                feedback=dict(candidate.human_feedback or {}),
                message="Candidate review was already up to date.",
                metadata=metadata,
            )
        corrected_fields = CommunicationCandidateReviewService._apply_review_fields(candidate, command)
        new_status = CommunicationCandidateReviewService._status_for_outcome(outcome)
        if candidate.status != new_status:
            candidate.status = new_status
        candidate.review_outcome = outcome
        candidate.review_reason = command.reason or ""
        if outcome == CommunicationIntelligenceCandidate.ReviewOutcome.DEFER:
            candidate.review_snoozed_until = command.snooze_until
        else:
            candidate.review_snoozed_until = None
        if outcome in {
            CommunicationIntelligenceCandidate.ReviewOutcome.DUPLICATE,
            CommunicationIntelligenceCandidate.ReviewOutcome.MERGE,
        }:
            candidate.merged_into = command.merge_target
        candidate.reviewed_by = command.actor
        candidate.reviewed_at = timezone.now()
        candidate.human_feedback = CommunicationCandidateReviewService._feedback(
            candidate,
            command,
            original_snapshot,
            corrected_fields,
        )

        changed = CommunicationCandidateReviewService._has_changed(candidate, original_snapshot)
        if not changed:
            return ReviewCommunicationCandidateResult(
                candidate=candidate,
                previous_status=previous_status,
                new_status=candidate.status,
                outcome=outcome,
                changed=False,
                corrected_fields={},
                feedback=dict(candidate.human_feedback or {}),
                message="Candidate review was already up to date.",
                metadata=metadata,
            )

        candidate.save()
        AuditService.record(
            event_type="communication_candidate.reviewed",
            message=f"Communication candidate {candidate.id} reviewed as {outcome}.",
            organization=candidate.organization,
            actor=command.actor,
            object_type="CommunicationIntelligenceCandidate",
            object_id=str(candidate.id),
            metadata={
                **metadata,
                "outcome": outcome,
                "previous_status": previous_status,
                "new_status": candidate.status,
                "original": original_snapshot,
                "corrected_fields": corrected_fields,
                "feedback": dict(candidate.human_feedback or {}),
                "merge_target_id": command.merge_target.id if command.merge_target else None,
            },
        )
        return ReviewCommunicationCandidateResult(
            candidate=candidate,
            previous_status=previous_status,
            new_status=candidate.status,
            outcome=outcome,
            changed=True,
            corrected_fields=corrected_fields,
            feedback=dict(candidate.human_feedback or {}),
            message="Candidate review recorded.",
            metadata=metadata,
        )

    @staticmethod
    def _validate_lifecycle(candidate):
        if candidate.status in CommunicationCandidateReviewService.TERMINAL_FOR_NORMAL_REVIEW:
            raise ValidationError("Candidate cannot be reviewed from its current lifecycle state.")

    @staticmethod
    def _validate_outcome(command):
        valid = {choice for choice, _label in CommunicationIntelligenceCandidate.ReviewOutcome.choices}
        if command.outcome not in valid:
            raise ValidationError("Unsupported candidate review outcome.")
        if command.outcome in {
            CommunicationIntelligenceCandidate.ReviewOutcome.REJECT,
            CommunicationIntelligenceCandidate.ReviewOutcome.NOT_ACTIONABLE,
        } and not (command.reason or "").strip():
            raise ValidationError("Rejecting a candidate requires a reason.")
        if command.outcome == CommunicationIntelligenceCandidate.ReviewOutcome.MERGE and not command.merge_target:
            raise ValidationError("Merging a candidate requires a merge target.")
        if command.outcome == CommunicationIntelligenceCandidate.ReviewOutcome.DEFER and not command.snooze_until:
            raise ValidationError("Deferring a candidate requires a snooze date.")
        if command.candidate_type:
            valid_types = {choice for choice, _label in CommunicationIntelligenceCandidate.Type.choices}
            if command.candidate_type not in valid_types:
                raise ValidationError("Unsupported candidate type.")

    @staticmethod
    def _validate_project(candidate, project):
        if project and project.organization_id != candidate.organization_id:
            raise ValidationError("Reviewed Project must belong to the same organization.")

    @staticmethod
    def _validate_merge_target(candidate, target):
        if not target:
            return
        if target.id == candidate.id:
            raise ValidationError("Candidate cannot be merged into itself.")
        if target.organization_id != candidate.organization_id:
            raise ValidationError("Merge target must belong to the same organization.")
        current = target
        seen = {candidate.id}
        while current and current.merged_into_id:
            if current.merged_into_id in seen:
                raise ValidationError("Candidate merge would create a cycle.")
            seen.add(current.id)
            current = current.merged_into

    @staticmethod
    def _status_for_outcome(outcome):
        mapping = {
            CommunicationIntelligenceCandidate.ReviewOutcome.APPROVE: CommunicationIntelligenceCandidate.Status.APPROVED,
            CommunicationIntelligenceCandidate.ReviewOutcome.EDIT_AND_APPROVE: CommunicationIntelligenceCandidate.Status.EDITED_AND_APPROVED,
            CommunicationIntelligenceCandidate.ReviewOutcome.REJECT: CommunicationIntelligenceCandidate.Status.REJECTED,
            CommunicationIntelligenceCandidate.ReviewOutcome.NOT_ACTIONABLE: CommunicationIntelligenceCandidate.Status.REJECTED,
            CommunicationIntelligenceCandidate.ReviewOutcome.DUPLICATE: CommunicationIntelligenceCandidate.Status.DUPLICATE,
            CommunicationIntelligenceCandidate.ReviewOutcome.MERGE: CommunicationIntelligenceCandidate.Status.MERGED,
            CommunicationIntelligenceCandidate.ReviewOutcome.DEFER: CommunicationIntelligenceCandidate.Status.PENDING_REVIEW,
        }
        return mapping[outcome]

    @staticmethod
    def _apply_review_fields(candidate, command):
        field_map = {
            "project": ("reviewed_project", command.project, candidate.project),
            "candidate_type": ("reviewed_candidate_type", command.candidate_type, candidate.candidate_type),
            "title": ("reviewed_title", command.title, candidate.title),
            "description": ("reviewed_description", command.description, candidate.description),
            "responsible_party": (
                "reviewed_responsible_party",
                command.responsible_party,
                candidate.suggested_responsible_party,
            ),
            "responsible_email": (
                "reviewed_responsible_email",
                command.responsible_email,
                candidate.suggested_responsible_email,
            ),
            "priority": ("reviewed_priority", command.priority, candidate.suggested_priority),
        }
        corrected = {}
        for feedback_key, (field_name, reviewed_value, original_value) in field_map.items():
            if reviewed_value is None:
                continue
            normalized = reviewed_value.strip() if isinstance(reviewed_value, str) else reviewed_value
            if normalized != original_value:
                setattr(candidate, field_name, normalized)
                corrected[feedback_key] = {
                    "from": getattr(original_value, "id", original_value),
                    "to": getattr(normalized, "id", normalized),
                }
            else:
                setattr(candidate, field_name, "" if isinstance(normalized, str) else None)
        if command.clear_due_date:
            candidate.reviewed_due_date = None
            candidate.reviewed_due_date_cleared = True
            if candidate.suggested_due_date is not None:
                corrected["due_date"] = {"from": candidate.suggested_due_date.isoformat(), "to": None}
        elif command.due_date is not None:
            candidate.reviewed_due_date = command.due_date
            candidate.reviewed_due_date_cleared = False
            if command.due_date != candidate.suggested_due_date:
                corrected["due_date"] = {
                    "from": candidate.suggested_due_date.isoformat() if candidate.suggested_due_date else None,
                    "to": command.due_date.isoformat(),
                }
        return corrected

    @staticmethod
    def _feedback(candidate, command, original_snapshot, corrected_fields):
        return {
            "outcome": command.outcome,
            "project_accepted": "project" not in corrected_fields,
            "type_accepted": "candidate_type" not in corrected_fields,
            "title_edited": "title" in corrected_fields,
            "description_edited": "description" in corrected_fields,
            "assignee_corrected": any(key in corrected_fields for key in ("responsible_party", "responsible_email")),
            "due_date_corrected": "due_date" in corrected_fields,
            "priority_corrected": "priority" in corrected_fields,
            "rejection_reason_code": "not_actionable" if command.outcome == candidate.ReviewOutcome.NOT_ACTIONABLE else "",
            "reason": command.reason or "",
            "duplicate_target": command.merge_target.id
            if command.outcome == candidate.ReviewOutcome.DUPLICATE and command.merge_target
            else None,
            "merge_target": command.merge_target.id
            if command.outcome == candidate.ReviewOutcome.MERGE and command.merge_target
            else None,
            "extractor_version": original_snapshot["extractor_version"],
            "rule_version": original_snapshot["rule_version"],
            "reviewed_at": timezone.now().isoformat(),
        }

    @staticmethod
    def _snapshot(candidate):
        return {
            "status": candidate.status,
            "project_id": candidate.project_id,
            "candidate_type": candidate.candidate_type,
            "title": candidate.title,
            "description": candidate.description,
            "responsible_party": candidate.suggested_responsible_party,
            "responsible_email": candidate.suggested_responsible_email,
            "due_date": candidate.suggested_due_date.isoformat() if candidate.suggested_due_date else None,
            "priority": candidate.suggested_priority,
            "reviewed_project_id": candidate.reviewed_project_id,
            "reviewed_candidate_type": candidate.reviewed_candidate_type,
            "reviewed_title": candidate.reviewed_title,
            "reviewed_description": candidate.reviewed_description,
            "reviewed_responsible_party": candidate.reviewed_responsible_party,
            "reviewed_responsible_email": candidate.reviewed_responsible_email,
            "reviewed_due_date": candidate.reviewed_due_date.isoformat() if candidate.reviewed_due_date else None,
            "reviewed_due_date_cleared": candidate.reviewed_due_date_cleared,
            "reviewed_priority": candidate.reviewed_priority,
            "review_outcome": candidate.review_outcome,
            "review_reason": candidate.review_reason,
            "review_snoozed_until": candidate.review_snoozed_until.isoformat()
            if candidate.review_snoozed_until
            else None,
            "merged_into_id": candidate.merged_into_id,
            "extractor_version": candidate.extractor_version,
            "rule_version": candidate.rule_version,
        }

    @staticmethod
    def _has_changed(candidate, snapshot):
        return CommunicationCandidateReviewService._snapshot(candidate) != snapshot

    @staticmethod
    def _is_idempotent_review(candidate, command):
        if command.outcome != candidate.ReviewOutcome.APPROVE:
            return False
        if candidate.status != candidate.Status.APPROVED or candidate.review_outcome != command.outcome:
            return False
        supplied_values = (
            command.project,
            command.candidate_type,
            command.title,
            command.description,
            command.responsible_party,
            command.responsible_email,
            command.due_date,
            command.priority,
            command.merge_target,
            command.snooze_until,
        )
        return not any(value for value in supplied_values) and not command.clear_due_date and not command.reason
