import hashlib
import hmac
import secrets

from odoo import api, fields, models
from odoo.exceptions import AccessError


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AiGatewaySession(models.Model):
    _name = "ai.gateway.session"
    _description = "AI Gateway Secure Browser Session"

    token_hash = fields.Char(required=True, index=True, copy=False)
    # A browser mutation must prove possession of the session-specific
    # anti-CSRF token as well as the HttpOnly session cookie.  Only the hash
    # is persisted; the raw token is returned once when the session is issued.
    csrf_token_hash = fields.Char(required=True, index=True, copy=False)
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
        if not user or not user.exists() or not user.active:
            raise AccessError("inactive users cannot receive a session")
        token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        now = fields.Datetime.now()
        expires = fields.Datetime.add(now, hours=ttl_hours)
        self.sudo().create({
            "token_hash": _hash(token), "csrf_token_hash": _hash(csrf_token),
            "user_id": user.id, "expires_at": expires, "last_seen_at": now,
            "user_agent_hash": _hash(user_agent) if user_agent else False,
            "rotation_parent_hash": _hash(rotation_parent) if rotation_parent else False,
        })
        return token, expires, csrf_token

    @api.model
    def authenticate_token(self, token, csrf_token=None, require_csrf=False):
        if not token:
            return self.browse()
        rec = self.sudo().search([
            ("token_hash", "=", _hash(token)), ("revoked_at", "=", False),
        ], limit=1)
        if not rec or rec.expires_at < fields.Datetime.now() or not rec.user_id.active:
            if rec:
                rec.write({"revoked_at": fields.Datetime.now()})
            return self.browse()
        if require_csrf:
            if not csrf_token or not hmac.compare_digest(
                rec.csrf_token_hash or "", _hash(csrf_token)
            ):
                return self.browse()
        self._touch(rec)
        return rec

    @api.model
    def _touch(self, rec):
        """Refresh the session heartbeat cheaply and safely.

        The browser fires several API calls per keystroke/poll in parallel, so
        many threads race on the *same* session row.  An ORM ``write`` on a
        single record compiles to ``UPDATE ... FROM (VALUES ...)`` and, under a
        concurrent update of the same row, PostgreSQL raises a serialization
        failure (EvalPlanQual cannot re-evaluate the self-join), which Odoo
        retries up to 4 times with backoff -- turning every request into a
        multi-second stall.  Use a plain single-statement UPDATE (which simply
        queues behind the row lock) and throttle it to once per 30s so the
        heartbeat never contends.
        """
        now = fields.Datetime.now()
        last = rec.last_seen_at
        if last and fields.Datetime.from_string(last) >= fields.Datetime.add(now, minutes=-0.5):
            return
        rec.invalidate_recordset(["last_seen_at"])
        rec.env.cr.execute(
            "UPDATE ai_gateway_session SET last_seen_at = now() WHERE id = %s",
            [rec.id],
        )
        rec.invalidate_recordset(["last_seen_at"])
        rec.last_seen_at = now

    @api.model
    def rotate(self, token, user_agent=None, ttl_hours=8):
        rec = self.authenticate_token(token)
        if not rec:
            return self.browse(), None, None, None
        rec.sudo().write({"revoked_at": fields.Datetime.now()})
        new_token, expires, csrf_token = self.issue(
            rec.user_id, ttl_hours=ttl_hours, user_agent=user_agent,
            rotation_parent=token,
        )
        return rec, new_token, expires, csrf_token

    def revoke(self):
        self.sudo().write({"revoked_at": fields.Datetime.now()})
