from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProjectKnowledge:
    """Read-only project knowledge context for future reasoning services."""

    project: object
    parties: tuple = field(default_factory=tuple)
    addresses: tuple = field(default_factory=tuple)
    emails: tuple = field(default_factory=tuple)
    threads: tuple = field(default_factory=tuple)
    conversation_contexts: tuple = field(default_factory=tuple)
    questions: tuple = field(default_factory=tuple)
    answer_drafts: tuple = field(default_factory=tuple)
    attachments: tuple = field(default_factory=tuple)
    documents: tuple = field(default_factory=tuple)
    workflow_instances: tuple = field(default_factory=tuple)
    workflow_events: tuple = field(default_factory=tuple)
    audit_events: tuple = field(default_factory=tuple)
    evidence: tuple = field(default_factory=tuple)
    timeline: tuple = field(default_factory=tuple)
    metadata: dict | None = None
