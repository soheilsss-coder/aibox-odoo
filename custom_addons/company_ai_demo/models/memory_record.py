from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
import os, base64, hashlib, hmac, re
from cryptography.fernet import Fernet, InvalidToken
from psycopg2 import IntegrityError


class AiAgentMemoryRecord(models.Model):
    _name = "ai.agent.memory.record"
    _description = "Enterprise Agent Memory"
    _order = "created_at desc"

    def init(self):
        """Index opaque search digests without indexing plaintext memory."""
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS ai_agent_memory_search_tokens_fts_idx "
            "ON ai_agent_memory_record USING gin "
            "(to_tsvector('simple', coalesce(search_tokens, '')))"
        )

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    department_id = fields.Many2one("hr.department", index=True)
    key = fields.Char(required=True, index=True)
    value = fields.Text(required=True, copy=False)
    # Keyed token digests allow bounded exact-memory search without storing
    # plaintext or decrypting the entire user's memory table on every turn.
    # The digest is not customer-visible and cannot be reversed without the
    # memory encryption key.
    search_tokens = fields.Text(copy=False, index=True, readonly=True)
    scope = fields.Selection([("personal", "Personal"), ("department", "Department"), ("company", "Company")], default="personal", required=True, index=True)
    created_at = fields.Datetime(default=fields.Datetime.now, readonly=True, index=True)
    expires_at = fields.Datetime(index=True)
    active = fields.Boolean(default=True, index=True)
    source = fields.Char(default="assistant")
    classification = fields.Selection([("public","Public"),("internal","Internal"),("confidential","Confidential"),("restricted","Restricted")], default="internal", required=True, index=True)
    deleted_at = fields.Datetime(index=True)
    residency_region = fields.Char(default=lambda self: os.environ.get("AI_MEMORY_RESIDENCY", "customer-region"), required=True)

    _sql_constraints = [
        (
            "memory_scope_key_unique",
            "unique(user_id, company_id, scope, key)",
            "A memory key is unique within its user/company/scope.",
        ),
    ]

    @api.model
    def _token_secret(self):
        raw = os.environ.get("AI_MEMORY_ENCRYPTION_KEY", "").strip()
        try:
            secret = base64.urlsafe_b64decode(raw.encode("ascii"))
        except Exception as exc:
            raise AccessError("invalid_memory_encryption_key") from exc
        if len(secret) != 32:
            raise AccessError("invalid_memory_encryption_key")
        return secret

    @api.model
    def _search_tokens(self, value):
        tokens = []
        for token in re.findall(r"[\w]{2,}", str(value or "").casefold(), flags=re.UNICODE):
            if token not in tokens:
                tokens.append(token)
            if len(tokens) >= 32:
                break
        secret = self._token_secret()
        return " ".join(
            hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()
            for token in tokens
        )

    @api.model
    def _fernet(self):
        raw = os.environ.get("AI_MEMORY_ENCRYPTION_KEY", "").strip()
        if not raw:
            raise AccessError("memory_encryption_key_required")
        try:
            return Fernet(raw.encode())
        except Exception as exc:
            raise AccessError("invalid_memory_encryption_key") from exc

    @api.model
    def _encrypt(self, value):
        return self._fernet().encrypt(str(value).encode("utf-8")).decode("ascii")

    @api.model
    def _decrypt(self, value):
        try:
            return self._fernet().decrypt((value or "").encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise AccessError("memory_decryption_failed") from exc

    @api.model
    def create_memory(self, key, value, scope="personal", user=None, retention_days=365):
        user = user or self.env.user
        key = str(key or "").strip()
        value = str(value if value is not None else "").strip()
        if not key or len(key) > 160:
            raise ValidationError("Memory key must contain 1 to 160 characters")
        if not value or len(value) > 16000:
            raise ValidationError("Memory value must contain 1 to 16000 characters")
        employee = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
        department = employee.department_id if employee else False
        if scope == "department" and not department:
            raise AccessError("department memory requires an employee department")
        if scope == "company" and not any(user.has_group(x) for x in ("hr.group_hr_manager", "ai_business_tools.role_executive", "ai_business_tools.role_system_admin")):
            raise AccessError("company memory is restricted to HR/Executive/Admin")
        if scope not in ("personal", "department", "company"):
            raise ValidationError("Invalid memory scope")
        try:
            retention_days = int(retention_days or 0)
        except (TypeError, ValueError):
            raise ValidationError("retention_days must be a bounded integer")
        if retention_days < 0 or retention_days > 3650:
            raise ValidationError("retention_days must be between 0 and 3650")
        expires = fields.Datetime.add(fields.Datetime.now(), days=retention_days) if retention_days else False
        values = {
            "user_id": user.id, "company_id": user.company_id.id,
            "department_id": department.id if department else False,
            "key": key, "value": self._encrypt(value), "search_tokens": self._search_tokens("%s %s" % (key, value)),
            "scope": scope, "expires_at": expires, "active": True,
            "classification": self.env.context.get("memory_classification", "internal"),
        }
        existing = self.sudo().search([
            ("user_id", "=", user.id), ("company_id", "=", user.company_id.id),
            ("scope", "=", scope), ("key", "=", key),
        ], order="id desc", limit=1)
        if existing:
            existing.write(values)
            return existing
        try:
            with self.env.cr.savepoint():
                return self.sudo().create(values)
        except IntegrityError:
            # Another chat turn may have won the unique-key race. Re-read and
            # update it instead of surfacing a raw database exception.
            existing = self.sudo().search([
                ("user_id", "=", user.id), ("company_id", "=", user.company_id.id),
                ("scope", "=", scope), ("key", "=", key),
            ], order="id desc", limit=1)
            if not existing:
                raise
            existing.write(values)
            return existing

    @api.model
    def visible_for(self, user=None, limit=500, query=""):
        user = user or self.env.user
        employee = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
        department_id = employee.department_id.id if employee else False
        privileged_company = any(user.has_group(x) for x in (
            "hr.group_hr_manager", "ai_business_tools.role_executive",
            "ai_business_tools.role_system_admin", "ai_business_tools.role_security"
        ))
        scope_domain = [
            "|",
            "&", ("scope", "=", "personal"), ("user_id", "=", user.id),
            "&", ("scope", "=", "department"), ("department_id", "=", department_id),
        ]
        if privileged_company:
            scope_domain = ["|", ("scope", "=", "company"), *scope_domain]
        domain = [
            ("active", "=", True),
            ("company_id", "=", user.company_id.id),
            "|", ("expires_at", "=", False), ("expires_at", ">=", fields.Datetime.now()),
            *scope_domain,
        ]
        if query:
            token_hashes = self._search_tokens(query).split()
            if token_hashes:
                # Search opaque digests through the GIN index, then verify the
                # complete query after decryption. This avoids decrypting the
                # whole memory table while preserving phrase-level matching in
                # Python and never stores plaintext search terms.
                self.env.cr.execute(
                    "SELECT id FROM ai_agent_memory_record "
                    "WHERE to_tsvector('simple', coalesce(search_tokens, '')) "
                    "@@ to_tsquery('simple', %s)",
                    (" | ".join(token_hashes),),
                )
                token_ids = [row[0] for row in self.env.cr.fetchall()]
                domain.append(("id", "in", token_ids or [0]))
        try:
            limit = max(1, min(int(limit), 5000))
        except (TypeError, ValueError):
            limit = 500
        return self.sudo().search(domain, order="created_at desc, id desc", limit=limit)

    @api.model
    def cleanup_expired(self):
        return self.sudo().search([("expires_at", "!=", False), ("expires_at", "<", fields.Datetime.now())]).write({"active": False})

    @api.model
    def erase_user(self, user=None):
        user = user or self.env.user
        if user != self.env.user and not self.env.user.has_group("base.group_system"):
            raise AccessError("Only the user or a system administrator may erase memory")
        recs = self.sudo().search([("user_id", "=", user.id)])
        count = len(recs)
        recs.unlink()
        return count
