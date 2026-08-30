import json
import uuid
from odoo import api, fields, models


class AiDomainEvent(models.Model):
    _name = "ai.control.event"
    _description = "AI Control Plane Domain Event / Durable Outbox"
    _order = "id desc"

    event_key = fields.Char(required=True, readonly=True, index=True, default=lambda self: str(uuid.uuid4()))
    event_type = fields.Char(required=True, index=True)
    aggregate_model = fields.Char(index=True)
    aggregate_id = fields.Integer(index=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, index=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, index=True)
    payload_json = fields.Text(default="{}")
    correlation_id = fields.Char(index=True)
    causation_id = fields.Char(index=True)
    sequence = fields.Integer(default=0, index=True)
    occurred_at = fields.Datetime(default=fields.Datetime.now, readonly=True, index=True)
    available_at = fields.Datetime(default=fields.Datetime.now, index=True)
    state = fields.Selection([
        ("pending", "Pending"),
        ("dispatching", "Dispatching"),
        ("published", "Published"),
        ("failed", "Failed"),
        ("dead_letter", "Dead Letter"),
    ], default="pending", index=True)
    attempt_count = fields.Integer(default=0)
    next_attempt_at = fields.Datetime(default=fields.Datetime.now, index=True)
    locked_at = fields.Datetime(index=True)
    locked_by = fields.Char(index=True)
    published_at = fields.Datetime()
    error = fields.Text()

    _sql_constraints = [
        ("event_key_unique", "unique(event_key)", "Event key must be unique."),
    ]

    @api.model
    def publish(self, event_type, aggregate=None, payload=None, user=None,
                correlation_id=None, causation_id=None, sequence=0, available_at=None):
        company = self.env.company
        if aggregate is not None and "company_id" in aggregate._fields:
            company = aggregate.company_id or company
        vals = {
            "event_key": str(uuid.uuid4()),
            "event_type": event_type,
            "aggregate_model": aggregate._name if aggregate else False,
            "aggregate_id": aggregate.id if aggregate else False,
            "company_id": company.id,
            "user_id": (user or self.env.user).id,
            "payload_json": json.dumps(payload or {}, ensure_ascii=False, default=str),
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "causation_id": causation_id,
            "sequence": sequence or 0,
            "available_at": available_at or fields.Datetime.now(),
            "next_attempt_at": available_at or fields.Datetime.now(),
            "state": "pending",
        }
        return self.sudo().create(vals)

    def mark_published(self):
        self.write({
            "state": "published",
            "published_at": fields.Datetime.now(),
            "locked_at": False,
            "locked_by": False,
            "error": False,
        })

    def mark_failed(self, error, dead=False):
        self.write({
            "state": "dead_letter" if dead else "failed",
            "error": str(error)[:10000],
            "locked_at": False,
            "locked_by": False,
        })
