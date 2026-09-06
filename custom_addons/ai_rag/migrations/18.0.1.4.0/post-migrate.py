"""Install the materialized lexical vector for the 1.4 RAG contract.

The model ``init()`` owns extension/index creation. This post-migration is
idempotent and only backfills rows when the columns are available; it never
changes the configured embedding revision or starts a remote/model call.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'ai_document_chunk'
          AND column_name = 'search_vector'
    """)
    if cr.fetchone():
        cr.execute("""
            UPDATE ai_document_chunk
               SET search_vector = to_tsvector(
                   'simple', coalesce(normalized_content, content, '')
               )
             WHERE search_vector IS NULL
        """)
