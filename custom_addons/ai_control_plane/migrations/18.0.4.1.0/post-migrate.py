"""Make module onboarding due immediately after the control-plane upgrade."""

from odoo import SUPERUSER_ID, api, fields


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref("ai_control_plane.cron_discover_modules", raise_if_not_found=False)
    if cron:
        cron.write({
            "interval_number": 1,
            "interval_type": "minutes",
            "nextcall": fields.Datetime.now(),
        })
