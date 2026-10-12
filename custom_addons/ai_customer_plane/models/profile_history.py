import json

from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError


class AiConfigurationProfileHistory(models.Model):
    """Immutable audit snapshot for customer configuration profile changes."""

    _name = "ai.customer.configuration.profile.history"
    _description = "Customer Configuration Profile History"
    _order = "changed_at desc, id desc"

    profile_id = fields.Many2one(
        "ai.customer.configuration.profile", index=True, ondelete="set null",
    )
    company_id = fields.Many2one(
        "res.company", required=True, readonly=True, index=True,
        ondelete="restrict",
    )
    profile_name = fields.Char(required=True, readonly=True)
    profile_version = fields.Integer(required=True, readonly=True)
    state = fields.Selection([
        ("draft", "Draft"), ("active", "Active"), ("archived", "Archived"),
    ], required=True, readonly=True)
    snapshot_json = fields.Text(required=True, readonly=True, default="{}")
    compiled_hash = fields.Char(readonly=True, index=True)
    changed_by_id = fields.Many2one("res.users", required=True, readonly=True)
    changed_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    @api.constrains("snapshot_json")
    def _check_snapshot_json(self):
        for record in self:
            value = json.loads(record.snapshot_json or "{}")
            if not isinstance(value, dict):
                raise ValidationError("Profile history snapshot must be a JSON object.")

    def write(self, vals):
        raise UserError("Profile history snapshots are immutable.")

    def unlink(self):
        raise UserError("Profile history snapshots cannot be deleted.")

    @api.model
    def create_snapshot(self, profile, reason=""):
        """Persist a binary-free snapshot of the current profile state."""
        sections = {}
        for name in getattr(profile, "_CONFIG_FIELDS", set()):
            try:
                sections[name] = json.loads(getattr(profile, name) or "{}")
            except (TypeError, ValueError):
                sections[name] = {"_invalid": True}
        snapshot = {
            "profile_id": profile.id,
            "name": profile.name,
            "version": profile.version,
            "state": profile.state,
            "sections": sections,
            "compiled_hash": profile.compiled_hash or "",
            "reason": reason or "",
        }
        values = {
            "profile_id": profile.id,
            "company_id": profile.company_id.id,
            "profile_name": profile.name,
            "profile_version": profile.version,
            "state": profile.state,
            "snapshot_json": json.dumps(snapshot, sort_keys=True, ensure_ascii=False),
            "compiled_hash": profile.compiled_hash or False,
            "changed_by_id": self.env.user.id,
        }
        return self.sudo().create(values)
