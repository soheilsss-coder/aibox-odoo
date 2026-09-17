import json

from odoo import api, fields, models


class AiAgentIdentity(models.Model):
    _name = "ai.gateway.agent.identity"
    _description = "AI Agent Identity"
    name = fields.Char(required=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)
    owner_user_id = fields.Many2one("res.users", required=True, default=lambda s: s.env.user, ondelete="restrict")
    purpose = fields.Char()
    scopes = fields.Text(default="[]")
    active = fields.Boolean(default=True, index=True)
    created_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    _sql_constraints = [("name_user_unique", "unique(name,user_id)", "Agent identity already exists for this user.")]

    @api.constrains("owner_user_id", "user_id")
    def _check_owner(self):
        for rec in self:
            if rec.owner_user_id != rec.user_id and not rec.owner_user_id.has_group("base.group_system"):
                # A non-admin owner may create an identity only for itself.
                raise ValueError("Agent identity owner must match the service user unless created by System Admin.")

    @api.model
    def ensure_personal(self, user=None):
        """Return the user's durable personal identity for Company Assistant.

        This is intentionally an identity/profile, not a second model or an
        authorization principal. Every personal identity still generates via
        the single Company Assistant and the effective permissions of its
        logged-in user. The savepoint makes the first request safe when two
        browser tabs initialize the profile concurrently.
        """
        user = user or self.env.user
        if not user or not user.exists() or not user.active:
            return self.browse()
        identity = self.sudo().search([
            ("user_id", "=", user.id),
            ("purpose", "=", "personal_workspace"),
            ("active", "=", True),
        ], order="id", limit=1)
        if identity:
            return identity
        vals = {
            "name": "personal_assistant_user_%s" % user.id,
            "user_id": user.id,
            "owner_user_id": user.id,
            "purpose": "personal_workspace",
            "scopes": json.dumps(["personal_memory", "current_user_permissions"]),
        }
        try:
            with self.env.cr.savepoint():
                identity = self.sudo().create(vals)
        except Exception:  # noqa: BLE001
            # Another request may have won the unique insert race. Re-read
            # instead of returning an error or creating a second identity.
            identity = self.sudo().search([
                ("user_id", "=", user.id),
                ("purpose", "=", "personal_workspace"),
                ("active", "=", True),
            ], order="id", limit=1)
        return identity

    @api.model
    def personal_public_state(self, user=None):
        """Return safe UI metadata without exposing technical identifiers."""
        identity = self.ensure_personal(user=user)
        return {
            "assigned": bool(identity),
            "label": "دستیار شخصی شما",
            "shared_core": True,
            "memory_scope": "حافظه شخصی و مجوزهای مؤثر همین کاربر",
        }
