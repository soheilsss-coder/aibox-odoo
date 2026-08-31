import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class IrModuleModuleIntegrationHook(models.Model):
    _inherit = "ir.module.module"

    def write(self, vals):
        result = super().write(vals)
        if vals.get("state") in ("installed", "uninstalled"):
            # Never run discovery inside the module installation transaction:
            # the registry is still being rebuilt and a partial model graph is
            # unsafe. Instead make the authoritative onboarding cron due as
            # soon as this transaction commits. The one-minute schedule is the
            # crash/restart fallback, so no administrator action is required.
            cron = self.env.ref("ai_control_plane.cron_discover_modules", raise_if_not_found=False)
            if cron:
                def enqueue_onboarding():
                    try:
                        cron.sudo().write({"nextcall": fields.Datetime.now()})
                    except Exception:  # noqa: BLE001
                        _logger.exception("Could not enqueue automatic module onboarding")
                self.env.cr.postcommit.add(enqueue_onboarding)
        return result
