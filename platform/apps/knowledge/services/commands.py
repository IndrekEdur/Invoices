from dataclasses import dataclass


@dataclass(frozen=True)
class BuildProjectKnowledgeCommand:
    project: object
    include_conversations: bool = True
    include_documents: bool = True
    include_workflow: bool = True
    include_audit: bool = True
    metadata: dict | None = None
