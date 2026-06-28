from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.services import AuditService

from ..models import WorkflowEvent, WorkflowInstance


class WorkflowEngine:
    """Central service for executing generic workflows.

    The engine understands workflow definitions, states, transitions,
    instances, and execution events. It intentionally does not know about
    invoices, documents, suppliers, payments, or other business domains.
    """

    @staticmethod
    def start(command):
        initial_state = command.workflow.states.filter(is_initial=True).first()
        if initial_state is None:
            raise ValidationError({"workflow": "Workflow must have an initial state."})

        metadata = dict(command.metadata or {})

        with transaction.atomic():
            instance = WorkflowInstance.objects.create(
                organization=command.organization,
                workflow=command.workflow,
                current_state=initial_state,
                entity_type=command.entity_type,
                entity_uuid=command.entity_uuid,
                metadata=metadata,
            )

            WorkflowEvent.objects.create(
                workflow_instance=instance,
                state=initial_state,
                event_type=WorkflowEvent.Type.WORKFLOW_STARTED,
                message="Workflow started.",
                metadata=metadata,
            )
            WorkflowEvent.objects.create(
                workflow_instance=instance,
                state=initial_state,
                event_type=WorkflowEvent.Type.STATE_ENTERED,
                message=f"Entered state {initial_state.code}.",
                metadata={"state": initial_state.code},
            )
            AuditService.record(
                event_type="workflow.started",
                message=f"Workflow started: {command.workflow.code}",
                organization=command.organization,
                object_type="WorkflowInstance",
                object_id=str(instance.uuid),
                metadata={
                    "workflow": command.workflow.code,
                    "entity_type": command.entity_type,
                    "entity_uuid": str(command.entity_uuid),
                },
            )

            return instance

    @staticmethod
    def can_transition(instance, transition):
        return transition.from_state_id == instance.current_state_id

    @staticmethod
    def transition(command):
        instance = command.workflow_instance
        transition = command.transition

        if not WorkflowEngine.can_transition(instance, transition):
            raise ValidationError({"transition": "Transition is not valid from the current state."})

        metadata = dict(command.metadata or {})
        from_state = instance.current_state
        to_state = transition.to_state

        with transaction.atomic():
            WorkflowEvent.objects.create(
                workflow_instance=instance,
                transition=transition,
                state=from_state,
                event_type=WorkflowEvent.Type.STATE_EXITED,
                message=f"Exited state {from_state.code}.",
                metadata={"state": from_state.code, **metadata},
                created_by=command.actor,
            )

            instance.current_state = to_state
            instance.save(update_fields=["current_state", "updated_at"])

            WorkflowEvent.objects.create(
                workflow_instance=instance,
                transition=transition,
                state=to_state,
                event_type=WorkflowEvent.Type.TRANSITION_EXECUTED,
                message=f"Executed transition {transition.code}.",
                metadata={
                    "transition": transition.code,
                    "from_state": from_state.code,
                    "to_state": to_state.code,
                    **metadata,
                },
                created_by=command.actor,
            )
            WorkflowEvent.objects.create(
                workflow_instance=instance,
                transition=transition,
                state=to_state,
                event_type=WorkflowEvent.Type.STATE_ENTERED,
                message=f"Entered state {to_state.code}.",
                metadata={"state": to_state.code, **metadata},
                created_by=command.actor,
            )
            AuditService.record(
                event_type="workflow.transitioned",
                message=f"Workflow transition executed: {transition.code}",
                organization=instance.organization,
                actor=command.actor,
                object_type="WorkflowInstance",
                object_id=str(instance.uuid),
                metadata={
                    "workflow": instance.workflow.code,
                    "transition": transition.code,
                    "from_state": from_state.code,
                    "to_state": to_state.code,
                },
            )

            return instance

    @staticmethod
    def complete(instance):
        with transaction.atomic():
            instance.completed_at = timezone.now()
            instance.save(update_fields=["completed_at", "updated_at"])

            WorkflowEvent.objects.create(
                workflow_instance=instance,
                state=instance.current_state,
                event_type=WorkflowEvent.Type.WORKFLOW_COMPLETED,
                message="Workflow completed.",
            )
            AuditService.record(
                event_type="workflow.completed",
                message=f"Workflow completed: {instance.workflow.code}",
                organization=instance.organization,
                object_type="WorkflowInstance",
                object_id=str(instance.uuid),
                metadata={"workflow": instance.workflow.code},
            )

            return instance

    @staticmethod
    def cancel(instance):
        with transaction.atomic():
            WorkflowEvent.objects.create(
                workflow_instance=instance,
                state=instance.current_state,
                event_type=WorkflowEvent.Type.WORKFLOW_CANCELLED,
                message="Workflow cancelled.",
            )
            AuditService.record(
                event_type="workflow.cancelled",
                message=f"Workflow cancelled: {instance.workflow.code}",
                organization=instance.organization,
                object_type="WorkflowInstance",
                object_id=str(instance.uuid),
                metadata={"workflow": instance.workflow.code},
            )

            return instance
