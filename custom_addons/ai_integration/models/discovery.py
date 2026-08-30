import json
from odoo import api, fields, models


class AiIntegrationDiscovery(models.Model):
    _inherit = "ai.control.module"

    model_names_json = fields.Text(default="[]")
    group_names_json = fields.Text(default="[]")
    capability_names_json = fields.Text(default="[]")
    integration_status = fields.Selection([
        ("ready", "Ready"), ("warning", "Warning"), ("failed", "Failed")
    ], default="ready")

    def _safe_model_names(self, module):
        Model = self.env["ir.model"].sudo()
        records = Model.search([("model", "!=", False), ("modules", "ilike", module)])
        return sorted(set(records.mapped("model")))

    @api.model
    def sync_installed_modules(self):
        result = super().sync_installed_modules()
        Module = self.env["ir.module.module"].sudo()
        installed = Module.search([("state", "=", "installed")])
        Adapter = self.env["ai.integration.adapter"].sudo()
        Cap = self.env["ai.control.capability"].sudo()
        for mod in installed:
            rec = self.sudo().search([("technical_name", "=", mod.name)], limit=1)
            if not rec:
                continue
            models = self._safe_model_names(mod.name)
            groups = self.env["res.groups"].sudo().search([("category_id", "!=", False)])
            group_names = sorted(g.name for g in groups if mod.name in (getattr(g, "module", "") or ""))
            adapter = Adapter.for_module(mod.name)
            cap_names = []
            if adapter:
                cap_names = Cap.search([("module_name", "=", mod.name), ("active", "=", True)]).mapped("name")
            # Generic READ capabilities are deliberately the only dynamic capabilities.
            # Writes/approvals must come from a reviewed adapter.
            for model_name in models:
                cap_name = "%s.read" % model_name
                if not Cap.search([("name", "=", cap_name)], limit=1):
                    Cap.create({
                        "name": cap_name,
                        "module_name": mod.name,
                        "description": "Discovered read-only capability for %s" % model_name,
                        "operation": "read",
                        "risk_level": 0,
                        "model_name": model_name,
                        "source": "discovered",
                    })
                    cap_names.append(cap_name)
            rec.write({
                "capability_count": len(set(cap_names)),
                "model_names_json": json.dumps(models),
                "group_names_json": json.dumps(group_names),
                "capability_names_json": json.dumps(sorted(set(cap_names))),
                "integration_status": "ready" if adapter or models else "warning",
            })
            if "ai.integration.test.runner" in self.env:
                try:
                    test = self.env["ai.integration.test.runner"].run_for_module(mod.name)
                    rec.write({"integration_status": "ready" if test["status"] == "pass" else "failed"})
                except Exception as exc:
                    rec.write({"integration_status": "failed", "last_error": str(exc)})
        return result
