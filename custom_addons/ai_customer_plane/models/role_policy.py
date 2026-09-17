from odoo import api, fields, models
from odoo.exceptions import ValidationError

class AiCustomerRolePolicy(models.Model):
    _name = "ai.customer.role.policy"
    _description = "Attribute-driven Excel Role Policy"
    _order = "priority desc, id"
    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company, index=True)
    profile_id = fields.Many2one(
        "ai.customer.configuration.profile", index=True, ondelete="set null",
        help="Configuration profile that owns this rule; empty means manually managed.",
    )
    profile_rule_key = fields.Char(index=True, copy=False)
    department = fields.Char()
    position = fields.Char()
    job_level = fields.Char()
    manager_required = fields.Boolean()
    location = fields.Char()
    employment_type = fields.Char()
    role_group_id = fields.Many2one("res.groups", required=True, ondelete="restrict")
    priority = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("profile_rule_unique", "unique(profile_id, profile_rule_key)", "Profile role rule key must be unique."),
    ]

    @api.constrains("role_group_id")
    def _check_product_role(self):
        for rec in self:
            xmlids=set(rec.role_group_id.get_external_id().values())
            if not any(x.startswith("ai_business_tools.role_") for x in xmlids):
                raise ValidationError("Role policies may target only product-defined AI roles.")

    @api.model
    def resolve(self, company, department="", position="", job_level="", manager_required=False, location="", employment_type=""):
        rows=self.sudo().search([("company_id","=",company.id),("active","=",True)], order="priority desc,id asc")
        def match(rule, value):
            return not rule or rule.strip().lower() in (value or "").strip().lower()
        for r in rows:
            if match(r.department,department) and match(r.position,position) and match(r.job_level,job_level) and match(r.location,location) and match(r.employment_type,employment_type) and (not r.manager_required or bool(manager_required)):
                return r.role_group_id
        return self.env["res.groups"].browse()
