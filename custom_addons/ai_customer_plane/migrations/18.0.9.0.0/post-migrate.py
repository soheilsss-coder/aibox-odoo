"""Initialize lifecycle metadata introduced for applied profile releases."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    profiles = env["ai.customer.configuration.profile"].sudo().search([
        ("deployment_result_json", "=", False),
    ])
    if profiles:
        profiles.write({"deployment_result_json": "{}"})
    history = env["ai.customer.configuration.profile.history"].sudo()
    for profile in env["ai.customer.configuration.profile"].sudo().search([]):
        history.create_snapshot(profile, reason="18.0.9 lifecycle and feature policy backfill")
