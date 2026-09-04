import logging
import os

from odoo import api, fields, models
from odoo.exceptions import UserError

from .embedding_client import embed_texts, to_pgvector_literal

_logger = logging.getLogger(__name__)

# Must match the certified embedding revision served by the native
# embedding unit. If the revision changes dimension, change this AND
# reindex everything - vectors of different dimensions cannot coexist
# in one pgvector column.
EMBEDDING_DIM = 1024
RAG_INDEX_VERSION = os.getenv("AI_RAG_INDEX_VERSION", "rag-v1")


class AiDocumentChunk(models.Model):
    """A chunk of a company.document's extracted text, with its
    embedding vector (roadmap #27). Deliberately a separate model
    (not a field on company.document itself) since one document
    produces many chunks and each needs its own vector for retrieval
    to be precise - returning a whole document as one "hit" defeats
    the point of chunking.

    SECURITY: this model's own ir.rule (security/chunk_rules.xml)
    mirrors company.document's access_level rule exactly, keyed off
    document_id. That matters because raw SQL (used for the actual
    vector search below, since pgvector's <=> operator isn't
    expressible through the ORM) BYPASSES ir.rule entirely - so
    search_similar() below does NOT rely on the ir.rule for
    filtering, it pre-filters through a normal ORM search on
    company.document first (which DOES apply ir.rule) and only ever
    queries chunk rows whose document_id is in that already-filtered
    list. The ir.rule on this model is a second, independent layer
    for anyone who browses ai.document.chunk directly (e.g. the debug
    list view under Settings > Technical) - defense in depth, same
    spirit as roadmap #20's Risk Engine enforce().
    """

    _name = "ai.document.chunk"
    _description = "RAG chunk of a company.document (roadmap #27)"
    _order = "document_id, sequence"

    document_id = fields.Many2one(
        "company.document", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=0)
    content = fields.Text(required=True)
    content_hash = fields.Char(
        index=True,
        help="md5 of content - lets reindex skip re-embedding chunks "
        "that haven't actually changed, instead of re-embedding the "
        "whole document on every write.",
    )
    index_version = fields.Char(
        default=RAG_INDEX_VERSION,
        required=True,
        index=True,
        help="Immutable index/embedding revision used for safe rebuilds.",
    )

    def init(self):
        """pgvector column + HNSW index aren't expressible as a
        fields.X declaration, so they're created here with raw SQL
        instead. Runs on every module install/upgrade; every
        statement is written to be safe to re-run (IF NOT EXISTS /
        existence-checked), matching how Odoo actually calls init()
        (once per -i/-u, not guaranteed to run only once ever)."""
        self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS vector")

        self.env.cr.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'ai_document_chunk' AND column_name = 'embedding'"
        )
        if not self.env.cr.fetchone():
            self.env.cr.execute(
                "ALTER TABLE ai_document_chunk ADD COLUMN embedding vector(%s)"
                % EMBEDDING_DIM
            )

        self.env.cr.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'ai_document_chunk' "
            "AND indexname = 'ai_document_chunk_embedding_hnsw_idx'"
        )
        if not self.env.cr.fetchone():
            # HNSW is the default candidate index for this deployment;
            # the actual corpus size, memory footprint and latency must be
            # measured on the target PostgreSQL/pgvector build before any
            # production capacity claim. Revisit IVFFlat/DiskANN only if
            # the measured corpus or tenant topology justifies it.
            self.env.cr.execute(
                "CREATE INDEX ai_document_chunk_embedding_hnsw_idx "
                "ON ai_document_chunk USING hnsw (embedding vector_cosine_ops)"
            )
        # Keep a lexical signal beside vector similarity. This makes
        # exact identifiers, codes and short names retrievable even
        # when an embedding model is unavailable, and gives the normal
        # path a deterministic hybrid rank instead of semantic-only
        # retrieval.
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS ai_document_chunk_content_fts_idx "
            "ON ai_document_chunk USING gin "
            "(to_tsvector('simple', coalesce(content, '')))"
        )

    def write_embedding(self, vector):
        """Set this chunk's embedding via raw SQL (see class docstring
        for why: no ORM field type for pgvector)."""
        self.ensure_one()
        self.env.cr.execute(
            "UPDATE ai_document_chunk SET embedding = %s::vector WHERE id = %s",
            (to_pgvector_literal(vector), self.id),
        )

    @api.model
    def search_similar(self, query_text, top_k=5):
        """Hybrid retrieval with authorization before candidate generation.

        The ORM search and relation/grant checks run first. Raw SQL then
        sees only those document ids, so neither vector nor lexical ranking
        can become an ACL side channel. The normal path combines cosine
        similarity with PostgreSQL full-text rank; if the embedding service
        is unavailable, exact/lexical retrieval remains available but is
        explicitly labelled in the result. This is a resilience fallback,
        not permission fallback: the same pre-filter is used in both paths.
        """
        try:
            top_k = max(1, min(int(top_k), 50))
        except (TypeError, ValueError):
            top_k = 5

        visible_docs = self.env["company.document"].search([])
        if "ai.control.relation" in self.env:
            relation = self.env["ai.control.relation"]
            grant_model = (
                self.env["ai.gateway.access.grant"].sudo()
                if "ai.gateway.access.grant" in self.env
                else None
            )
            filtered = []
            for doc in visible_docs:
                if not (doc.project_id or doc.folder_id):
                    filtered.append(doc)
                    continue
                allowed = any(
                    relation.allows(self.env.user, rel, doc)
                    for rel in ("owner", "manager", "member", "viewer", "editor", "delegate")
                )
                if grant_model is not None and grant_model.grant_allows(
                    self.env.user, "document.read", record=doc
                ):
                    allowed = True
                if allowed or self.env.user.has_group("base.group_system"):
                    filtered.append(doc)
            visible_docs = self.env["company.document"].browse(
                [doc.id for doc in filtered]
            )
        allowed_doc_ids = visible_docs.ids
        if not allowed_doc_ids:
            return []
        if "ai.rag.index.snapshot" in self.env:
            active_snapshot = self.env["ai.rag.index.snapshot"].sudo().search([
                ("version", "=", RAG_INDEX_VERSION),
                ("company_id", "=", self.env.company.id),
                ("status", "=", "active"),
            ], limit=1)
            # Never serve a partially rebuilt revision. A caller receives no
            # result until the durable snapshot is complete and active.
            if not active_snapshot:
                return []

        from odoo.addons.ai_business_tools.models.context_firewall import scrub_value

        safe_query = scrub_value(str(query_text or "")).strip()
        if not safe_query:
            return []

        retrieval_mode = "hybrid"
        query_literal = None
        try:
            vectors = embed_texts([safe_query], env=self.env)
            if vectors:
                query_literal = to_pgvector_literal(vectors[0])
        except UserError:
            # The lexical path is useful for exact business identifiers
            # during a model restart. It never broadens the visible set.
            retrieval_mode = "lexical_fallback"

        if query_literal:
            self.env.cr.execute(
                """
                SELECT c.id AS chunk_id, c.document_id AS document_id,
                       c.content AS content, c.sequence AS sequence,
                       1 - (c.embedding <=> %s::vector) AS vector_score,
                       ts_rank_cd(
                         to_tsvector('simple', coalesce(c.content, '')),
                         plainto_tsquery('simple', %s)
                       ) AS lexical_score
                FROM ai_document_chunk c
                WHERE c.document_id = ANY(%s)
                  AND c.index_version = %s
                  AND c.embedding IS NOT NULL
                ORDER BY (
                    0.80 * (1 - (c.embedding <=> %s::vector)) +
                    0.20 * ts_rank_cd(
                      to_tsvector('simple', coalesce(c.content, '')),
                      plainto_tsquery('simple', %s)
                    )
                ) DESC
                LIMIT %s
                """,
                (
                    query_literal,
                    safe_query,
                    allowed_doc_ids,
                    RAG_INDEX_VERSION,
                    query_literal,
                    safe_query,
                    top_k,
                ),
            )
        else:
            self.env.cr.execute(
                """
                SELECT c.id AS chunk_id, c.document_id AS document_id,
                       c.content AS content, c.sequence AS sequence,
                       0.0 AS vector_score,
                       ts_rank_cd(
                         to_tsvector('simple', coalesce(c.content, '')),
                         plainto_tsquery('simple', %s)
                       ) AS lexical_score
                FROM ai_document_chunk c
                WHERE c.document_id = ANY(%s)
                  AND c.index_version = %s
                  AND to_tsvector('simple', coalesce(c.content, '')) @@
                      plainto_tsquery('simple', %s)
                ORDER BY lexical_score DESC
                LIMIT %s
                """,
                (safe_query, allowed_doc_ids, RAG_INDEX_VERSION, safe_query, top_k),
            )

        rows = self.env.cr.dictfetchall()
        if not rows:
            return []

        docs = self.env["company.document"].browse(
            [row["document_id"] for row in rows]
        )
        doc_names = {doc.id: doc.name for doc in docs}

        return [
            {
                # A customer citation needs a business document label and
                # excerpt, not local record ids, ORM names, or index metadata.
                "document_name": doc_names.get(row["document_id"], ""),
                "excerpt": scrub_value(row["content"] or ""),
                "similarity": round(float(row["vector_score"] or 0.0), 4),
                "lexical_score": round(float(row["lexical_score"] or 0.0), 4),
            }
            for row in rows
        ]
