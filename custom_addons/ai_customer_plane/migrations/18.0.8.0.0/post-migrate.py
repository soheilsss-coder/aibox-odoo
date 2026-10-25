"""Backfill an immutable history snapshot for existing configuration profiles."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Profile = env["ai.customer.configuration.profile"].sudo()
    History = env["ai.customer.configuration.profile.history"].sudo()
    for profile in Profile.search([]):
        exists = History.search_count([
            ("profile_id", "=", profile.id),
            ("profile_version", "=", profile.version),
        ])
        if not exists:
            History.create_snapshot(profile, reason="migration backfill")
