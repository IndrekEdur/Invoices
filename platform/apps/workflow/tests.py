from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from .models import WorkflowDefinition, WorkflowState, WorkflowTransition


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
