from odoo import api, fields, models
from odoo.exceptions import AccessError


class AiCapability(models.Model):
    _name = "ai.control.capability"
    _description = "AI Capability"
    _order = "module_name, name"

    name = fields.Char(required=True, index=True)
    module_name = fields.Char(required=True, index=True)
    description = fields.Text()
    operation = fields.Selection([
        ("read", "Read"), ("create", "Create"), ("update", "Update"),
        ("delete", "Delete"), ("approve", "Approve"), ("execute", "Execute"),
    ], default="execute", required=True)
    risk_level = fields.Integer(default=0, required=True)
    model_name = fields.Char(index=True)
    group_ids = fields.Many2many("res.groups", string="Allowed Roles")
    active = fields.Boolean(default=True)
    source = fields.Selection([
        ("manual", "Manual"), ("adapter", "Adapter"), ("discovered", "Discovered")
    ], default="manual", required=True)

    _sql_constraints = [("name_unique", "unique(name)", "Capability name must be unique.")]

    @api.model
    def user_can(self, user, capability_name, record=None):
        return self.env["ai.control.authorization"].decide(capability_name, user=user, record=record)

    @api.model
    def require(self, capability_name, record=None):
        return self.env["ai.control.authorization"].require(capability_name, record=record)


class AiCapabilityResolver(models.AbstractModel):
    _name = "ai.control.capability.resolver"
    _description = "AI Capability Resolver"

    @api.model
    def effective_capabilities(self, user=None):
        return self.env["ai.control.authorization"].effective_capabilities(user=user)
