"""Backfill ownership for the artifact tool risk contract."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["ai.gateway.tool.risk"].sudo().search([
        ("tool_name", "=", "generate_artifact"),
    ], limit=1).write({"module_name": "ai_experience"})
