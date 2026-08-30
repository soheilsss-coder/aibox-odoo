def migrate(cr, version):
    # Secret material must never survive the v41 upgrade. The ORM field is
    # intentionally gone from the model; explicitly clear the legacy column
    # before the module registry is rebuilt.
    cr.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='ai_gateway_api_key' AND column_name='key'
            ) THEN
                UPDATE ai_gateway_api_key SET key = NULL WHERE key IS NOT NULL;
            END IF;
        END $$;
    """)
