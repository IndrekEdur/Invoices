from apps.communications.dto import ConversationContext

from ..models import EmailProjectLink


class ConversationContextBuilder:
    """Builds read-only conversation context for future reasoning services."""

    @staticmethod
    def build(command):
        email_message = command.email_message
        metadata = dict(command.metadata or {})

        thread_messages = ConversationContextBuilder._thread_messages(email_message, command.include_thread)
        project_links = ConversationContextBuilder._project_links(email_message, command.include_projects)
        questions = ConversationContextBuilder._questions(email_message, command.include_questions)
        attachments = ConversationContextBuilder._attachments(email_message, command.include_attachments)
        documents = [attachment.document for attachment in attachments if attachment.document_id]

        confirmed_projects = [
            link.project for link in project_links if link.status == EmailProjectLink.Status.CONFIRMED
        ]
        suggested_projects = [
            link.project for link in project_links if link.status == EmailProjectLink.Status.SUGGESTED
        ]
        evidence = ConversationContextBuilder._evidence(project_links, questions)

        return ConversationContext(
            email_message=email_message,
            thread_messages=thread_messages,
            project_links=project_links,
            confirmed_projects=confirmed_projects,
            suggested_projects=suggested_projects,
            questions=questions,
            attachments=attachments,
            documents=documents,
            evidence=evidence,
            metadata=metadata,
        )

    @staticmethod
    def _thread_messages(email_message, include_thread):
        if not include_thread:
            return []
        if email_message.thread_id is None:
            return [email_message]

        return list(
            email_message.thread.messages.filter(organization=email_message.organization).order_by(
                "received_at",
                "sent_at",
                "created_at",
                "id",
            )
        )

    @staticmethod
    def _project_links(email_message, include_projects):
        if not include_projects:
            return []

        return list(
            email_message.project_links.filter(organization=email_message.organization)
            .select_related("project")
            .order_by("project__code", "id")
        )

    @staticmethod
    def _questions(email_message, include_questions):
        if not include_questions:
            return []

        return list(email_message.questions.filter(organization=email_message.organization).order_by("-confidence", "id"))

    @staticmethod
    def _attachments(email_message, include_attachments):
        if not include_attachments:
            return []

        return list(
            email_message.attachments.filter(organization=email_message.organization)
            .select_related("document")
            .order_by("original_filename", "id")
        )

    @staticmethod
    def _evidence(project_links, questions):
        evidence = []

        for link in project_links:
            if link.evidence:
                evidence.append(
                    {
                        "source": "project_link",
                        "project_id": link.project_id,
                        "status": link.status,
                        "confidence": link.confidence,
                        "evidence": dict(link.evidence),
                    }
                )

        for question in questions:
            if question.evidence:
                evidence.append(
                    {
                        "source": "question",
                        "question_id": question.id,
                        "confidence": question.confidence,
                        "evidence": dict(question.evidence),
                    }
                )

        return evidence
