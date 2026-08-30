import hashlib
import secrets
from odoo import api, fields, models


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AiGatewaySession(models.Model):
    _name = "ai.gateway.session"
    _description = "AI Gateway Secure Browser Session"

    token_hash = fields.Char(required=True, index=True, copy=False)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    created_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    expires_at = fields.Datetime(required=True, index=True)
    last_seen_at = fields.Datetime()
    revoked_at = fields.Datetime()
    user_agent_hash = fields.Char()
    rotation_parent_hash = fields.Char(index=True, copy=False)

    _sql_constraints = [("token_hash_unique", "unique(token_hash)", "Session token collision.")]

    @api.model
    def issue(self, user, ttl_hours=8, user_agent=None, rotation_parent=None):
        token = secrets.token_urlsafe(48)
        now = fields.Datetime.now()
        expires = fields.Datetime.add(now, hours=ttl_hours)
        self.sudo().create({
            "token_hash": _hash(token), "user_id": user.id,
            "expires_at": expires, "last_seen_at": now,
            "user_agent_hash": _hash(user_agent) if user_agent else False,
            "rotation_parent_hash": _hash(rotation_parent) if rotation_parent else False,
        })
        return token, expires

    @api.model
    def authenticate_token(self, token):
        if not token:
            return self.browse()
        rec = self.sudo().search([("token_hash", "=", _hash(token)), ("revoked_at", "=", False)], limit=1)
        if not rec or rec.expires_at < fields.Datetime.now():
            if rec:
                rec.write({"revoked_at": fields.Datetime.now()})
            return self.browse()
        rec.sudo().write({"last_seen_at": fields.Datetime.now()})
        return rec

    @api.model
    def rotate(self, token, user_agent=None, ttl_hours=8):
        rec = self.authenticate_token(token)
        if not rec:
            return self.browse(), None, None
        rec.sudo().write({"revoked_at": fields.Datetime.now()})
        new_token, expires = self.issue(rec.user_id, ttl_hours=ttl_hours, user_agent=user_agent, rotation_parent=token)
        return rec, new_token, expires

    def revoke(self):
        self.sudo().write({"revoked_at": fields.Datetime.now()})
