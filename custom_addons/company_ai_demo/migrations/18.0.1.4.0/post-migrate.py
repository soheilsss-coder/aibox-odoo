"""Prepare structured facts for the explicit embedding revision contract.

Existing vectors are retained for rollback/audit but are made non-recallable
until the local embedding worker reindexes them with the active
``AI_RAG_INDEX_VERSION`` and model revision. No model call is made in a
migration transaction.
"""

import os


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = 'ai_agent_memory_fact'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'ai_agent_memory_fact'
          AND column_name = 'embedding_index_version'
    """)
    if not cr.fetchone():
        return
    index_version = os.getenv("AI_RAG_INDEX_VERSION", "rag-v1")
    cr.execute(
        """
        UPDATE ai_agent_memory_fact
           SET embedding_state = 'pending',
               embedding_error = 'embedding revision migration requires local reindex',
               embedding_index_version = %s
         WHERE status = 'confirmed'
        """,
        (index_version,),
    )
