"""Backfill the universal onboarding trigger set after upgrade."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # Existing operation rows predate the explicit coverage field. A read
    # operation must never inherit the new operational default during upgrade.
    cr.execute("""
        UPDATE ai_integration_operation
           SET source = COALESCE(source, 'reviewed'),
               coverage = CASE
                               WHEN operation = 'read' AND COALESCE(source, 'reviewed') = 'discovered' THEN 'discovered_read'
                               WHEN operation = 'read' THEN 'reviewed_read'
                               ELSE COALESCE(coverage, 'reviewed_operational')
                          END
         WHERE source IS NULL OR coverage IS NULL OR operation = 'read'
    """)
    env = api.Environment(cr, SUPERUSER_ID, {})
    trigger_manager = env["ai.integration.change.trigger"]
    trigger_manager.ensure_triggers()
    env["ai.control.module"].sync_installed_modules()
