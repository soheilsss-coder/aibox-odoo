import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from .embedding_client import embed_texts, to_pgvector_literal  # noqa: F401 (EMBEDDING_DIM imported below the comment)

_logger = logging.getLogger(__name__)

# Column width - imported from embedding_client (single source of
# truth so the dimension check there and the CREATE TABLE ... vector(N)
# here can never drift apart). The certified model is
# Qwen3-Embedding-0.6B (1024-dim native); shorter stand-in models are
# zero-padded by embed_texts (cosine-preserving), LONGER ones are
# rejected there. Switching to a longer model means a NEW column +
# full reindex - vectors of different dimensions cannot coexist.
from .embedding_client import EMBEDDING_DIM


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
            # HNSW, not IVFFlat, and no pgvectorscale/DiskANN: this
            # project sells one device per one customer (see README
            # "A note on scope"), so the corpus here is one company's
            # documents - thousands of chunks at most, nowhere near
            # the tens-of-millions-of-vectors range where DiskANN's
            # extra complexity starts to pay for itself. Plain pgvector
            # HNSW is single-digit-millisecond at this scale. Revisit
            # only if this module is ever repurposed for a shared
            # multi-tenant deployment (which the roadmap's intro
            # explicitly says this project is NOT doing).
            self.env.cr.execute(
                "CREATE INDEX ai_document_chunk_embedding_hnsw_idx "
                "ON ai_document_chunk USING hnsw (embedding vector_cosine_ops)"
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
        """Semantic search restricted to documents the CURRENT user can
        already read. THE ACCESS FILTER RUNS FIRST: company.document
        is searched normally through the ORM (self.env.user, ir.rule
        applies exactly as it does for list_documents/get_document),
        and only THAT already-filtered id list is ever passed into the
        raw-SQL vector query below - a chunk belonging to a document
        this user can't open is never compared against the query
        vector, let alone returned. This is the specific requirement
        roadmap #27 calls out (filter before the vector search, not
        after) and the reason this method isn't just `ORDER BY
        embedding <=> query LIMIT k` with no WHERE clause.
        """
        visible_docs = self.env["company.document"].search([])
        if "ai.control.relation" in self.env:
            relation = self.env["ai.control.relation"]
            grant_model = self.env["ai.gateway.access.grant"].sudo() if "ai.gateway.access.grant" in self.env else None
            filtered = []
            for doc in visible_docs:
                if not (doc.project_id or doc.folder_id):
                    filtered.append(doc)
                    continue
                allowed = any(relation.allows(self.env.user, rel, doc) for rel in ("owner", "manager", "member", "viewer", "editor", "delegate"))
                if grant_model and grant_model.grant_allows(self.env.user, "document.read", record=doc):
                    allowed = True
                if allowed or self.env.user.has_group("base.group_system"):
                    filtered.append(doc)
            visible_docs = self.env["company.document"].browse([d.id for d in filtered])
        allowed_doc_ids = visible_docs.ids
        if not allowed_doc_ids:
            return []

        from odoo.addons.ai_business_tools.models.context_firewall import scrub_value
        safe_query = scrub_value(query_text)
        try:
            vectors = embed_texts([safe_query], env=self.env)
        except UserError:
            vectors = []
        if not vectors:
            # Embedding server down / no certified model: degrade to a
            # keyword search over the SAME access-filtered chunk set
            # instead of hard-failing the whole tool (labeled
            # mode=keyword_fallback so callers know the ranking is
            # lexical, not semantic - never a silent fake of semantics).
            return self._keyword_fallback(safe_query, allowed_doc_ids, top_k)
        query_literal = to_pgvector_literal(vectors[0])

        self.env.cr.execute(
            """
            SELECT c.id AS chunk_id, c.document_id AS document_id,
                   c.content AS content, c.sequence AS sequence,
                   1 - (c.embedding <=> %s::vector) AS similarity
            FROM ai_document_chunk c
            WHERE c.document_id = ANY(%s) AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s
            """,
            (query_literal, allowed_doc_ids, query_literal, top_k),
        )
        rows = self.env.cr.dictfetchall()
        if not rows:
            return []

        docs = self.env["company.document"].browse(
            [r["document_id"] for r in rows]
        )
        doc_names = {d.id: d.name for d in docs}

        return [
            {
                "document_id": r["document_id"],
                "document_name": doc_names.get(r["document_id"], ""),
                "excerpt": r["content"],
                "similarity": round(float(r["similarity"]), 4),
                "mode": "semantic",
            }
            for r in rows
        ]

    def _keyword_fallback(self, query, allowed_doc_ids, top_k):
        # Access semantics IDENTICAL to the vector path: only chunks
        # whose document_id is in the already-ir.rule-filtered
        # allowed_doc_ids are ever touched - the fallback can never
        # surface more than semantic search could.
        tokens = [t for t in query.replace("؟", " ").split() if len(t) >= 3][:6]
        if not tokens:
            return []
        conds = ["document_id = ANY(%s)"] + ["content ILIKE %s"] * len(tokens)
        params = [allowed_doc_ids] + ["%" + t + "%" for t in tokens]
        self.env.cr.execute(
            "SELECT c.id, c.document_id, c.content FROM ai_document_chunk c "
            "WHERE " + " AND ".join(conds) + " ORDER BY c.document_id, c.sequence LIMIT %s",
            params + [top_k],
        )
        rows = self.env.cr.fetchall()
        if not rows:
            return []
        docs = self.env["company.document"].browse([r[1] for r in rows])
        doc_names = {d.id: d.name for d in docs}
        _logger.warning(
            "RAG semantic embedding unavailable - keyword fallback returned "
            "%s hits (user %s)", len(rows), self.env.user.login,
        )
        return [
            {
                "document_id": r[1],
                "document_name": doc_names.get(r[1], ""),
                "excerpt": r[2],
                "similarity": None,
                "mode": "keyword_fallback",
            }
            for r in rows
        ]
