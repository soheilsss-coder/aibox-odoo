import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AiDocumentIndexJob(models.Model):
    _name = "ai.document.index.job"
    _description = "Asynchronous RAG Index Job"
    _order = "priority desc, create_date"

    document_id = fields.Many2one("company.document", required=True, ondelete="cascade", index=True)
    state = fields.Selection([("pending", "Pending"), ("running", "Running"), ("done", "Done"), ("failed", "Failed")], default="pending", index=True)
    attempts = fields.Integer(default=0)
    priority = fields.Integer(default=10)
    error = fields.Text()
    started_at = fields.Datetime()
    finished_at = fields.Datetime()

    @api.model
    def enqueue(self, document):
        existing = self.sudo().search([("document_id", "=", document.id), ("state", "in", ("pending", "running"))], limit=1)
        if existing:
            return existing
        return self.sudo().create({"document_id": document.id})

    @api.model
    def process(self, limit=5):
        jobs = self.sudo().search([("state", "=", "pending")], order="priority desc, id", limit=limit)
        for job in jobs:
            job.write({"state": "running", "started_at": fields.Datetime.now(), "attempts": job.attempts + 1})
            try:
                if job.document_id.exists():
                    job.document_id._rag_reindex()
                job.write({"state": "done", "finished_at": fields.Datetime.now(), "error": False})
            except Exception as exc:
                _logger.exception("RAG index job %s failed", job.id)
                job.write({"state": "failed" if job.attempts >= 3 else "pending", "error": str(exc), "finished_at": fields.Datetime.now()})
        return len(jobs)
