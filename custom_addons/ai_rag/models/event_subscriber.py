import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class AiRagEventSubscriber(models.AbstractModel):
    """First-class RAG subscriber for the durable Control Plane event bus.

    Document writes only publish a domain event. They never call the embedding
    service in the transaction. The event bus materializes a durable delivery,
    and this subscriber creates/merges an asynchronous index job.
    """

    _name = "ai.rag.event.subscriber"
    _description = "RAG Event Subscriber"

    @api.model
    def _handle_event(self, event, payload):
        if event.event_type not in ("document.created", "document.updated"):
            return {"status": "ignored", "event_type": event.event_type}
        if event.aggregate_model != "company.document" or not event.aggregate_id:
            return {"status": "skipped", "reason": "event has no company.document aggregate"}
        doc = self.env["company.document"].sudo().browse(event.aggregate_id).exists()
        if not doc:
            return {"status": "skipped", "reason": "document not found"}
        job = self.env["ai.document.index.job"].sudo().enqueue(doc)
        return {"status": "rag_queued", "job_id": job.id, "event_id": event.id}
