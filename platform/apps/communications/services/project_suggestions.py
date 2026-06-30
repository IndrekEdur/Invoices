from django.db import transaction

from apps.core.services import AuditService
from apps.projects.models import Project

from ..models import EmailProjectLink


class EmailProjectSuggestionService:
    """Rules-based project suggestions for e-mail messages before AI is introduced."""

    @staticmethod
    def suggest(command):
        email_message = command.email_message
        metadata = dict(command.metadata or {})
        suggestions = []

        with transaction.atomic():
            for project in Project.objects.filter(
                organization=email_message.organization,
                status=Project.Status.ACTIVE,
            ):
                evidence_items = EmailProjectSuggestionService._collect_evidence(email_message, project)
                if not evidence_items:
                    continue

                confidence = max(item["confidence"] for item in evidence_items)
                link, created = EmailProjectLink.objects.get_or_create(
                    email_message=email_message,
                    project=project,
                    defaults={
                        "organization": email_message.organization,
                        "status": EmailProjectLink.Status.SUGGESTED,
                        "confidence": confidence,
                        "evidence": {"matches": evidence_items},
                        "metadata": metadata,
                    },
                )

                if not created and link.status in {
                    EmailProjectLink.Status.CONFIRMED,
                    EmailProjectLink.Status.REJECTED,
                }:
                    continue

                if not created:
                    link.status = EmailProjectLink.Status.SUGGESTED
                    link.confidence = confidence
                    link.evidence = {"matches": evidence_items}
                    link.metadata = metadata
                    link.save(update_fields=["status", "confidence", "evidence", "metadata", "updated_at"])

                AuditService.record(
                    event_type="email_project_link.suggested",
                    message=f"Email project link suggested: {link}",
                    organization=email_message.organization,
                    actor=command.actor,
                    object_type="EmailProjectLink",
                    object_id=str(link.id),
                    metadata={
                        "email_message_id": email_message.id,
                        "project_id": project.id,
                        "confidence": confidence,
                        "evidence": {"matches": evidence_items},
                        "suggestion_metadata": metadata,
                        "created": created,
                    },
                )
                suggestions.append(link)

        return suggestions

    @staticmethod
    def _collect_evidence(email_message, project):
        subject = email_message.subject or ""
        body_text = email_message.body_text or ""
        evidence = []

        for field_name, value in (("subject", subject), ("body_text", body_text)):
            lower_value = value.casefold()
            if project.code and project.code.casefold() in lower_value:
                evidence.append(
                    {
                        "matched_field": field_name,
                        "matched_project_code": project.code,
                        "confidence": 90,
                    }
                )
            if project.name and project.name.casefold() in lower_value:
                evidence.append(
                    {
                        "matched_field": field_name,
                        "matched_project_name": project.name,
                        "confidence": 75,
                    }
                )

        return evidence
