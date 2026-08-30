from odoo.tests.common import TransactionCase


class TestEventSubscriberContract(TransactionCase):
    def test_rejects_arbitrary_method(self):
        Sub = self.env["ai.integration.subscription"]
        with self.assertRaises(ValueError):
            Sub.create({
                "event_type": "test.secure",
                "target": "audit",
                "handler_key": "bad",
                "subscriber_model": "res.users",
                "subscriber_method": "write",
            })

    def test_delivery_uses_explicit_subscriber_contract(self):
        # ai.integration.event.dispatcher itself exposes a contract-compatible
        # method for this test. A real deployment should point subscriptions at
        # dedicated subscriber models owned by the consuming integration.
        Sub = self.env["ai.integration.subscription"]
        sub = Sub.create({
            "event_type": "test.contract",
            "target": "audit",
            "handler_key": "dispatcher-contract",
            "subscriber_model": "ai.integration.event.dispatcher",
            "subscriber_method": "_handle_audit",
        })
        event = self.env["ai.control.event"].publish(
            "test.contract", payload={"ok": True}, user=self.env.user
        )
        self.env["ai.integration.event.dispatcher"]._materialize_events(limit=10, worker="test")
        delivery = self.env["ai.integration.event.delivery"].search([
            ("event_id", "=", event.id), ("subscription_id", "=", sub.id)
        ], limit=1)
        self.assertTrue(delivery)
        self.env["ai.integration.event.dispatcher"]._process_deliveries(limit=10, worker="test")
        self.assertEqual(delivery.state, "succeeded")
