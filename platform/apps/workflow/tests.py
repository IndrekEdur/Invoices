import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from apps.core.services import CreateOrganizationCommand, OrganizationService

from .models import WorkflowDefinition, WorkflowEvent, WorkflowInstance, WorkflowState, WorkflowTransition


def create_organization(name="Workflow Org"):
    return OrganizationService.create(CreateOrganizationCommand(name=name))


def create_workflow_instance():
    organization = create_organization()
    workflow = WorkflowDefinition.objects.create(code=f"workflow-{uuid.uuid4()}", name="Workflow")
    initial_state = WorkflowState.objects.create(workflow=workflow, code="new", name="New", is_initial=True)
    instance = WorkflowInstance.objects.create(
        organization=organization,
        workflow=workflow,
        current_state=initial_state,
        entity_type="ExampleEntity",
        entity_uuid=uuid.uuid4(),
    )
    return instance, initial_state


class WorkflowStateMachineModelTests(TestCase):
    def test_workflow_creation(self):
        workflow = WorkflowDefinition.objects.create(
            code="generic-review",
            name="Generic review",
            description="Reusable review workflow.",
            metadata={"scope": "test"},
        )

        self.assertIsNotNone(workflow.id)
        self.assertIsNotNone(workflow.uuid)
        self.assertTrue(workflow.is_active)
        self.assertEqual(workflow.metadata, {"scope": "test"})

    def test_state_creation(self):
        workflow = WorkflowDefinition.objects.create(code="state-test", name="State test")

        state = WorkflowState.objects.create(workflow=workflow, code="new", name="New", is_initial=True)

        self.assertEqual(state.workflow, workflow)
        self.assertTrue(state.is_initial)
        self.assertFalse(state.is_terminal)

    def test_transition_creation(self):
        workflow = WorkflowDefinition.objects.create(code="transition-test", name="Transition test")
        new_state = WorkflowState.objects.create(workflow=workflow, code="new", name="New", is_initial=True)
        done_state = WorkflowState.objects.create(workflow=workflow, code="done", name="Done", is_terminal=True)

        transition = WorkflowTransition.objects.create(
            workflow=workflow,
            from_state=new_state,
            to_state=done_state,
            code="complete",
            name="Complete",
            metadata={"button": "Complete"},
        )

        self.assertEqual(transition.from_state, new_state)
        self.assertEqual(transition.to_state, done_state)
        self.assertEqual(transition.metadata, {"button": "Complete"})

    def test_only_one_initial_state_validation(self):
        workflow = WorkflowDefinition.objects.create(code="initial-test", name="Initial test")
        WorkflowState.objects.create(workflow=workflow, code="new", name="New", is_initial=True)

        with self.assertRaises(IntegrityError):
            WorkflowState.objects.create(workflow=workflow, code="draft", name="Draft", is_initial=True)

    def test_transition_must_reference_same_workflow(self):
        workflow = WorkflowDefinition.objects.create(code="workflow-a", name="Workflow A")
        other_workflow = WorkflowDefinition.objects.create(code="workflow-b", name="Workflow B")
        from_state = WorkflowState.objects.create(workflow=workflow, code="new", name="New", is_initial=True)
        to_state = WorkflowState.objects.create(workflow=other_workflow, code="done", name="Done", is_initial=True)

        with self.assertRaises(ValidationError):
            WorkflowTransition.objects.create(
                workflow=workflow,
                from_state=from_state,
                to_state=to_state,
                code="invalid",
                name="Invalid",
            )

    def test_str_methods(self):
        workflow = WorkflowDefinition.objects.create(code="string-test", name="String test")
        new_state = WorkflowState.objects.create(workflow=workflow, code="new", name="New", is_initial=True)
        done_state = WorkflowState.objects.create(workflow=workflow, code="done", name="Done", is_terminal=True)
        transition = WorkflowTransition.objects.create(
            workflow=workflow,
            from_state=new_state,
            to_state=done_state,
            code="complete",
            name="Complete",
        )

        self.assertEqual(str(workflow), "String test")
        self.assertEqual(str(new_state), "string-test:new")
        self.assertEqual(str(transition), "string-test:complete")


