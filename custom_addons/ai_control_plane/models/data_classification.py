from odoo import api, fields, models


class AiDataClassification(models.Model):
    _name = "ai.control.data.classification"
    _description = "AI Data Classification Policy"

    model_name = fields.Char(required=True, index=True)
    field_name = fields.Char(index=True)
    classification = fields.Selection([
        ("public", "Public"), ("internal", "Internal"),
        ("confidential", "Confidential"), ("restricted", "Restricted"),
        ("pii", "PII"),
    ], required=True, default="internal")
    tenant_scope = fields.Selection([("company", "Company"), ("department", "Department"), ("personal", "Personal"), ("explicit", "Explicit")], required=True, default="company")
    allowed_groups = fields.Many2many("res.groups")
    active = fields.Boolean(default=True)

    @api.model
    def for_record(self, record):
        return self.sudo().search([
            ("model_name", "=", record._name), ("field_name", "in", [False, ""]), ("active", "=", True)
        ], order="id", limit=1)

    def allows(self, user, record=None):
        self.ensure_one()
        if self.allowed_groups and not (self.allowed_groups & user.groups_id):
            return False
        if not record:
            return False
        # Tenant boundary is about the RECORD, never merely the user having
        # a company_id field. A missing company on a classified record is
        # denied rather than treated as global.
        if self.tenant_scope == "company":
            if "company_id" not in record._fields:
                return False
            company = record.company_id
            return bool(company and company.id in user.company_ids.ids)
        if self.tenant_scope == "personal":
            for field_name in ("user_id", "owner_id", "employee_id"):
                if field_name in record._fields:
                    value = record[field_name]
                    if field_name == "employee_id" and value and value.user_id:
                        return value.user_id.id == user.id
                    if value and getattr(value, "id", None) == user.id:
                        return True
            return False
        if self.tenant_scope == "department":
            employee = user.employee_id
            if not employee or not employee.department_id:
                return False
            for field_name in ("department_id",):
                if field_name in record._fields and record[field_name]:
                    return record[field_name].id == employee.department_id.id
            if "employee_id" in record._fields and record.employee_id:
                return record.employee_id.department_id.id == employee.department_id.id
            return False
        if self.tenant_scope == "explicit":
            if user.has_group("base.group_system"):
                return True
            if "allowed_user_ids" in record._fields and user in record.allowed_user_ids:
                return True
            if "ai.control.relation" in self.env:
                relation = self.env["ai.control.relation"]
                return any(relation.allows(user, rel, record) for rel in ("owner", "manager", "member", "viewer", "editor", "delegate"))
            return False
        return False
