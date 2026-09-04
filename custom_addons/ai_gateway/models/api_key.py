import hashlib
import secrets
from odoo import api, fields, models


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AiGatewayApiKey(models.Model):
    _name = "ai.gateway.api.key"
    _description = "AI Gateway API Key"
    _rec_name = "user_id"

    user_id = fields.Many2one("res.users", required=True, ondelete="cascade")
    # IMPORTANT: plaintext secrets are no longer stored. The old `key` DB
    # column is removed by the v41 migration; callers receive a secret only
    # once from create_key().
    key_hash = fields.Char(required=True, index=True, copy=False)
    key_hint = fields.Char(size=12, copy=False)
    active = fields.Boolean(default=True)
    created_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    expires_at = fields.Datetime()
    last_used_at = fields.Datetime(readonly=True)
    revoked_at = fields.Datetime(readonly=True)
    scope = fields.Char(default="m2m")
    token_id = fields.Char(required=True, index=True, copy=False, default=lambda self: secrets.token_hex(16))
    created_by_id = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    device_session = fields.Char()
    agent_id = fields.Many2one("ai.gateway.agent.identity", index=True, ondelete="set null")

    _sql_constraints = [
        ("key_hash_unique", "unique(key_hash)", "This API key already exists."),
        ("user_unique", "unique(user_id)", "This user already has an API key."),
    ]

    @api.model
    def create_key(self, user, expires_at=None, scope="m2m"):
        secret = secrets.token_urlsafe(36)
        rec = self.sudo().search([("user_id", "=", user.id)], limit=1)
        vals = {
            "user_id": user.id,
            "key_hash": _hash(secret),
            "key_hint": secret[:10],
            "expires_at": expires_at,
            "scope": scope,
            "active": True,
            "revoked_at": False,
        }
        if rec:
            if "ai.gateway.api.key.history" in self.env:
                self.env["ai.gateway.api.key.history"].sudo().create({"api_key_id": rec.id, "token_id": rec.token_id, "user_id": rec.user_id.id, "key_hash": rec.key_hash, "event": "rotated", "event_at": fields.Datetime.now()})
            rec.write(vals)
            rec.write({"token_id": secrets.token_hex(16), "created_by_id": self.env.user.id})
        else:
            rec = self.sudo().create(vals)
        return secret

    @api.model
    def authenticate_secret(self, secret):
        if not secret:
            return self.browse()
        rec = self.sudo().search(
            [("key_hash", "=", _hash(secret)), ("active", "=", True)], limit=1
        )
        if rec and rec.expires_at and rec.expires_at < fields.Datetime.now():
            if "ai.gateway.api.key.history" in self.env:
                self.env["ai.gateway.api.key.history"].sudo().create({"api_key_id": rec.id, "token_id": rec.token_id, "user_id": rec.user_id.id, "key_hash": rec.key_hash, "event": "expired", "event_at": fields.Datetime.now()})
            rec.write({"active": False, "revoked_at": fields.Datetime.now()})
            return self.browse()
        if rec and not rec.user_id.active:
            # Deprovisioning must invalidate both browser sessions and
            # stateless credentials.  Never let a valid old key revive an
            # inactive identity.
            return self.browse()
        if rec:
            rec.sudo().write({"last_used_at": fields.Datetime.now()})
        return rec

    def revoke(self, reason="revoked"):
        for rec in self:
            if "ai.gateway.api.key.history" in self.env:
                self.env["ai.gateway.api.key.history"].sudo().create({"api_key_id": rec.id, "token_id": rec.token_id, "user_id": rec.user_id.id, "key_hash": rec.key_hash, "event": reason, "event_at": fields.Datetime.now()})
            rec.sudo().write({"active": False, "revoked_at": fields.Datetime.now()})
