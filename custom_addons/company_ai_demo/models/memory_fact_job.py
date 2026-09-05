from __future__ import annotations

import logging

from odoo import api, fields, models

from .memory_fact_extractor import extract_candidates, plain_message

_logger = logging.getLogger(__name__)


def _safe_datetime(value):
    if not value:
        return False
    try:
        return fields.Datetime.to_datetime(value)
    except (TypeError, ValueError):
        return False


class AiAgentMemoryFactJob(models.Model):
    _name = "ai.agent.memory.fact.job"
    _description = "Asynchronous Structured Memory Extraction Job"
    _order = "priority desc, id"

    message_id = fields.Many2one("mail.message", required=True, ondelete="cascade", index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", required=True, ondelete="cascade", index=True)
    thread_id = fields.Integer(index=True)
    state = fields.Selection([
        ("pending", "Pending"), ("running", "Running"),
        ("done", "Done"), ("failed", "Failed"),
    ], default="pending", required=True, index=True)
    attempts = fields.Integer(default=0)
    priority = fields.Integer(default=10)
    error = fields.Char()
    extracted_count = fields.Integer(default=0)
    started_at = fields.Datetime()
    finished_at = fields.Datetime()

    _sql_constraints = [
        ("memory_fact_message_unique", "unique(message_id)", "A message can be extracted only once."),
    ]

    @api.model
    def enqueue(self, message, user=None, thread_id=None):
        message = message.exists()
        if not message:
            return self.browse()
        user = user or self.env.user
        existing = self.sudo().search([("message_id", "=", message.id)], limit=1)
        if existing:
            return existing
        return self.sudo().create({
            "message_id": message.id,
            "user_id": user.id,
            "company_id": user.company_id.id,
            "thread_id": thread_id or (message.res_id if message.model == "llm.thread" else False),
        })

    @api.model
    def process(self, limit=5):
        try:
            limit = max(1, min(int(limit or 5), 50))
        except (TypeError, ValueError):
            limit = 5
        now = fields.Datetime.now()
        stale = self.sudo().search([
            ("state", "=", "running"),
            ("started_at", "<", fields.Datetime.subtract(now, minutes=15)),
        ])
        for job in stale:
            job.write({
                "state": "failed" if job.attempts >= 3 else "pending",
                "error": "memory extraction lease expired",
                "finished_at": now if job.attempts >= 3 else False,
            })
        self.env.cr.execute(
            """
            SELECT id FROM ai_agent_memory_fact_job
            WHERE state = 'pending'
            ORDER BY priority DESC, id
            LIMIT %s FOR UPDATE SKIP LOCKED
            """,
            (limit,),
        )
        jobs = self.sudo().browse([row[0] for row in self.env.cr.fetchall()])
        for job in jobs:
            job.write({"state": "running", "attempts": job.attempts + 1, "started_at": now})
            try:
                message = job.message_id.exists()
                if not message:
                    job.write({"state": "done", "finished_at": fields.Datetime.now(), "extracted_count": 0})
                    continue
                with self.env.cr.savepoint():
                    candidates = extract_candidates(plain_message(message.body or ""), env=self.env)
                    Fact = self.env["ai.agent.memory.fact"]
                    count = 0
                    for candidate in candidates:
                        Fact.create_fact(
                            candidate["subject"], candidate["predicate"], candidate["value"],
                            scope="personal", user=job.user_id, confirmed=False,
                            confidence=candidate["confidence"],
                            source_message_id=message.id, source_thread_id=job.thread_id,
                            source_quote=candidate["source_quote"],
                            source_type="assistant_extraction",
                            object_type=candidate.get("object_type", "text"),
                            valid_from=_safe_datetime(candidate.get("valid_from")),
                            valid_to=_safe_datetime(candidate.get("valid_to")),
                        )
                        count += 1
                job.write({
                    "state": "done", "finished_at": fields.Datetime.now(),
                    "extracted_count": count, "error": False,
                })
            except Exception as exc:  # noqa: BLE001
                _logger.exception("memory fact extraction job %s failed", job.id)
                job.write({
                    "state": "failed" if job.attempts >= 3 else "pending",
                    "finished_at": fields.Datetime.now(), "error": str(exc)[:250],
                })
        return len(jobs)
