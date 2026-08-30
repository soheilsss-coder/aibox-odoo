from odoo.tests.common import TransactionCase


class TestDurableEventBus(TransactionCase):
    def test_event_has_stable_identity_and_delivery_is_idempotent(self):
        event = self.env["ai.control.event"].publish(
            "test.event", payload={"value": 1}, user=self.env.user
        )
        dispatcher = self.env["ai.integration.event.dispatcher"]
        dispatcher._materialize_events(limit=10, worker="test")
        delivery_model = self.env["ai.integration.event.delivery"]
        deliveries = delivery_model.search([("event_id", "=", event.id)])
        self.assertTrue(event.event_key)
        # Re-materialization must not duplicate the same subscriber deliveries.
        dispatcher._materialize_events(limit=10, worker="test")
        self.assertEqual(
            delivery_model.search_count([("event_id", "=", event.id)]), len(deliveries)
        )

    def test_claim_uses_durable_delivery_state(self):
        event = self.env["ai.control.event"].publish(
            "approval.approved", payload={"approval_id": 123}, user=self.env.user
        )
        self.env["ai.integration.event.dispatcher"]._materialize_events(limit=10, worker="test")
        deliveries = self.env["ai.integration.event.delivery"].search([("event_id", "=", event.id)])
        self.assertTrue(deliveries)
        self.assertTrue(all(d.state in ("queued", "retry", "running", "succeeded", "dead_letter") for d in deliveries))
