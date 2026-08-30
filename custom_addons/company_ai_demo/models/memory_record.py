from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
import os, base64, hashlib
from cryptography.fernet import Fernet, InvalidToken


class AiAgentMemoryRecord(models.Model):
    _name = "ai.agent.memory.record"
    _description = "Enterprise Agent Memory"
    _order = "created_at desc"

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    department_id = fields.Many2one("hr.department", index=True)
    key = fields.Char(required=True, index=True)
    value = fields.Text(required=True, copy=False)
    scope = fields.Selection([("personal", "Personal"), ("department", "Department"), ("company", "Company")], default="personal", required=True, index=True)
    created_at = fields.Datetime(default=fields.Datetime.now, readonly=True, index=True)
    expires_at = fields.Datetime(index=True)
    active = fields.Boolean(default=True, index=True)
    source = fields.Char(default="assistant")
    classification = fields.Selection([("public","Public"),("internal","Internal"),("confidential","Confidential"),("restricted","Restricted")], default="internal", required=True, index=True)
    deleted_at = fields.Datetime(index=True)
    residency_region = fields.Char(default=lambda self: os.environ.get("AI_MEMORY_RESIDENCY", "customer-region"), required=True)

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
        employee = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
        department = employee.department_id if employee else False
        if scope == "department" and not department:
            raise AccessError("department memory requires an employee department")
        if scope == "company" and not any(user.has_group(x) for x in ("hr.group_hr_manager", "ai_business_tools.role_executive", "ai_business_tools.role_system_admin")):
            raise AccessError("company memory is restricted to HR/Executive/Admin")
        expires = fields.Datetime.add(fields.Datetime.now(), days=retention_days) if retention_days else False
        if scope not in ("personal", "department", "company"):
            raise ValidationError("Invalid memory scope")
        return self.sudo().create({
            "user_id": user.id, "company_id": user.company_id.id,
            "department_id": department.id if department else False,
            "key": key, "value": self._encrypt(value), "scope": scope, "expires_at": expires,
            "classification": self.env.context.get("memory_classification", "internal"),
        })

    @api.model
    def visible_for(self, user=None):
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
        return self.sudo().search(domain)

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
