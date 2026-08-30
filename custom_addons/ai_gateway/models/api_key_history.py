from odoo import fields, models

class AiGatewayApiKeyHistory(models.Model):
    _name = "ai.gateway.api.key.history"
    _description = "Immutable API Key Rotation History"
    _order = "event_at desc"
    api_key_id = fields.Many2one("ai.gateway.api.key", required=True, ondelete="cascade", index=True)
    token_id = fields.Char(required=True, index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    key_hash = fields.Char(required=True, copy=False)
    event = fields.Selection([( "rotated", "Rotated"), ("revoked", "Revoked"), ("expired", "Expired")], required=True)
    event_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
