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
        now = fields.Datetime.now()
        # A worker crash must not strand a job in running forever.  Requeue
        # only leases older than 15 minutes; after the normal retry budget the
        # job is left failed for operator review instead of hot-looping.
        stale = self.sudo().search([
            ("state", "=", "running"),
            ("started_at", "<", fields.Datetime.subtract(now, minutes=15)),
        ])
        for job in stale:
            job.write({
                "state": "failed" if job.attempts >= 3 else "pending",
                "error": "RAG worker lease expired; operator review required" if job.attempts >= 3 else "RAG worker lease expired; queued for retry",
                "finished_at": now if job.attempts >= 3 else False,
            })

        # Claim with PostgreSQL row locking so two native worker processes
        # cannot index the same document and emit duplicate side effects.
        try:
            bounded_limit = max(1, min(int(limit or 5), 50))
        except (TypeError, ValueError):
            bounded_limit = 5
        self.env.cr.execute("""
            SELECT id
              FROM ai_document_index_job
             WHERE state = 'pending'
             ORDER BY priority DESC, id
             FOR UPDATE SKIP LOCKED
             LIMIT %s
        """, (bounded_limit,))
        ids = [row[0] for row in self.env.cr.fetchall()]
        jobs = self.sudo().browse(ids)
        for job in jobs:
            job.write({"state": "running", "started_at": now, "attempts": job.attempts + 1})
            try:
                if job.document_id.exists():
                    job.document_id._rag_reindex()
                job.write({"state": "done", "finished_at": fields.Datetime.now(), "error": False})
            except Exception as exc:
                _logger.exception("RAG index job %s failed", job.id)
                if "ai.rag.index.snapshot" in self.env:
                    self.env["ai.rag.index.snapshot"].sudo().search(
                        [
                            ("version", "=", __import__("os").environ.get("AI_RAG_INDEX_VERSION", "rag-v1")),
                            ("company_id", "=", self.env.company.id),
                        ],
                        limit=1,
                    ).write({"status": "failed", "note": str(exc)[:2000]})
                job.write({"state": "failed" if job.attempts >= 3 else "pending", "error": str(exc), "finished_at": fields.Datetime.now()})
        return len(jobs)
