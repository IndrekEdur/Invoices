import json

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from apps.communications.models import EmailMessage, EmailProjectLink
from apps.projects.models import Project


class InboxContextBuilder:
    """Builds read-only inbox context from communication domain models."""

    VALID_FILTERS = {
        "all",
        "needs_project_confirmation",
        "has_questions",
        "has_attachments",
        "no_project",
    }

    @staticmethod
    def build(*, filter_value="all", query=""):
        active_filter = filter_value if filter_value in InboxContextBuilder.VALID_FILTERS else "all"
        emails = InboxContextBuilder._base_queryset()
        emails = InboxContextBuilder._apply_filter(emails, active_filter)
        emails = InboxContextBuilder._apply_search(emails, query)

        return {
            "active_filter": active_filter,
            "search_query": query,
            "filter_links": InboxContextBuilder._filter_links(active_filter, query),
            "inbox_emails": [InboxContextBuilder._email_row(email) for email in emails[:100]],
        }

    @staticmethod
    def build_detail(*, email_id):
        email = (
            EmailMessage.objects.select_related("account", "thread")
            .prefetch_related("project_links__project", "questions", "attachments")
            .get(pk=email_id)
        )
        project_links = list(email.project_links.select_related("project").order_by("-confidence", "-created_at", "-id"))
        questions = list(email.questions.order_by("-confidence", "id"))
        attachments = list(email.attachments.select_related("document").order_by("original_filename", "id"))

        return {
            "email": email,
            "recipients_display": InboxContextBuilder._format_recipients(email.recipients),
            "cc_display": InboxContextBuilder._format_recipients(email.cc),
            "project_links": [InboxContextBuilder._project_link_context(link) for link in project_links],
            "questions": questions,
            "attachments": attachments,
            "evidence_json": InboxContextBuilder._format_evidence(project_links, questions),
            "projects": Project.objects.filter(organization=email.organization).order_by("code", "id"),
        }

    @staticmethod
    def _base_queryset():
        return (
            EmailMessage.objects.select_related("account")
            .prefetch_related("project_links__project", "questions", "attachments")
            .annotate(question_count=Count("questions", distinct=True))
            .annotate(attachment_count=Count("attachments", distinct=True))
            .order_by("-received_at", "-sent_at", "-created_at", "-id")
        )

    @staticmethod
    def _apply_filter(emails, active_filter):
        if active_filter == "needs_project_confirmation":
            return emails.filter(project_links__status=EmailProjectLink.Status.SUGGESTED).distinct()
        if active_filter == "has_questions":
            return emails.filter(questions__isnull=False).distinct()
        if active_filter == "has_attachments":
            return emails.filter(attachments__isnull=False).distinct()
        if active_filter == "no_project":
            return emails.filter(project_links__isnull=True)
        return emails

    @staticmethod
    def _apply_search(emails, query):
        clean_query = (query or "").strip()
        if not clean_query:
            return emails
        return emails.filter(
            Q(subject__icontains=clean_query)
            | Q(sender_email__icontains=clean_query)
            | Q(sender_name__icontains=clean_query)
            | Q(body_text__icontains=clean_query)
        )

    @staticmethod
    def _filter_links(active_filter, query):
        labels = [
            ("all", "All"),
            ("needs_project_confirmation", "Needs Project Confirmation"),
            ("has_questions", "Has Questions"),
            ("has_attachments", "Has Attachments"),
            ("no_project", "No Project"),
        ]
        return [
            {
                "key": key,
                "label": label,
                "url": f"{reverse('workspace:inbox')}?filter={key}" + (f"&q={query}" if query else ""),
                "active": key == active_filter,
            }
            for key, label in labels
        ]

    @staticmethod
    def _email_row(email):
        project_link = InboxContextBuilder._primary_project_link(email)
        return {
            "id": email.id,
            "detail_url": reverse("workspace:inbox_detail", kwargs={"email_id": email.id}),
            "received_at": InboxContextBuilder._format_datetime(email.received_at or email.sent_at or email.created_at),
            "sender": email.sender_name or email.sender_email or "-",
            "subject": email.subject or email.external_message_id,
            "direction": email.direction,
            "project": project_link.project.code if project_link else "-",
            "project_status": project_link.status if project_link else "no_project",
            "confidence": f"{project_link.confidence}%" if project_link else "-",
            "question_count": email.question_count,
            "attachment_count": email.attachment_count,
            "review_status": InboxContextBuilder._review_status(email, project_link),
            "project_link": InboxContextBuilder._project_link_context(project_link) if project_link else None,
        }

    @staticmethod
    def _primary_project_link(email):
        links = list(email.project_links.all())
        if not links:
            return None
        return sorted(links, key=lambda link: (link.status != EmailProjectLink.Status.CONFIRMED, -link.confidence, link.id))[0]

    @staticmethod
    def _review_status(email, project_link):
        if project_link and project_link.status == EmailProjectLink.Status.SUGGESTED:
            return "needs_review"
        if email.question_count:
            return "info"
        if not project_link:
            return "pending"
        return project_link.status

    @staticmethod
    def _format_datetime(value):
        if not value:
            return "-"
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _format_recipients(recipients):
        if not recipients:
            return "-"
        if isinstance(recipients, list):
            return ", ".join(str(recipient) for recipient in recipients) or "-"
        return str(recipients)

    @staticmethod
    def _format_evidence(project_links, questions):
        evidence = {
            "project_links": [
                {
                    "project": link.project.code,
                    "status": link.status,
                    "confidence": link.confidence,
                    "evidence": link.evidence,
                }
                for link in project_links
            ],
            "questions": [
                {
                    "question": question.question_text,
                    "confidence": question.confidence,
                    "evidence": question.evidence,
                }
                for question in questions
            ],
        }
        return json.dumps(evidence, indent=2, ensure_ascii=False)

    @staticmethod
    def _project_link_context(link):
        return {
            "link": link,
            "project": link.project,
            "status": link.status,
            "confidence": link.confidence,
            "evidence": link.evidence,
            "confirm_url": reverse("workspace:project_link_confirm", kwargs={"link_id": link.id}),
            "reject_url": reverse("workspace:project_link_reject", kwargs={"link_id": link.id}),
            "correct_url": reverse("workspace:project_link_correct", kwargs={"link_id": link.id}),
        }
