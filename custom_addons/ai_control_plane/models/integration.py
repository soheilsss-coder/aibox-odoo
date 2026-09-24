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
    discovered_models = fields.Integer(default=0)
    discovered_groups = fields.Integer(default=0)
    capability_count = fields.Integer(default=0)
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
                model_names = self.env["ir.model"].sudo().search([("model", "!=", False), ("modules", "ilike", mod.name)]).mapped("model")
                groups = self.env["res.groups"].sudo().search([("category_id", "!=", False), ("module", "ilike", mod.name)]) if "module" in self.env["res.groups"]._fields else self.env["res.groups"].browse()
                vals.update({"discovered_models": len(model_names), "discovered_groups": len(groups)})
                rec = rec or self.sudo().create(vals)
                rec.write(vals)
            except Exception as exc:
                vals.update({"state": "error", "last_error": str(exc)})
                (rec or self.sudo().create(vals)).write(vals)
        self.sudo().search([("technical_name", "not in", list(installed_names))]).write({"state": "not_installed"})
        return True

    @api.model
    def sync_now(self):
        return self.sync_installed_modules()
