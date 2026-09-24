from odoo import api, models


class IrModuleModuleIntegrationHook(models.Model):
    _inherit = "ir.module.module"

    def write(self, vals):
        result = super().write(vals)
        # Module installation happens inside a transaction. Do not commit or
        # perform a full discovery from here; the integration cron is the
        # authoritative post-transaction synchronizer.
        if vals.get("state") in ("installed", "uninstalled"):
            self.env.context.get("ai_module_state_changed")
        return result
