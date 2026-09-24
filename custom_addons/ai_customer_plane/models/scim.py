import hashlib
import secrets
from odoo import api, fields, models


class AiScimToken(models.Model):
    _name = "ai.customer.scim.token"
    _description = "SCIM Bearer Token"

    name = fields.Char(required=True)
    token_hash = fields.Char(required=True, index=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    active = fields.Boolean(default=True)
    expires_at = fields.Datetime(index=True)
    last_used_at = fields.Datetime(readonly=True)

    _sql_constraints = [("token_hash_unique", "unique(token_hash)", "SCIM token already exists.")]

    @api.model
    def issue(self, name, company=None, expires_at=None):
        raw = "scim_" + secrets.token_urlsafe(48)
        rec = self.sudo().create({
            "name": name, "token_hash": hashlib.sha256(raw.encode()).hexdigest(),
            "company_id": (company or self.env.company).id, "expires_at": expires_at,
        })
        return rec, raw

    @api.model
    def authenticate(self, raw):
        if not raw:
            return self.browse()
        rec = self.sudo().search([("token_hash","=",hashlib.sha256(raw.encode()).hexdigest()),("active","=",True)], limit=1)
        if rec and rec.expires_at and rec.expires_at < fields.Datetime.now():
            rec.write({"active": False})
            return self.browse()
        if rec:
            rec.write({"last_used_at": fields.Datetime.now()})
        return rec

class AiScimGroupMap(models.Model):
    """Tenant-scoped allow-list for SCIM-managed Odoo groups.

    Odoo res.groups is global metadata. SCIM must never expose or mutate every
    group in the database merely because a tenant token is valid. A customer
    explicitly maps the groups that its IdP is allowed to manage.
    """
    _name = "ai.customer.scim.group"
    _description = "SCIM Managed Group Mapping"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company, index=True)
    group_id = fields.Many2one("res.groups", required=True, ondelete="cascade")
    active = fields.Boolean(default=True)

    @api.constrains("group_id")
    def _check_product_role(self):
        for rec in self:
            xmlids = set(rec.group_id.get_external_id().values()) if rec.group_id else set()
            if not any(x.startswith("ai_business_tools.role_") for x in xmlids):
                raise ValidationError("SCIM may manage only product-defined AI roles.")

    _sql_constraints = [
        ("company_group_unique", "unique(company_id, group_id)", "This group is already mapped for the company."),
    ]
