from odoo import fields, models

class AiGatewayApprovalHistory(models.Model):
    _name = "ai.gateway.approval.history"
    _description = "Immutable Approval History"
    _order = "event_at desc"
    approval_id = fields.Many2one("ai.gateway.approval", required=True, ondelete="cascade", index=True)
    event = fields.Selection([( "created", "Created"), ("approved", "Approved"), ("rejected", "Rejected"), ("cancelled", "Cancelled"), ("executing", "Executing"), ("expired", "Expired")], required=True)
    actor_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    event_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    note = fields.Text()
    state_before = fields.Char()
    state_after = fields.Char()
