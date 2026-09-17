from odoo import api, fields, models


class AiIntegrationModule(models.Model):
    _name = "ai.control.module"
    _description = "AI Module Integration Registry"
    _order = "name"

    name = fields.Char(required=True, index=True)
    technical_name = fields.Char(required=True, index=True)
    version = fields.Char()
    state = fields.Selection([
        ("installed", "Installed"), ("not_installed", "Not Installed"),
        ("error", "Error")
    ], default="installed", required=True)
    adapter_key = fields.Char()
    integration_level = fields.Selection([
        ("discovered_read_only", "Discovered / Read-only"),
        ("reviewed_operational", "Reviewed / Operational"),
        ("blocked", "Blocked until reviewed"),
    ], default="discovered_read_only", required=True, index=True)
    certification_state = fields.Selection([
        ("discovered", "Discovered"),
        ("baseline_ready", "Baseline ready"),
        ("adapter_required", "Adapter required"),
        ("runtime_certified", "Runtime certified"),
        ("blocked", "Blocked"),
    ], default="discovered", required=True, index=True)
    automatic_read = fields.Boolean(default=True)
    automatic_events = fields.Boolean(default=True)
    automatic_audit = fields.Boolean(default=True)
    # This is deliberately separate from integration_level: a module can have
    # a read-only/discovered integration and still be connected to the one
    # local Company Assistant. Connection means the agent knows the module's
    # registered tool surface; authorization decides what a user may invoke.
    agent_connected = fields.Boolean(default=False, index=True)
    agent_connection_state = fields.Selection([
        ("connected", "Connected"),
        ("connected_no_tools", "Connected / no approved tools"),
        ("error", "Connection error"),
        ("disconnected", "Disconnected"),
    ], default="disconnected", required=True, index=True)
    agent_tool_count = fields.Integer(default=0)
    agent_operation_count = fields.Integer(default=0)
    agent_last_sync = fields.Datetime()
    agent_error = fields.Text()
    discovered_models = fields.Integer(default=0)
    discovered_groups = fields.Integer(default=0)
    discovered_menus = fields.Integer(default=0)
    discovered_views = fields.Integer(default=0)
    menu_names_json = fields.Text(default="[]")
    view_names_json = fields.Text(default="[]")
    scope_json = fields.Text(default="{}")
    capability_count = fields.Integer(default=0)
    discovered_operation_count = fields.Integer(default=0)
    reviewed_operation_count = fields.Integer(default=0)
    unavailable_mutations_json = fields.Text(default="[]")
    last_sync = fields.Datetime()
    last_error = fields.Text()
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("technical_name_unique", "unique(technical_name)", "Module already registered."),
    ]

    @api.model
    def sync_installed_modules(self):
        Module = self.env["ir.module.module"].sudo()
        installed = Module.search([("state", "=", "installed")])
        installed_names = set(installed.mapped("name"))
        for mod in installed:
            rec = self.sudo().search([("technical_name", "=", mod.name)], limit=1)
            vals = {
                "name": mod.shortdesc or mod.name,
                "technical_name": mod.name,
                "version": mod.installed_version or mod.latest_version or "",
                "state": "installed",
                "adapter_key": "builtin.%s" % mod.name,
                "last_sync": fields.Datetime.now(),
                "last_error": False,
            }
            try:
                model_meta = self.env["ir.model"].sudo().search([("model", "!=", False)])
                model_names = [
                    record.model for record in model_meta
                    if mod.name in {item.strip() for item in (record.modules or "").split(",") if item.strip()}
                ]
                groups = self.env["res.groups"].sudo().search([("category_id", "!=", False), ("module", "ilike", mod.name)]) if "module" in self.env["res.groups"]._fields else self.env["res.groups"].browse()
                vals.update({"discovered_models": len(model_names), "discovered_groups": len(groups)})
                rec = rec or self.sudo().create(vals)
                rec.write(vals)
            except Exception as exc:
                vals.update({"state": "error", "last_error": str(exc)})
                (rec or self.sudo().create(vals)).write(vals)
        self.sudo().search([("technical_name", "not in", list(installed_names))]).write({
            "state": "not_installed", "integration_level": "blocked", "certification_state": "blocked",
            "automatic_read": False, "automatic_events": False, "automatic_audit": False,
            "agent_connected": False, "agent_connection_state": "disconnected",
            "agent_tool_count": 0, "agent_operation_count": 0,
            "agent_last_sync": fields.Datetime.now(),
            "agent_error": False,
        })
        return True

    @api.model
    def sync_now(self):
        return self.sync_installed_modules()
