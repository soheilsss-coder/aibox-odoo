import hashlib, json
from odoo import api, fields, models
from odoo.exceptions import ValidationError

class AiCustomerDesigner(models.Model):
    _name = "ai.customer.designer"
    _description = "Customer Control Plane Designer"
    _order = "kind, name"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company, index=True, ondelete="cascade")
    kind = fields.Selection([
        ("role","Role"),("permission","Permission"),("policy","Policy"),("workflow","Workflow"),
        ("approval_matrix","Approval Matrix"),("document_policy","Document Policy"),("agent","Agent"),
        ("tool","Tool"),("configuration_profile","Configuration Profile"),("deployment","Deployment Profile")
    ], required=True, index=True)
    definition_json = fields.Text(required=True, default="{}")
    version = fields.Integer(default=1, readonly=True)
    active = fields.Boolean(default=True)
    definition_hash = fields.Char(readonly=True, index=True)

    _sql_constraints=[("designer_name_company_kind_unique","unique(name,company_id,kind)","Designer name must be unique per company and kind.")]

    @api.constrains("definition_json")
    def _valid_json(self):
        for rec in self:
            try:
                value=json.loads(rec.definition_json or "{}")
            except Exception as exc:
                raise ValidationError("definition_json must be valid JSON") from exc
            if not isinstance(value, dict):
                raise ValidationError("definition_json must be a JSON object")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            raw=vals.get("definition_json") or "{}"
            vals["definition_hash"]=hashlib.sha256(raw.encode()).hexdigest()
        return super().create(vals_list)

    def write(self, vals):
        if "definition_json" in vals:
            raw=vals.get("definition_json") or "{}"
            vals=dict(vals, version=max(self.mapped("version") or [1])+1, definition_hash=hashlib.sha256(raw.encode()).hexdigest())
        return super().write(vals)
