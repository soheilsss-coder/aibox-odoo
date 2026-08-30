from odoo import api, fields, models


class AiIntegrationAdapter(models.Model):
    _name = "ai.integration.adapter"
    _description = "AI Module Integration Adapter"
    _order = "module_name"

    module_name = fields.Char(required=True, index=True)
    label = fields.Char(required=True)
    active = fields.Boolean(default=True)
    priority = fields.Integer(default=10)
    capability_prefix = fields.Char()
    event_prefix = fields.Char()
    notes = fields.Text()
    state = fields.Selection([( "ready", "Ready"), ("blocked", "Blocked")], default="ready")

    _sql_constraints = [("module_unique", "unique(module_name)", "An integration adapter already exists for this module.")]

    @api.model
    def for_module(self, module_name):
        return self.sudo().search([("module_name", "=", module_name), ("active", "=", True)], limit=1)
