import logging
import os

from odoo import api, fields, models
from odoo.exceptions import UserError

from .chunking import normalize_search_text
from .embedding_client import embed_texts, to_pgvector_literal

_logger = logging.getLogger(__name__)

# Must match the certified embedding revision served by the native
# embedding unit. If the revision changes dimension, change this AND
# reindex everything - vectors of different dimensions cannot coexist
# in one pgvector column.
EMBEDDING_DIM = 1024
RAG_INDEX_VERSION = os.getenv("AI_RAG_INDEX_VERSION", "rag-v1")
RAG_MAX_QUERY_CHARS = 8_000
try:
    RAG_MAX_AUTHORIZED_DOCUMENTS = max(1_000, int(os.getenv("AI_RAG_MAX_AUTHORIZED_DOCUMENTS", "50000")))
except (TypeError, ValueError):
    RAG_MAX_AUTHORIZED_DOCUMENTS = 50_000


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


RAG_MIN_VECTOR_SCORE = _env_float("AI_RAG_MIN_VECTOR_SCORE", 0.18)
RAG_MIN_LEXICAL_SCORE = _env_float("AI_RAG_MIN_LEXICAL_SCORE", 0.01)


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
    normalized_content = fields.Text(
        help="Unicode-normalized lexical representation; original content remains citation source.",
    )
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
    source_page = fields.Integer(index=True, help="1-based source page when the parser provides it.")
    source_section = fields.Char(index=True, help="Source heading/section when available.")
    source_type = fields.Char(help="Parser block type, for example Table or paragraph.")
    source_coordinates = fields.Char(help="Serialized source bounding box when available.")
    source_table = fields.Char(help="Source table identifier or name when available.")
    source_sheet = fields.Char(help="Source spreadsheet sheet when available.")
    source_slide = fields.Integer(help="1-based presentation slide when available.")
    parser_name = fields.Char(index=True)
    parser_version = fields.Char()

    def init(self):
        """pgvector column + HNSW index aren't expressible as a
        fields.X declaration, so they're created here with raw SQL
        instead. Runs on every module install/upgrade; every
        statement is written to be safe to re-run (IF NOT EXISTS /
        existence-checked), matching how Odoo actually calls init()
        (once per -i/-u, not guaranteed to run only once ever)."""
        self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS vector")
        self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

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
            "(to_tsvector('simple', coalesce(normalized_content, content, '')))"
        )
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS ai_document_chunk_content_trgm_idx "
            "ON ai_document_chunk USING gin (normalized_content gin_trgm_ops)"
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

        Document = self.env["company.document"]
        visible_domain = []
        if "ai.control.relation" in self.env and not self.env.user.has_group("base.group_system"):
        # Resolve FGA and grant facts in two bounded queries, then let the
        # normal ORM search apply the native company/access-level record
        # rule. Central grant_allows remains additive; it never replaces
        # this pre-retrieval ACL boundary.
            # rule. The former implementation loaded every visible document
            # and called relation/grant checks once per row (N+1), which made
            # RAG latency grow with the corpus and could exhaust memory under
            # concurrent chat traffic.
            now = fields.Datetime.now()
            relation_rows = self.env["ai.control.relation"].sudo().search([
                ("subject_user_id", "=", self.env.user.id),
                ("resource_model", "in", ["company.document", "project.project", "documents.folder"]),
                ("company_id", "in", [self.env.company.id, False]),
                ("active", "=", True),
                ("starts_at", "<=", now),
                "|", ("expires_at", "=", False), ("expires_at", ">=", now),
            ], limit=5000)
            direct_ids = relation_rows.filtered(
                lambda rel: rel.resource_model == "company.document"
            ).mapped("resource_id")
            project_ids = relation_rows.filtered(
                lambda rel: rel.resource_model == "project.project"
            ).mapped("resource_id")
            folder_ids = relation_rows.filtered(
                lambda rel: rel.resource_model == "documents.folder"
            ).mapped("resource_id")
            # Four additive visibility cases: unscoped documents, direct FGA
            # document relations, project relations, and folder relations.
            visible_domain = [
                "|", "&", ("project_id", "=", False), ("folder_id", "=", False),
                "|", ("id", "in", direct_ids or [0]),
                "|", ("project_id", "in", project_ids or [0]),
                ("folder_id", "in", folder_ids or [0]),
            ]
            grant_model = (
                self.env["ai.gateway.access.grant"].sudo()
                if "ai.gateway.access.grant" in self.env else None
            )
            if grant_model is not None:
                grants = grant_model._active_grants_for(
                    self.env.user, capability="document.read"
                )
                grant_ids = grants.filtered(
                    lambda grant: (
                        not grant.resource_id
                        or (
                            grant.resource_model == "company.document"
                            and (
                                grant.grant_type != "delegated"
                                or (
                                    grant.delegated_from_id
                                    and (
                                        not grant.group_id
                                        or grant.group_id in grant.delegated_from_id.groups_id
                                    )
                                )
                            )
                        )
                    )
                )
                if any(not grant.resource_id for grant in grant_ids):
                    # A global grant is additive to the native record rule,
                    # not a bypass of it; no extra domain is necessary.
                    grant_ids = grant_ids.browse()
                else:
                    document_ids = grant_ids.filtered(
                        lambda grant: grant.resource_model == "company.document"
                    ).mapped("resource_id")
                    if document_ids:
                        visible_domain = ["|", *visible_domain, ("id", "in", document_ids)]
        visible_docs = Document.search(
            visible_domain,
            limit=RAG_MAX_AUTHORIZED_DOCUMENTS + 1,
        )
        if len(visible_docs) > RAG_MAX_AUTHORIZED_DOCUMENTS:
            raise UserError(
                "authorized document scope is too large for this retrieval path; refine the company or folder scope"
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

        safe_query = scrub_value(str(query_text or "")).strip()[:RAG_MAX_QUERY_CHARS]
        if not safe_query:
            return []
        safe_lexical_query = normalize_search_text(safe_query)

        # Retrieve a wider candidate set, apply a minimum relevance check,
        # then return only the requested number. This prevents a low-score
        # nearest neighbour from being presented as a factual answer while
        # preserving lexical hits for exact identifiers and policy codes.
        candidate_limit = min(max(top_k * 4, top_k), 100)
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
            # Keep the vector and lexical candidate scans independently
            # index-friendly. Sorting the entire ACL-filtered corpus by a
            # combined expression prevents PostgreSQL from using the HNSW
            # ordering efficiently; the small Python merge is deterministic
            # and gives exact identifiers a second chance.
            self.env.cr.execute(
                """
                SELECT c.id AS chunk_id, c.document_id AS document_id,
                       c.content AS content, c.sequence AS sequence,
                       c.source_page AS source_page, c.source_section AS source_section,
                       c.source_type AS source_type,
                       c.source_table AS source_table, c.source_sheet AS source_sheet,
                       c.source_slide AS source_slide,
                       1 - (c.embedding <=> %s::vector) AS vector_score,
                       0.0 AS lexical_score,
                       0.0 AS trigram_score
                FROM ai_document_chunk c
                WHERE c.document_id = ANY(%s)
                  AND c.index_version = %s
                  AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> %s::vector
                LIMIT %s
                """,
                (query_literal, allowed_doc_ids, RAG_INDEX_VERSION, query_literal, candidate_limit),
            )
            vector_rows = {row["chunk_id"]: row for row in self.env.cr.dictfetchall()}
            self.env.cr.execute(
                """
                SELECT c.id AS chunk_id, c.document_id AS document_id,
                       c.content AS content, c.sequence AS sequence,
                       c.source_page AS source_page, c.source_section AS source_section,
                       c.source_type AS source_type,
                       c.source_table AS source_table, c.source_sheet AS source_sheet,
                       c.source_slide AS source_slide,
                       0.0 AS vector_score,
                       ts_rank_cd(
                         to_tsvector('simple', coalesce(c.normalized_content, c.content, '')),
                         plainto_tsquery('simple', %s)
                       ) AS lexical_score,
                       0.0 AS trigram_score
                FROM ai_document_chunk c
                WHERE c.document_id = ANY(%s)
                  AND c.index_version = %s
                  AND to_tsvector('simple', coalesce(c.normalized_content, c.content, '')) @@
                      plainto_tsquery('simple', %s)
                ORDER BY lexical_score DESC
                LIMIT %s
                """,
                (safe_lexical_query, allowed_doc_ids, RAG_INDEX_VERSION, safe_lexical_query, candidate_limit),
            )
            rows = vector_rows
            for lexical_row in self.env.cr.dictfetchall():
                current = rows.get(lexical_row["chunk_id"])
                if current:
                    current["lexical_score"] = lexical_row["lexical_score"]
                else:
                    rows[lexical_row["chunk_id"]] = lexical_row
            rows = list(rows.values())
        else:
            self.env.cr.execute(
                """
                SELECT c.id AS chunk_id, c.document_id AS document_id,
                       c.content AS content, c.sequence AS sequence,
                       c.source_page AS source_page, c.source_section AS source_section,
                       c.source_type AS source_type,
                       c.source_table AS source_table, c.source_sheet AS source_sheet,
                       c.source_slide AS source_slide,
                       0.0 AS vector_score,
                       ts_rank_cd(
                         to_tsvector('simple', coalesce(c.normalized_content, c.content, '')),
                         plainto_tsquery('simple', %s)
                       ) AS lexical_score,
                       0.0 AS trigram_score
                FROM ai_document_chunk c
                WHERE c.document_id = ANY(%s)
                  AND c.index_version = %s
                  AND to_tsvector('simple', coalesce(c.normalized_content, c.content, '')) @@
                      plainto_tsquery('simple', %s)
                ORDER BY lexical_score DESC
                LIMIT %s
                """,
                (safe_lexical_query, allowed_doc_ids, RAG_INDEX_VERSION, safe_lexical_query, candidate_limit),
            )

        if not query_literal:
            rows = self.env.cr.dictfetchall()

        # Trigram search is a bounded third candidate path for short Persian
        # identifiers and typo-tolerant substring matches. The `%` operator
        # uses the pg_trgm GIN index; the threshold is local to this query and
        # never broadens the already ACL-filtered document id set.
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("SET LOCAL pg_trgm.similarity_threshold = 0.10")
                self.env.cr.execute(
                    """
                    SELECT c.id AS chunk_id, c.document_id AS document_id,
                           c.content AS content, c.sequence AS sequence,
                           c.source_page AS source_page, c.source_section AS source_section,
                           c.source_type AS source_type,
                       c.source_table AS source_table, c.source_sheet AS source_sheet,
                       c.source_slide AS source_slide,
                           0.0 AS vector_score,
                           0.0 AS lexical_score,
                           similarity(c.normalized_content, %s) AS trigram_score
                    FROM ai_document_chunk c
                    WHERE c.document_id = ANY(%s)
                      AND c.index_version = %s
                      AND c.normalized_content %% %s
                    ORDER BY c.normalized_content <-> %s
                    LIMIT %s
                    """,
                    (
                        safe_lexical_query, allowed_doc_ids, RAG_INDEX_VERSION,
                        safe_lexical_query, safe_lexical_query, candidate_limit,
                    ),
                )
                trigram_rows = self.env.cr.dictfetchall()
                if query_literal:
                    rows_by_id = {row["chunk_id"]: row for row in rows}
                    for trigram_row in trigram_rows:
                        current = rows_by_id.get(trigram_row["chunk_id"])
                        if current:
                            current["trigram_score"] = trigram_row["trigram_score"]
                        else:
                            rows_by_id[trigram_row["chunk_id"]] = trigram_row
                    rows = list(rows_by_id.values())
                else:
                    rows_by_id = {row["chunk_id"]: row for row in rows}
                    for trigram_row in trigram_rows:
                        current = rows_by_id.get(trigram_row["chunk_id"])
                        if current:
                            current["trigram_score"] = trigram_row["trigram_score"]
                        else:
                            rows_by_id[trigram_row["chunk_id"]] = trigram_row
                    rows = list(rows_by_id.values())
        except Exception:  # pg_trgm may be unavailable on a minimal database.
            _logger.info("pg_trgm candidate search unavailable", exc_info=True)

        if not rows:
            return []
        for row in rows:
            vector_score = float(row["vector_score"] or 0.0)
            lexical_score = float(row["lexical_score"] or 0.0)
            trigram_score = float(row.get("trigram_score") or 0.0)
            row["hybrid_score"] = 0.70 * vector_score + 0.20 * lexical_score + 0.10 * trigram_score
        if retrieval_mode == "hybrid":
            rows = [row for row in rows if (
                float(row["vector_score"] or 0.0) >= RAG_MIN_VECTOR_SCORE
                or float(row["lexical_score"] or 0.0) >= RAG_MIN_LEXICAL_SCORE
                or float(row.get("trigram_score") or 0.0) >= 0.10
            )]
        rows.sort(key=lambda row: row["hybrid_score"], reverse=True)
        rows = rows[:top_k]
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
                "citation": {
                    "page": row.get("source_page"),
                    "section": row.get("source_section") or "",
                    "type": row.get("source_type") or "",
                    "table": row.get("source_table") or "",
                    "sheet": row.get("source_sheet") or "",
                    "slide": row.get("source_slide"),
                },
                "similarity": round(float(row["vector_score"] or 0.0), 4),
                "lexical_score": round(float(row["lexical_score"] or 0.0), 4),
                "trigram_score": round(float(row.get("trigram_score") or 0.0), 4),
                "relevance_score": round(float(row["hybrid_score"] or 0.0), 4),
                "retrieval_mode": retrieval_mode,
            }
            for row in rows
        ]