class WorkflowInstanceModelTests(TestCase):
    def test_create_instance(self):
        organization = create_organization()
        workflow = WorkflowDefinition.objects.create(code="instance-test", name="Instance test")
        initial_state = WorkflowState.objects.create(workflow=workflow, code="new", name="New", is_initial=True)
        entity_uuid = uuid.uuid4()

        instance = WorkflowInstance.objects.create(
            organization=organization,
            workflow=workflow,
            current_state=initial_state,
            entity_type="ExampleEntity",
            entity_uuid=entity_uuid,
            metadata={"source": "test"},
        )

        self.assertIsNotNone(instance.id)
        self.assertIsNotNone(instance.uuid)
        self.assertEqual(instance.organization, organization)
        self.assertEqual(instance.metadata, {"source": "test"})

    def test_current_state_validation(self):
        organization = create_organization()
        workflow = WorkflowDefinition.objects.create(code="instance-workflow-a", name="Workflow A")
        other_workflow = WorkflowDefinition.objects.create(code="instance-workflow-b", name="Workflow B")
        initial_state = WorkflowState.objects.create(workflow=other_workflow, code="new", name="New", is_initial=True)

        with self.assertRaises(ValidationError):
            WorkflowInstance.objects.create(
                organization=organization,
                workflow=workflow,
                current_state=initial_state,
                entity_type="ExampleEntity",
                entity_uuid=uuid.uuid4(),
            )

    def test_completed_at_nullable(self):
        organization = create_organization()
        workflow = WorkflowDefinition.objects.create(code="nullable-completed", name="Nullable completed")
        initial_state = WorkflowState.objects.create(workflow=workflow, code="new", name="New", is_initial=True)

        instance = WorkflowInstance.objects.create(
            organization=organization,
            workflow=workflow,
            current_state=initial_state,
            entity_type="ExampleEntity",
            entity_uuid=uuid.uuid4(),
        )

        self.assertIsNone(instance.completed_at)

    def test_str(self):
        organization = create_organization()
        workflow = WorkflowDefinition.objects.create(code="instance-string", name="Instance string")
        initial_state = WorkflowState.objects.create(workflow=workflow, code="new", name="New", is_initial=True)
        entity_uuid = uuid.uuid4()

        instance = WorkflowInstance.objects.create(
            organization=organization,
            workflow=workflow,
            current_state=initial_state,
            entity_type="ExampleEntity",
            entity_uuid=entity_uuid,
        )

        self.assertEqual(str(instance), f"instance-string:ExampleEntity:{entity_uuid}")


class WorkflowEventModelTests(TestCase):
    def test_create_workflow_event(self):
        instance, state = create_workflow_instance()

        event = WorkflowEvent.objects.create(
            workflow_instance=instance,
            state=state,
            event_type=WorkflowEvent.Type.WORKFLOW_STARTED,
            message="Workflow started.",
        )

        self.assertIsNotNone(event.id)
        self.assertIsNotNone(event.uuid)
        self.assertEqual(event.workflow_instance, instance)
        self.assertEqual(event.state, state)

    def test_transition_nullable(self):
        instance, state = create_workflow_instance()

        event = WorkflowEvent.objects.create(
            workflow_instance=instance,
            state=state,
            event_type=WorkflowEvent.Type.STATE_ENTERED,
        )

        self.assertIsNone(event.transition)

    def test_created_by_nullable(self):
        instance, state = create_workflow_instance()

        event = WorkflowEvent.objects.create(
            workflow_instance=instance,
            state=state,
            event_type=WorkflowEvent.Type.STATE_ENTERED,
        )

        self.assertIsNone(event.created_by)

    def test_metadata_stored(self):
        instance, state = create_workflow_instance()

        event = WorkflowEvent.objects.create(
            workflow_instance=instance,
            state=state,
            event_type=WorkflowEvent.Type.POLICY_APPROVED,
            metadata={"policy": "auto_approval", "result": "approved"},
        )

        self.assertEqual(event.metadata["policy"], "auto_approval")
        self.assertEqual(event.metadata["result"], "approved")

    def test_str(self):
        instance, state = create_workflow_instance()
        user = get_user_model().objects.create_user(username="workflow-user")

        event = WorkflowEvent.objects.create(
            workflow_instance=instance,
            state=state,
            event_type=WorkflowEvent.Type.MANUAL_OVERRIDE,
            created_by=user,
        )

        self.assertEqual(str(event), f"{instance}:manual_override")
