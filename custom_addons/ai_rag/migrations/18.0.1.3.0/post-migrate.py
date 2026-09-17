"""Backfill durable ingestion state and lexical text for the structured extractor."""

from odoo import SUPERUSER_ID, api

from odoo.addons.ai_rag.models.chunking import normalize_search_text


_CHUNK_BATCH_SIZE = 500


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    if "company.document" in env:
        documents = env["company.document"].sudo().search([("file", "!=", False)])
        for document in documents:
            document.write({
                "rag_ingestion_state": (
                    "indexed"
                    if document.rag_indexed_date and document.rag_index_version
                    else "pending"
                ),
            })

    # Existing chunks predate normalized_content. Recompute it in bounded
    # batches so the first upgrade gets Persian/Arabic lexical search without
    # loading a whole tenant corpus into one Python list. Existing citation
    # fields remain null when the old parser did not provide provenance.
    if "ai.document.chunk" not in env:
        return
    chunks = env["ai.document.chunk"].sudo()
    last_id = 0
    while True:
        batch = chunks.search(
            [("id", ">", last_id)], order="id asc", limit=_CHUNK_BATCH_SIZE
        )
        if not batch:
            break
        for chunk in batch:
            chunk.write({"normalized_content": normalize_search_text(chunk.content)})
        last_id = batch[-1].id
