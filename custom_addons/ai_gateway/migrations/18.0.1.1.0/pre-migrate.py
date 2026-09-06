"""Remove legacy plaintext API-key material before the new registry loads."""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ai_gateway_api_key' AND column_name = 'key'
            ) THEN
                UPDATE ai_gateway_api_key SET key = NULL WHERE key IS NOT NULL;
            END IF;
        END $$;
    """)
