"""Backfill the tenant boundary for existing company documents."""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        ALTER TABLE company_document
        ADD COLUMN IF NOT EXISTS company_id integer
    """)
    cr.execute("""
        UPDATE company_document
           SET company_id = (SELECT id FROM res_company ORDER BY id LIMIT 1)
         WHERE company_id IS NULL
    """)
    cr.execute("""
        ALTER TABLE ai_gateway_approval
        ADD COLUMN IF NOT EXISTS company_id integer
    """)
    cr.execute("""
        UPDATE ai_gateway_approval
           SET company_id = COALESCE(
               (SELECT company_id FROM res_users WHERE res_users.id = ai_gateway_approval.requested_by_id),
               (SELECT id FROM res_company ORDER BY id LIMIT 1)
           )
         WHERE company_id IS NULL
    """)
    cr.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM company_document WHERE company_id IS NULL) THEN
                RAISE EXCEPTION 'Cannot backfill company_document.company_id';
            END IF;
            IF EXISTS (SELECT 1 FROM ai_gateway_approval WHERE company_id IS NULL) THEN
                RAISE EXCEPTION 'Cannot backfill ai_gateway_approval.company_id';
            END IF;
            ALTER TABLE company_document ALTER COLUMN company_id SET NOT NULL;
            ALTER TABLE ai_gateway_approval ALTER COLUMN company_id SET NOT NULL;
        END $$;
    """)
    cr.execute("""
        CREATE INDEX IF NOT EXISTS company_document_company_id_idx
        ON company_document (company_id)
    """)
    cr.execute("""
        CREATE INDEX IF NOT EXISTS ai_gateway_approval_company_id_idx
        ON ai_gateway_approval (company_id)
    """)
