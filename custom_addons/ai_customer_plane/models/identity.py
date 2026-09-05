from odoo import api, fields, models
from odoo.exceptions import AccessError


class AiExternalIdentity(models.Model):
    _name = "ai.customer.external.identity"
    _description = "Customer External Identity Mapping"

    provider_id = fields.Many2one("ai.customer.sso.provider", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", related="provider_id.company_id", store=True, index=True)
    external_subject = fields.Char(required=True, index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    email = fields.Char()
    last_login_at = fields.Datetime()
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("provider_subject_unique", "unique(provider_id, external_subject)", "External identity already mapped."),
    ]

    @api.model
    def map_identity(self, provider, subject, email=None, name=None):
        if not provider or not provider.active or not subject:
            raise AccessError("SSO provider or external identity is inactive")
        rec = self.sudo().search([
            ("provider_id", "=", provider.id),
            ("external_subject", "=", subject),
        ], limit=1)
        if rec:
            # SCIM/admin deprovisioning must not be undone by a later SSO login.
            if not rec.active or not rec.user_id.active:
                raise AccessError("customer identity is deprovisioned")
            rec.write({"last_login_at": fields.Datetime.now(), "email": email or rec.email})
            return rec.user_id

        user = self.env["res.users"].sudo().search([
            ("login", "=", email),
            ("company_ids", "in", provider.company_id.id),
        ], limit=1) if email else self.env["res.users"].browse()
        if user and not user.active:
            raise AccessError("customer account is inactive")
        if not user:
            if not provider.auto_provision:
                raise AccessError("external identity is not mapped and auto-provisioning is disabled")
            user = self.env["res.users"].sudo().create({
                "name": name or email or subject,
                "login": email or ("sso_" + subject),
                "email": email or False,
                "company_id": provider.company_id.id,
                "company_ids": [(4, provider.company_id.id)],
                "active": True,
            })
        self.sudo().create({
            "provider_id": provider.id,
            "external_subject": subject,
            "user_id": user.id,
            "email": email,
            "last_login_at": fields.Datetime.now(),
            "active": True,
        })
        return user
