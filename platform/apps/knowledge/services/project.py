from apps.communications.models import EmailAnswerDraft, EmailProjectLink
from apps.communications.services import BuildConversationContextCommand, ConversationContextBuilder
from apps.core.models import AuditEvent
from apps.documents.models import Document
from apps.knowledge.dto import ProjectKnowledge
from apps.workflow.models import WorkflowEvent, WorkflowInstance


class ProjectKnowledgeBuilder:
    """Builds read-only project knowledge without creating or mutating records."""

    @staticmethod
    def build(command):
        project = command.project
        organization = project.organization
        metadata = dict(command.metadata or {})

        parties = tuple(project.parties.filter(organization=organization).order_by("role", "name", "id"))
        addresses = tuple(project.addresses.filter(organization=organization).order_by("address_type", "id"))

        email_links = ProjectKnowledgeBuilder._email_links(project, command.include_conversations)
        emails = tuple(link.email_message for link in email_links)
        threads = ProjectKnowledgeBuilder._threads(emails)
        conversation_contexts = ProjectKnowledgeBuilder._conversation_contexts(emails, command.include_conversations)
        questions = ProjectKnowledgeBuilder._questions(conversation_contexts)
        answer_drafts = ProjectKnowledgeBuilder._answer_drafts(emails, command.include_conversations)
        attachments = ProjectKnowledgeBuilder._attachments(conversation_contexts, command.include_documents)
        documents = ProjectKnowledgeBuilder._documents(project, attachments, command.include_documents)
        workflow_instances = ProjectKnowledgeBuilder._workflow_instances(project, documents, command.include_workflow)
        workflow_events = ProjectKnowledgeBuilder._workflow_events(workflow_instances, command.include_workflow)
        audit_events = ProjectKnowledgeBuilder._audit_events(
            project,
            emails,
            documents,
            workflow_instances,
            command.include_audit,
        )
        evidence = ProjectKnowledgeBuilder._evidence(email_links, questions, answer_drafts)
        timeline = ProjectKnowledgeBuilder._timeline(
            emails=emails,
            questions=questions,
            answer_drafts=answer_drafts,
            documents=documents,
            workflow_events=workflow_events,
            audit_events=audit_events,
        )

        return ProjectKnowledge(
            project=project,
            parties=parties,
            addresses=addresses,
            emails=emails,
            threads=threads,
            conversation_contexts=conversation_contexts,
            questions=questions,
            answer_drafts=answer_drafts,
            attachments=attachments,
            documents=documents,
            workflow_instances=workflow_instances,
            workflow_events=workflow_events,
            audit_events=audit_events,
            evidence=evidence,
            timeline=timeline,
            metadata=metadata,
        )

    @staticmethod
    def _email_links(project, include_conversations):
        if not include_conversations:
            return tuple()

        return tuple(
            EmailProjectLink.objects.filter(organization=project.organization, project=project)
            .select_related("email_message", "email_message__thread")
            .order_by("email_message__received_at", "email_message__sent_at", "email_message__created_at", "id")
        )

    @staticmethod
    def _threads(emails):
        seen = set()
        threads = []

        for email in emails:
            if email.thread_id and email.thread_id not in seen:
                seen.add(email.thread_id)
                threads.append(email.thread)

        return tuple(threads)

    @staticmethod
    def _conversation_contexts(emails, include_conversations):
        if not include_conversations:
            return tuple()

        return tuple(
            ConversationContextBuilder.build(
                BuildConversationContextCommand(email_message=email)
            )
            for email in emails
        )

    @staticmethod
    def _questions(conversation_contexts):
        return ProjectKnowledgeBuilder._unique_by_id(
            question
            for context in conversation_contexts
            for question in context.questions
        )

    @staticmethod
    def _answer_drafts(emails, include_conversations):
        if not include_conversations:
            return tuple()

        email_ids = [email.id for email in emails]
        if not email_ids:
            return tuple()

        return tuple(
            EmailAnswerDraft.objects.filter(
                organization=emails[0].organization,
                email_message_id__in=email_ids,
            ).order_by("created_at", "id")
        )

    @staticmethod
    def _attachments(conversation_contexts, include_documents):
        if not include_documents:
            return tuple()

        return ProjectKnowledgeBuilder._unique_by_id(
            attachment
            for context in conversation_contexts
            for attachment in context.attachments
        )

    @staticmethod
    def _documents(project, attachments, include_documents):
        if not include_documents:
            return tuple()

        attached_document_ids = [
            attachment.document_id
            for attachment in attachments
            if attachment.document_id
        ]

        documents_by_id = {
            document.id: document
            for document in Document.objects.filter(
                organization=project.organization,
                id__in=attached_document_ids,
            ).order_by("created_at", "id")
        }

        return tuple(documents_by_id.values())

    @staticmethod
    def _workflow_instances(project, documents, include_workflow):
        if not include_workflow:
            return tuple()

        entity_filters = [
            ("project", project.uuid),
            *[("document", document.uuid) for document in documents],
        ]

        instances = []
        for entity_type, entity_uuid in entity_filters:
            instances.extend(
                WorkflowInstance.objects.filter(
                    organization=project.organization,
                    entity_type=entity_type,
                    entity_uuid=entity_uuid,
                )
                .select_related("workflow", "current_state")
                .order_by("created_at", "id")
            )

        return tuple(instances)

    @staticmethod
    def _workflow_events(workflow_instances, include_workflow):
        if not include_workflow or not workflow_instances:
            return tuple()

        return tuple(
            WorkflowEvent.objects.filter(workflow_instance__in=workflow_instances)
            .select_related("workflow_instance", "state", "transition")
            .order_by("created_at", "id")
        )

    @staticmethod
    def _audit_events(project, emails, documents, workflow_instances, include_audit):
        if not include_audit:
            return tuple()

        object_refs = [("Project", str(project.id))]
        object_refs.extend(("EmailMessage", str(email.id)) for email in emails)
        object_refs.extend(("Document", str(document.id)) for document in documents)
        object_refs.extend(("WorkflowInstance", str(instance.id)) for instance in workflow_instances)

        audit_events = []
        for object_type, object_id in object_refs:
            audit_events.extend(
                AuditEvent.objects.filter(
                    organization=project.organization,
                    object_type=object_type,
                    object_id=object_id,
                ).order_by("created_at", "id")
            )

        return tuple(audit_events)

    @staticmethod
    def _evidence(email_links, questions, answer_drafts):
        evidence = []

        for link in email_links:
            if link.evidence:
                evidence.append(
                    {
                        "source": "email_project_link",
                        "source_id": link.id,
                        "project_id": link.project_id,
                        "email_message_id": link.email_message_id,
                        "status": link.status,
                        "confidence": link.confidence,
                        "evidence": dict(link.evidence),
                    }
                )

        for question in questions:
            if question.evidence:
                evidence.append(
                    {
                        "source": "email_question",
                        "source_id": question.id,
                        "email_message_id": question.email_message_id,
                        "confidence": question.confidence,
                        "evidence": dict(question.evidence),
                    }
                )

        for draft in answer_drafts:
            if draft.evidence:
                evidence.append(
                    {
                        "source": "email_answer_draft",
                        "source_id": draft.id,
                        "email_message_id": draft.email_message_id,
                        "evidence": dict(draft.evidence),
                    }
                )

        return tuple(evidence)

    @staticmethod
    def _timeline(*, emails, questions, answer_drafts, documents, workflow_events, audit_events):
        entries = []

        for email in emails:
            entries.append(
                {
                    "type": "email",
                    "object": email,
                    "timestamp": email.received_at or email.sent_at or email.created_at,
                }
            )

        for question in questions:
            entries.append({"type": "question", "object": question, "timestamp": question.created_at})

        for draft in answer_drafts:
            entries.append({"type": "answer_draft", "object": draft, "timestamp": draft.created_at})

        for document in documents:
            entries.append({"type": "document", "object": document, "timestamp": document.created_at})

        for event in workflow_events:
            entries.append({"type": "workflow_event", "object": event, "timestamp": event.created_at})

        for event in audit_events:
            entries.append({"type": "audit_event", "object": event, "timestamp": event.created_at})

        return tuple(sorted(entries, key=lambda entry: (entry["timestamp"], entry["type"])))

    @staticmethod
    def _unique_by_id(objects):
        seen = set()
        unique = []

        for obj in objects:
            if obj.id in seen:
                continue
            seen.add(obj.id)
            unique.append(obj)

        return tuple(unique)
