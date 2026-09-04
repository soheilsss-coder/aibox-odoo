"""Prepare browser sessions for the mandatory anti-CSRF token.

Existing sessions cannot be given a token that the browser knows, so revoke
all of them during the upgrade. Users must log in again; this is safer than
silently retaining a session that cannot satisfy the new mutation contract.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        ALTER TABLE ai_gateway_session
        ADD COLUMN IF NOT EXISTS csrf_token_hash varchar;
    """)
    cr.execute("""
        UPDATE ai_gateway_session
           SET csrf_token_hash = 'revoked-during-csrf-upgrade-' || id,
               revoked_at = COALESCE(revoked_at, NOW())
         WHERE csrf_token_hash IS NULL;
    """)
    cr.execute("""
        ALTER TABLE ai_gateway_session
        ALTER COLUMN csrf_token_hash SET NOT NULL;
    """)
