from django.utils import timezone

from apps.communications.models import EmailAnswerDraft, EmailMessage, EmailProjectLink, EmailQuestion
from apps.core.models import AuditEvent
from apps.documents.models import Document
from apps.projects.models import Project
from apps.workflow.models import WorkflowInstance


class DashboardContextBuilder:
    """Builds read-only dashboard context from existing domain models."""

    @staticmethod
    def build():
        today = timezone.localdate()

        cards = [
            {
                "icon": "E",
                "title": "Total Imported Emails",
                "count": EmailMessage.objects.count(),
                "body": "All imported e-mails currently stored.",
                "status": "info",
            },
            {
                "icon": "P",
                "title": "Emails Needing Project Confirmation",
                "count": EmailProjectLink.objects.filter(status=EmailProjectLink.Status.SUGGESTED)
                .values("email_message_id")
                .distinct()
                .count(),
                "body": "Suggested project links waiting for review.",
                "status": "pending",
            },
            {
                "icon": "?",
                "title": "Detected Questions",
                "count": EmailQuestion.objects.count(),
                "body": "Questions detected in communication.",
                "status": "info",
            },
            {
                "icon": "AI",
                "title": "Answer Drafts Needing Review",
                "count": EmailAnswerDraft.objects.filter(status=EmailAnswerDraft.Status.NEEDS_REVIEW).count(),
                "body": "Draft replies waiting for human review.",
                "status": "needs_review",
            },
            {
                "icon": "P",
                "title": "Active Projects",
                "count": Project.objects.filter(status=Project.Status.ACTIVE).count(),
                "body": "Projects currently marked active.",
                "status": "success",
            },
            {
                "icon": "D",
                "title": "Documents",
                "count": Document.objects.count(),
                "body": "Business documents stored in the platform.",
                "status": "neutral",
            },
            {
                "icon": "W",
                "title": "Workflow Instances",
                "count": WorkflowInstance.objects.count(),
                "body": "Workflow executions currently tracked.",
                "status": "neutral",
            },
            {
                "icon": "A",
                "title": "Audit Events Today",
                "count": AuditEvent.objects.filter(created_at__date=today).count(),
                "body": "Traceable actions recorded today.",
                "status": "info",
            },
        ]

        return {
            "dashboard_cards": cards,
            "latest_email_headers": ["Subject", "Sender", "Received"],
            "latest_emails": DashboardContextBuilder._latest_emails(),
            "latest_project_suggestion_headers": ["Email", "Project", "Confidence", "Status"],
            "latest_project_suggestions": DashboardContextBuilder._latest_project_suggestions(),
            "latest_question_headers": ["Question", "Email", "Status"],
            "latest_questions": DashboardContextBuilder._latest_questions(),
            "latest_document_headers": ["Document", "Source", "Status"],
            "latest_documents": DashboardContextBuilder._latest_documents(),
            "latest_audit_event_headers": ["Event", "Object", "Created"],
            "latest_audit_events": DashboardContextBuilder._latest_audit_events(),
        }

    @staticmethod
    def _latest_emails():
        emails = EmailMessage.objects.select_related("account").order_by("-received_at", "-sent_at", "-created_at", "-id")[:5]
        return [
            [
                email.subject or email.external_message_id,
                email.sender_email or "-",
                DashboardContextBuilder._format_datetime(email.received_at or email.sent_at or email.created_at),
            ]
            for email in emails
        ]

    @staticmethod
    def _latest_project_suggestions():
        links = (
            EmailProjectLink.objects.select_related("email_message", "project")
            .order_by("-created_at", "-id")[:5]
        )
        return [
            [
                link.email_message.subject or link.email_message.external_message_id,
                link.project.code,
                f"{link.confidence}%",
                link.status,
            ]
            for link in links
        ]

    @staticmethod
    def _latest_questions():
        questions = EmailQuestion.objects.select_related("email_message").order_by("-created_at", "-id")[:5]
        return [
            [
                question.question_text[:80],
                question.email_message.subject or question.email_message.external_message_id,
                question.status,
            ]
            for question in questions
        ]

    @staticmethod
    def _latest_documents():
        documents = Document.objects.order_by("-created_at", "-id")[:5]
        return [
            [
                document.title or document.original_filename,
                document.source,
                document.status,
            ]
            for document in documents
        ]

    @staticmethod
    def _latest_audit_events():
        audit_events = AuditEvent.objects.order_by("-created_at", "-id")[:5]
        return [
            [
                event.event_type,
                f"{event.object_type}:{event.object_id}",
                DashboardContextBuilder._format_datetime(event.created_at),
            ]
            for event in audit_events
        ]

    @staticmethod
    def _format_datetime(value):
        if not value:
            return "-"
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")
