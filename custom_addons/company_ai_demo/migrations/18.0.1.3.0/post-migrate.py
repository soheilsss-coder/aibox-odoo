"""Backfill keyed search digests for encrypted assistant memories."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    if "ai.agent.memory.record" not in env:
        return
    Memory = env["ai.agent.memory.record"].sudo()
    # A missing/rotated key must not make a database upgrade destroy or
    # rewrite ciphertext. New memories will receive tokens once the key is
    # configured; the runtime tool has a bounded legacy fallback meanwhile.
    for record in Memory.search([("value", "!=", False), ("search_tokens", "=", False)]):
        try:
            plaintext = Memory._decrypt(record.value)
            record.write({"search_tokens": Memory._search_tokens("%s %s" % (record.key, plaintext))})
        except Exception:
            continue
