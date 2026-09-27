"""Backfill ownership for the semantic-search tool risk contract."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["ai.gateway.tool.risk"].sudo().search([
        ("tool_name", "=", "search_documents_semantic"),
    ], limit=1).write({"module_name": "ai_rag"})
