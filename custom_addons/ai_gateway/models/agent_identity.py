from odoo import api, fields, models

class AiAgentIdentity(models.Model):
    _name = "ai.gateway.agent.identity"
    _description = "AI Agent Identity"
    name = fields.Char(required=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)
    owner_user_id = fields.Many2one("res.users", required=True, default=lambda s: s.env.user, ondelete="restrict")
    purpose = fields.Char()
    scopes = fields.Text(default="[]")
    active = fields.Boolean(default=True, index=True)
    created_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    _sql_constraints=[("name_user_unique","unique(name,user_id)","Agent identity already exists for this user.")]

    @api.constrains("owner_user_id", "user_id")
    def _check_owner(self):
        for rec in self:
            if rec.owner_user_id != rec.user_id and not rec.owner_user_id.has_group("base.group_system"):
                # A non-admin owner may create an identity only for itself.
                raise ValueError("Agent identity owner must match the service user unless created by System Admin.")
