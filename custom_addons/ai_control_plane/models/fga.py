from odoo import api, fields, models


class AiRelation(models.Model):
    _name = "ai.control.relation"
    _description = "Fine Grained Authorization Relation"

    subject_user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    project_id = fields.Integer(index=True)
    folder_id = fields.Integer(index=True)
    relation = fields.Selection([
        ("owner", "Owner"), ("manager", "Manager"), ("member", "Member"),
        ("viewer", "Viewer"), ("editor", "Editor"), ("delegate", "Delegate"),
    ], required=True)
    resource_model = fields.Char(required=True, index=True)
    resource_id = fields.Integer(required=True, index=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, index=True)
    active = fields.Boolean(default=True)
    starts_at = fields.Datetime(default=fields.Datetime.now, required=True)
    expires_at = fields.Datetime()
    granted_by_id = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    reason = fields.Char()

    _sql_constraints = [
        ("relation_unique", "unique(subject_user_id, relation, resource_model, resource_id)",
         "Authorization relation already exists."),
    ]

    @api.model
    def allows(self, user, relation, record):
        if not record or not record.id:
            return False
        now = fields.Datetime.now()
        domains = [[
            ("subject_user_id", "=", user.id), ("relation", "=", relation),
            ("resource_model", "=", record._name), ("resource_id", "=", record.id),
        ]]
        if "project_id" in record._fields and record.project_id:
            domains.append([
                ("subject_user_id", "=", user.id), ("relation", "=", relation),
                ("resource_model", "=", "project.project"), ("resource_id", "=", record.project_id.id),
            ])
        if "folder_id" in record._fields and record.folder_id:
            domains.append([
                ("subject_user_id", "=", user.id), ("relation", "=", relation),
                ("resource_model", "=", "documents.folder"), ("resource_id", "=", record.folder_id.id),
            ])
        for domain in domains:
            domain += [("active", "=", True), ("starts_at", "<=", now), "|", ("expires_at", "=", False), ("expires_at", ">=", now)]
            if self.sudo().search(domain, limit=1):
                return True
        return False

    @api.model
    def explain(self, user, relation, record):
        allowed = self.allows(user, relation, record)
        return {
            "allowed": allowed,
            "subject_user_id": user.id,
            "relation": relation,
            "resource_model": record._name if record else False,
            "resource_id": record.id if record else False,
            "checked_at": fields.Datetime.now().isoformat(),
        }
