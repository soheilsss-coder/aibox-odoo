from odoo import api, fields, models
from odoo.exceptions import AccessError


class AiAuthorizationPolicy(models.Model):
    _name = "ai.control.policy"
    _description = "AI Authorization Policy"
    _order = "capability_name"

    capability_name = fields.Char(required=True, index=True)
    resource_model = fields.Char(index=True)
    scope = fields.Selection([
        ("any", "Any"), ("own", "Own"), ("team", "Team"),
        ("department", "Department"), ("branch", "Branch"), ("project", "Project"),
        ("folder", "Folder"), ("position", "Position"), ("company", "Company"),
        ("explicit", "Explicit"),
    ], default="any", required=True)
    required_groups = fields.Many2many("res.groups", string="Required Roles")
    active = fields.Boolean(default=True)
    description = fields.Text()

    _sql_constraints = [("capability_scope_unique", "unique(capability_name, scope)", "Policy already exists.")]


class AiAuthorizationEngine(models.AbstractModel):
    _name = "ai.control.authorization"
    _description = "Central Authorization Engine"

    @api.model
    def decide(self, capability, user=None, record=None, action="execute"):
        user = user or self.env.user
        Cap = self.env["ai.control.capability"].sudo()
        cap = Cap.search([("name", "=", capability), ("active", "=", True)], limit=1)
        if not cap:
            return False
        permanent_groups = user.groups_id
        grant_model = self.env["ai.gateway.access.grant"].sudo() if "ai.gateway.access.grant" in self.env else None
        assignment_model = self.env["ai.customer.role.assignment"].sudo() if "ai.customer.role.assignment" in self.env else None
        assigned_groups = assignment_model.groups_for_user(user) if assignment_model else self.env["res.groups"].browse()
        effective_groups = permanent_groups | assigned_groups
        if grant_model:
            effective_groups |= grant_model.effective_groups(user)
        grant_allows = grant_model.grant_allows(user, capability, record=record) if grant_model else False
        delegation_allows = False
        if "ai.customer.delegation" in self.env:
            delegation_allows = bool(self.env["ai.customer.delegation"].sudo().effective_for(
                user, capability, model=record._name if record else None, res_id=record.id if record else None
            ))
        if cap.group_ids and not (cap.group_ids & effective_groups) and not grant_allows and not delegation_allows:
            return False
        if record is not None and cap.model_name and record._name != cap.model_name:
            return False
        # Temporary/delegated grants are authorization facts, never role mutations.
        if record is not None and "ai.control.data.classification" in self.env:
            classification = self.env["ai.control.data.classification"].sudo().for_record(record)
            if classification and not classification.allows(user, record=record):
                return False
        policy = self.env["ai.control.policy"].sudo().search([
            ("capability_name", "=", capability), ("active", "=", True)
        ], order="id", limit=1)
        policies = self.env["ai.control.policy"].sudo().search([("capability_name", "=", capability), ("active", "=", True)])
        if not policies:
            return True
        groups = set(effective_groups.ids)
        for policy in policies:
            if policy.required_groups and not groups.intersection(policy.required_groups.ids):
                continue
            if record is None or policy.scope == "any":
                return True
            if policy.scope == "own":
                own = ((hasattr(record, "create_uid") and record.create_uid.id == user.id) or
                       (hasattr(record, "user_id") and record.user_id and record.user_id.id == user.id))
                if own: return True
            elif policy.scope == "company" and "company_id" in record._fields:
                if not record.company_id or record.company_id.id == user.company_id.id: return True
            elif policy.scope == "branch" and "branch_id" in record._fields:
                if record.branch_id and record.branch_id.id == user.company_id.id: return True
            elif policy.scope == "project" and "ai.control.relation" in self.env:
                if any(self.env["ai.control.relation"].allows(user, rel, record) for rel in ("owner", "manager", "member", "viewer", "editor", "delegate")): return True
            elif policy.scope == "folder" and "ai.control.relation" in self.env:
                if any(self.env["ai.control.relation"].allows(user, rel, record) for rel in ("owner", "manager", "member", "viewer", "editor", "delegate")): return True
            elif policy.scope == "position":
                employee = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
                if employee and "employee_id" in record._fields and record.employee_id and record.employee_id.job_id == employee.job_id: return True
            elif policy.scope in ("department", "team"):
                employee = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
                target_employee = record if record._name == "hr.employee" else False
                if not target_employee and "employee_id" in record._fields: target_employee = record.employee_id
                if target_employee and employee:
                    if policy.scope == "department" and target_employee.department_id == employee.department_id: return True
                    if policy.scope == "team" and target_employee.parent_id == employee: return True
            elif policy.scope == "explicit" and "ai.control.relation" in self.env:
                if any(self.env["ai.control.relation"].allows(user, rel, record) for rel in ("owner", "manager", "member", "viewer", "editor", "delegate")): return True
        return False

    @api.model
    def check_capability(self, capability, user=None, record=None, action="execute"):
        return bool(self.decide(capability, user=user, record=record, action=action))

    @api.model
    def require(self, capability, user=None, record=None, action="execute"):

        if not self.decide(capability, user=user, record=record, action=action):
            raise AccessError("access_denied: capability '%s' is not authorized" % capability)
        return True

    @api.model
    def effective_capabilities(self, user=None):
        user = user or self.env.user
        return self.env["ai.control.capability"].sudo().search([("active", "=", True)]).filtered(
            lambda c: self.decide(c.name, user=user)
        )
