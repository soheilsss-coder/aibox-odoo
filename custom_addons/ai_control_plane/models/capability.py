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
        ("manual", "Manual"), ("adapter", "Adapter"), ("discovered", "Discovered"),
        ("control_plane", "Control Plane")
    ], default="manual", required=True)

    _sql_constraints = [("name_unique", "unique(name)", "Capability name must be unique.")]

    @api.model_create_multi
    def create(self, vals_list):
        """Idempotent registry seeding: capabilities are unique by name, so
        re-seeding the same capability from another module UPDATES it instead
        of crashing the install with UniqueViolation."""
        to_create = []
        updated = self.browse()
        for vals in vals_list:
            name = vals.get("name")
            found = self.with_context(active_test=False).search(
                [("name", "=", name)], limit=1) if name else self.browse()
            if found:
                found.write({k: v for k, v in vals.items() if k != "name"})
                updated |= found
            else:
                to_create.append(vals)
        created = super().create(to_create) if to_create else self.browse()
        return updated | created

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
