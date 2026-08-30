import json
from odoo.tests.common import TransactionCase

class TestDurableWorkflowContract(TransactionCase):
    def test_definition_supports_durable_primitives(self):
        Flow = self.env["ai.workflow"]
        flow = Flow.create({
            "name": "Contract",
            "code": "contract.workflow",
            "trigger_event": "contract.created",
            "state": "active",
            "definition_json": json.dumps({"steps": [
                {"action": "condition", "if": {"value": "$amount", "operator": "gte", "compare": 100}},
                {"action": "approval", "approval_code": "finance.approve"},
                {"action": "wait", "seconds": 1},
                {"action": "event", "event_type": "contract.approved"},
            ]}),
        })
        self.assertTrue(flow.validate_definition())

    def test_run_idempotency(self):
        event = self.env["ai.control.event"].publish(
            "contract.created", payload={"amount": 100}, user=self.env.user
        )
        flow = self.env["ai.workflow"].create({
            "name": "Idempotent", "code": "idempotent.workflow",
            "trigger_event": "contract.created", "state": "active",
            "definition_json": json.dumps({"steps": [{"action": "noop"}]}),
        })
        first = self.env["ai.workflow.run"].enqueue_for_event(event)
        second = self.env["ai.workflow.run"].enqueue_for_event(event)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)
