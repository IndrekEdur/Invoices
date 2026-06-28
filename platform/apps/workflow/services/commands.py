from dataclasses import dataclass


@dataclass(frozen=True)
class StartWorkflowCommand:
    organization: object
    workflow: object
    entity_type: str
    entity_uuid: object
    metadata: dict | None = None


@dataclass(frozen=True)
class TransitionWorkflowCommand:
    workflow_instance: object
    transition: object
    actor: object = None
    metadata: dict | None = None
