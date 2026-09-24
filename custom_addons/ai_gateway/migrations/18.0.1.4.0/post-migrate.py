"""Attach existing chat threads to their user's personal assistant identity."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    if "llm.thread" not in env:
        return
    Identity = env["ai.gateway.agent.identity"].sudo()
    Thread = env["llm.thread"].sudo()
    for thread in Thread.search([
        ("personal_agent_identity_id", "=", False),
        ("create_uid", "!=", False),
    ]):
        identity = Identity.ensure_personal(user=thread.create_uid)
        if identity:
            thread.write({"personal_agent_identity_id": identity.id})
