from odoo import api, fields, models


class AiConfigurationProfile(models.Model):
    _name = "ai.customer.configuration.profile"
    _description = "Customer Control Plane Configuration Profile"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    active = fields.Boolean(default=True)
    role_policy_json = fields.Text(default="{}")
    capability_policy_json = fields.Text(default="{}")
    approval_matrix_json = fields.Text(default="{}")
    document_policy_json = fields.Text(default="{}")
    agent_config_json = fields.Text(default="{}")
    tool_config_json = fields.Text(default="{}")
    workflow_config_json = fields.Text(default="{}")
    version = fields.Integer(default=1)
    state = fields.Selection([("draft","Draft"),("active","Active"),("archived","Archived")],
                             default="draft", required=True)

    _sql_constraints = [
        ("name_company_unique", "unique(name,company_id)", "Profile name must be unique per company.")
    ]

    def activate(self):
        for rec in self:
            self.search([("company_id","=",rec.company_id.id),("id","!=",rec.id),("state","=","active")]).write({"state":"archived"})
            rec.write({"state":"active", "active": True})
        return True


class AiDeploymentWizard(models.TransientModel):
    _name = "ai.customer.deployment.wizard"
    _description = "Customer Deployment Wizard"

    profile_id = fields.Many2one("ai.customer.configuration.profile", required=True)
    dry_run = fields.Boolean(default=True)
    result_json = fields.Text(default="{}")

    def run(self):
        profile = self.profile_id
        required_models = [
            "ai.control.authorization", "ai.control.capability", "ai.integration.module",
            "ai.integration.adapter", "ai.integration.operation", "ai.integration.subscription",
            "ai.gateway.execution.gate", "ai.gateway.approval", "ai.gateway.access.grant",
            "ai.customer.role.assignment", "ai.customer.role.policy", "ai.workflow",
            "ai.document.index.job", "ai.model.profile", "ai.gateway.session",
            "ai.customer.sso.provider", "ai.customer.scim.token",
        ]
        required_adapters = ["hr", "account", "stock", "purchase", "sale", "crm", "project", "mrp", "documents", "calendar"]
        required_subscribers = {"workflow", "ai", "notification", "calendar", "buzz", "telegram", "memory", "audit", "rag"}
        checks = {
            "profile": bool(profile),
            "company": bool(profile and profile.company_id),
            "required_models": {m: (m in self.env) for m in required_models},
            "required_adapters": {m: bool(self.env["ai.integration.adapter"].sudo().search_count([("module_name", "=", m), ("active", "=", True)])) for m in required_adapters if "ai.integration.adapter" in self.env},
            "subscriber_matrix": sorted(set(self.env["ai.integration.subscription"].sudo().search([]).mapped("target"))) if "ai.integration.subscription" in self.env else [],
            "capability_count": self.env["ai.control.capability"].sudo().search_count([("active", "=", True)]) if "ai.control.capability" in self.env else 0,
            "integration_operations": self.env["ai.integration.operation"].sudo().search_count([("active", "=", True)]) if "ai.integration.operation" in self.env else 0,
            "workflow_engine": "ai.workflow" in self.env,
            "async_rag": "ai.document.index.job" in self.env,
            "model_registry": "ai.model.profile" in self.env,
            "sso": "ai.customer.sso.provider" in self.env,
            "scim": "ai.customer.scim.token" in self.env,
            "frontend_capability_api": True,
        }
        checks["all_required_models"] = all(checks["required_models"].values())
        checks["all_required_adapters"] = all(checks["required_adapters"].values()) if checks["required_adapters"] else False
        checks["all_subscribers"] = required_subscribers.issubset(set(checks["subscriber_matrix"]))
        checks["ready"] = bool(checks["profile"] and checks["company"] and checks["all_required_models"] and checks["all_required_adapters"] and checks["all_subscribers"] and checks["capability_count"] and checks["integration_operations"])
        self.result_json = __import__("json").dumps(checks, sort_keys=True, ensure_ascii=False)
        if not checks["ready"] and not self.dry_run:
            raise ValueError("Deployment prerequisites failed; production activation is blocked.")
        return True
