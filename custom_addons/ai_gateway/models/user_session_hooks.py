from odoo import models


class ResUsersGatewayRevocation(models.Model):
    _inherit = "res.users"

    def write(self, vals):
        result = super().write(vals)
        # Account deactivation is a security boundary, not merely a UI flag.
        # Revoke every gateway credential after the native user write commits
        # in the same transaction; subsequent authentication also checks
        # user.active for defense in depth.
        if vals.get("active") is False:
            inactive = self.filtered(lambda user: not user.active)
            if inactive:
                if "ai.gateway.session" in self.env:
                    self.env["ai.gateway.session"].sudo().search([
                        ("user_id", "in", inactive.ids),
                        ("revoked_at", "=", False),
                    ]).revoke()
                if "ai.gateway.api.key" in self.env:
                    self.env["ai.gateway.api.key"].sudo().search([
                        ("user_id", "in", inactive.ids),
                        ("active", "=", True),
                    ]).revoke(reason="user_deactivated")
        return result
