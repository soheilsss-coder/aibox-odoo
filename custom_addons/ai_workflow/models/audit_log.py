from odoo import fields, models


class AiGatewayAuditLog(models.Model):
    _inherit = "ai.gateway.audit.log"

    workflow_id = fields.Many2one("ai.workflow", index=True, ondelete="set null")