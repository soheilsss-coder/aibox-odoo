from odoo import api, fields, models


class AiSsoProvider(models.Model):
    _name = "ai.customer.sso.provider"
    _description = "Customer SSO Provider"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    protocol = fields.Selection([("oidc","OIDC"),("saml","SAML")], required=True, default="oidc")
    issuer = fields.Char()
    client_id = fields.Char()
    client_secret_ref = fields.Char(help="Reference into external secret management; never store the secret here.")
    authorization_url = fields.Char()
    token_url = fields.Char()
    jwks_url = fields.Char()
    audience = fields.Char()
    claim_user_id = fields.Char(default="sub")
    claim_email = fields.Char(default="email")
    claim_groups = fields.Char(default="groups")
    active = fields.Boolean(default=False)
    enforce_for_company = fields.Boolean(default=False)
    auto_provision = fields.Boolean(default=False, help="Never create a user from an IdP claim unless explicitly enabled.")
    redirect_uri = fields.Char(default="/api/sso/oidc/callback")
    saml_metadata_url = fields.Char()
    saml_entity_id = fields.Char()

    _sql_constraints = [
        ("provider_name_company_unique", "unique(name,company_id)", "Provider name must be unique per company.")
    ]

    @api.constrains("client_secret_ref")
    def _no_secret_literal(self):
        for rec in self:
            if rec.client_secret_ref and len(rec.client_secret_ref) > 0 and not rec.client_secret_ref.startswith(("vault://","secret://","env://")):
                raise ValueError("client_secret_ref must reference external secret management.")
