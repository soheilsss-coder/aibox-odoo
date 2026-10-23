from odoo import fields, models


class AiGatewayAuditLog(models.Model):
    _inherit = "ai.gateway.audit.log"

    policy_id = fields.Many2one("ai.control.policy", index=True, ondelete="set null")