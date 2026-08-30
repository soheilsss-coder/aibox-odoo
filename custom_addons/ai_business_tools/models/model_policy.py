from odoo import api, fields, models


class AiGatewayModelPolicy(models.Model):
    """Explicit allowlist of (model, operation) pairs that may be
    called through the generic /api/rpc pass-through.

    This is a SECOND, independent gate on top of Odoo's own
    ir.model.access / record rules - not a replacement for them. Odoo's
    ACL answers "is this user allowed to do this at all"; this table
    answers the separate question "should the AI-facing gateway ever
    expose this model/operation, regardless of who is asking". A model
    can be perfectly readable by base.group_user for normal HR/ops
    reasons and still not belong on this list, because nothing about
    day-to-day Odoo use implies it should be reachable from a chat
    endpoint.

    Deny-by-default: if a (model, operation) pair is not in this table
    and active, /api/rpc refuses it before Odoo's ACL is even checked.
    """

    _name = "ai.gateway.model.policy"
    _description = "AI Gateway Model Allowlist"
    _rec_name = "model_name"

    model_name = fields.Char(required=True, index=True)
    operation = fields.Selection(
        [
            ("fields", "fields"), ("get_views", "get_views"),
            ("search_read", "search_read"), ("read", "read"),
            ("search_count", "search_count"),
            ("create", "create"), ("write", "write"), ("unlink", "unlink"),
        ],
        required=True,
    )
    active = fields.Boolean(default=True)
    notes = fields.Char()

    _sql_constraints = [
        ("model_op_unique", "unique(model_name, operation)",
         "This model/operation pair is already listed."),
    ]

    @api.model
    def is_allowed(self, model_name, operation):
        return bool(self.sudo().search_count([
            ("model_name", "=", model_name),
            ("operation", "=", operation),
            ("active", "=", True),
        ]))
