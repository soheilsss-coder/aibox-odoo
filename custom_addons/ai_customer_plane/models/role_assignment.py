from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AiRoleAssignment(models.Model):
    _name = "ai.customer.role.assignment"
    _description = "Central Role Assignment Source"
    _order = "priority desc, id"

    user_id = fields.Many2one("res.users", index=True, ondelete="cascade")
    role_group_id = fields.Many2one("res.groups", required=True, ondelete="restrict")
    source = fields.Selection([
        ("direct", "Direct"), ("department", "Department"), ("position", "Position"),
        ("temporary", "Temporary"), ("delegated", "Delegated"),
    ], required=True, index=True)
    department_id = fields.Many2one("hr.department", ondelete="cascade", index=True)
    position_id = fields.Many2one("hr.job", ondelete="cascade", index=True)
    grant_id = fields.Many2one("ai.gateway.access.grant", ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company, index=True)
    starts_at = fields.Datetime(default=fields.Datetime.now, required=True)
    expires_at = fields.Datetime()
    active = fields.Boolean(default=True, index=True)
    priority = fields.Integer(default=10)
    reason = fields.Char()
    managed_by = fields.Selection([
        ("admin", "Admin"), ("scim", "SCIM"), ("sso", "SSO"),
        ("excel", "Excel"), ("system", "System")
    ], default="admin", required=True, index=True)

    @api.constrains("source", "user_id", "department_id", "position_id", "grant_id")
    def _check_source(self):
        for rec in self:
            expected = {
                "direct": bool(rec.user_id) and not rec.department_id and not rec.position_id and not rec.grant_id,
                "department": bool(rec.department_id) and not rec.user_id and not rec.position_id and not rec.grant_id,
                "position": bool(rec.position_id) and not rec.user_id and not rec.department_id and not rec.grant_id,
                "temporary": bool(rec.grant_id) and rec.grant_id.grant_type == "temporary" and not rec.user_id and not rec.department_id and not rec.position_id,
                "delegated": bool(rec.grant_id) and rec.grant_id.grant_type == "delegated" and not rec.user_id and not rec.department_id and not rec.position_id,
            }[rec.source]
            if not expected:
                raise ValidationError("Role assignment source fields do not match source type.")
            module = getattr(rec.role_group_id, "module", "") or ""
            xmlid = rec.role_group_id.get_external_id().get(rec.role_group_id.id, "")
            if module != "ai_business_tools" and not xmlid.startswith("ai_business_tools."):
                raise ValidationError("Only product-defined roles may be assigned.")

    @api.model
    def groups_for_user(self, user):
        now = fields.Datetime.now()
        groups = self.env["res.groups"].browse()
        domain = [
            ("active", "=", True), ("company_id", "in", [user.company_id.id, False]),
            ("starts_at", "<=", now), "|", ("expires_at", "=", False), ("expires_at", ">=", now),
        ]
        for rec in self.sudo().search(domain):
            if rec.source == "direct" and rec.user_id == user:
                groups |= rec.role_group_id
            elif rec.source == "department":
                employee = user.employee_id
                if employee and employee.department_id == rec.department_id:
                    groups |= rec.role_group_id
            elif rec.source == "position":
                employee = user.employee_id
                if employee and employee.job_id == rec.position_id:
                    groups |= rec.role_group_id
            elif rec.source in ("temporary", "delegated") and rec.grant_id and rec.grant_id.to_user_id == user:
                grant = rec.grant_id
                if grant.active and grant.state == "active":
                    if grant.group_id:
                        groups |= grant.group_id
        return groups
