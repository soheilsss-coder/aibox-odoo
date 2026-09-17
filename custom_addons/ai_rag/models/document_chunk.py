import logging
import os

from odoo import api, fields, models
from odoo.exceptions import UserError

from .chunking import normalize_search_text
from .embedding_client import embed_texts, to_pgvector_literal
from .ranking import reciprocal_rank_fusion
from .reranker_client import rerank_texts

_logger = logging.getLogger(__name__)

# Must match the certified embedding revision served by the native
# embedding unit. If the revision changes dimension, change this AND
# reindex everything - vectors of different dimensions cannot coexist
# in one pgvector column. Deployment-specific via AI_RAG_EMBEDDING_DIM
# (the default 1024 targets a native vLLM BGE-M3-class unit; the local
# CPU serving unit uses 384-dim MiniLM).
try:
    EMBEDDING_DIM = max(64, int(os.getenv("AI_RAG_EMBEDDING_DIM", "1024")))
except (TypeError, ValueError):
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
try:
    RAG_CANDIDATE_LIMIT = max(20, min(int(os.getenv("AI_RAG_CANDIDATE_LIMIT", "60")), 200))
except (TypeError, ValueError):
    RAG_CANDIDATE_LIMIT = 60
try:
    RAG_RRF_K = max(1, min(int(os.getenv("AI_RAG_RRF_K", "60")), 1000))
except (TypeError, ValueError):
    RAG_RRF_K = 60
RAG_RERANK_ENABLED = os.getenv("AI_RAG_RERANK_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int_env(name, default, minimum, maximum):
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except (TypeError, ValueError):
        return default


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
        else:
            # Reconcile a deployment that switched embedding revisions. A
            # column created under a different vector dimension rejects
            # every new vector outright; rebuild the column/index for the
            # configured dimension. Existing vectors of the old revision
            # must be reindexed (the module-level comment says exactly this).
            self.env.cr.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'ai_document_chunk'::regclass AND attname = 'embedding'"
            )
            coltype = self.env.cr.fetchone()
            if coltype and coltype[0] != "vector" and ("(%d)" % EMBEDDING_DIM) not in coltype[0]:
                self.env.cr.execute("DROP INDEX IF EXISTS ai_document_chunk_embedding_hnsw_idx")
                self.env.cr.execute(
                    "ALTER TABLE ai_document_chunk ALTER COLUMN embedding TYPE vector(%s) "
                    "USING embedding::vector(%s)" % (EMBEDDING_DIM, EMBEDDING_DIM)
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
        # Materialize the lexical document vector once per write. The
        # expression index above remains for backwards compatibility, while
        # this stored vector avoids rebuilding to_tsvector during every rank
        # calculation on a large corpus.
        self.env.cr.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'ai_document_chunk' AND column_name = 'search_vector'"
        )
        if not self.env.cr.fetchone():
            self.env.cr.execute("ALTER TABLE ai_document_chunk ADD COLUMN search_vector tsvector")
        self.env.cr.execute(
            "UPDATE ai_document_chunk SET search_vector = to_tsvector('simple', coalesce(normalized_content, content, '')) "
            "WHERE search_vector IS NULL"
        )
        self.env.cr.execute(
            """
            CREATE OR REPLACE FUNCTION ai_document_chunk_search_vector_trigger()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                NEW.search_vector := to_tsvector('simple', coalesce(NEW.normalized_content, NEW.content, ''));
                RETURN NEW;
            END $$
            """
        )
        self.env.cr.execute(
            "DROP TRIGGER IF EXISTS ai_document_chunk_search_vector_update ON ai_document_chunk"
        )
        self.env.cr.execute(
            """
            CREATE TRIGGER ai_document_chunk_search_vector_update
            BEFORE INSERT OR UPDATE OF normalized_content, content ON ai_document_chunk
            FOR EACH ROW EXECUTE FUNCTION ai_document_chunk_search_vector_trigger()
            """
        )
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS ai_document_chunk_search_vector_idx "
            "ON ai_document_chunk USING gin (search_vector)"
        )
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

    def _configure_hnsw_scan(self):
        """Enable filtered iterative scans when the installed extension has it.

        pgvector 0.8.0 introduced this setting. The savepoint makes the
        upgrade safe on older customer databases: an unknown GUC rolls back
        only this optional tuning operation and cannot poison the request
        transaction. Values are bounded from environment configuration.
        """
        try:
            self.env.cr.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
            version = self.env.cr.fetchone()
            parts = tuple(int(part) for part in str(version[0]).split(".")[:2]) if version else ()
            if parts < (0, 8):
                return False
            scan = os.getenv("AI_RAG_HNSW_ITERATIVE_SCAN", "relaxed_order").strip()
            if scan not in {"strict_order", "relaxed_order"}:
                scan = "relaxed_order"
            ef_search = _bounded_int_env("AI_RAG_HNSW_EF_SEARCH", 100, 10, 10_000)
            max_scan = _bounded_int_env("AI_RAG_HNSW_MAX_SCAN_TUPLES", 20_000, 1_000, 1_000_000)
            scan_mem = _env_float("AI_RAG_HNSW_SCAN_MEM_MULTIPLIER", 1.0)
            scan_mem = max(1.0, min(scan_mem, 8.0))
            with self.env.cr.savepoint():
                self.env.cr.execute("SET LOCAL hnsw.iterative_scan = %s" % scan)
                self.env.cr.execute("SET LOCAL hnsw.ef_search = %d" % ef_search)
                self.env.cr.execute("SET LOCAL hnsw.max_scan_tuples = %d" % max_scan)
                self.env.cr.execute("SET LOCAL hnsw.scan_mem_multiplier = %s" % scan_mem)
            return True
        except Exception:  # older pgvector builds simply use the base scan
            _logger.info("filtered iterative HNSW scan unavailable", exc_info=True)
            return False

    @api.model
    def _rerank_is_available(self):
        if RAG_RERANK_ENABLED:
            return True
        if "ai.model.router" in self.env:
            try:
                self.env["ai.model.router"].route(purpose="rerank", requires_tools=False)
                return True
            except Exception:
                return False
        return False

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

        # Retrieve a wide, bounded candidate set. Each retriever is ranked
        # independently and fused by RRF below; raw cosine/FTS/trigram
        # scores are not comparable enough to add with fixed weights.
        candidate_limit = min(max(RAG_CANDIDATE_LIMIT, top_k * 4), 200)
        retrieval_mode = "hybrid"
        query_literal = None
        try:
            vectors = embed_texts([safe_query], env=self.env, is_query=True)
            if vectors:
                query_literal = to_pgvector_literal(vectors[0])
        except UserError:
            # The lexical path is useful for exact business identifiers
            # during a model restart. It never broadens the visible set.
            retrieval_mode = "lexical_fallback"

        vector_rows = []
        lexical_rows = []
        trigram_rows = []
        if query_literal:
            # Keep vector, lexical and typo-tolerant scans independently
            # index-friendly. The ACL boundary is already represented by
            # allowed_doc_ids and is repeated in every candidate query.
            self._configure_hnsw_scan()
            self.env.cr.execute(
                """
                SELECT c.id AS chunk_id, c.document_id AS document_id,
                       c.content AS content, c.sequence AS sequence,
                       c.source_page AS source_page, c.source_section AS source_section,
                       c.source_type AS source_type, c.source_coordinates AS source_coordinates,
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
            vector_rows = self.env.cr.dictfetchall()

        self.env.cr.execute(
            """
            SELECT c.id AS chunk_id, c.document_id AS document_id,
                   c.content AS content, c.sequence AS sequence,
                   c.source_page AS source_page, c.source_section AS source_section,
                   c.source_type AS source_type, c.source_coordinates AS source_coordinates,
                   c.source_table AS source_table, c.source_sheet AS source_sheet,
                   c.source_slide AS source_slide,
                   0.0 AS vector_score,
                   ts_rank_cd(
                     c.search_vector,
                     plainto_tsquery('simple', %s)
                   ) AS lexical_score,
                   0.0 AS trigram_score
            FROM ai_document_chunk c
            WHERE c.document_id = ANY(%s)
              AND c.index_version = %s
              AND c.search_vector @@ plainto_tsquery('simple', %s)
            ORDER BY lexical_score DESC
            LIMIT %s
            """,
            (safe_lexical_query, allowed_doc_ids, RAG_INDEX_VERSION, safe_lexical_query, candidate_limit),
        )
        lexical_rows = self.env.cr.dictfetchall()

        # Trigram search is a bounded third candidate path for short Persian
        # identifiers and typo-tolerant substring matches. The `%` operator
        # uses the pg_trgm index; the threshold is local to this query and
        # never broadens the already ACL-filtered document id set.
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("SET LOCAL pg_trgm.similarity_threshold = 0.10")
                self.env.cr.execute(
                    """
                    SELECT c.id AS chunk_id, c.document_id AS document_id,
                           c.content AS content, c.sequence AS sequence,
                           c.source_page AS source_page, c.source_section AS source_section,
                           c.source_type AS source_type, c.source_coordinates AS source_coordinates,
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
        except Exception:  # pg_trgm may be unavailable on a minimal database.
            _logger.info("pg_trgm candidate search unavailable", exc_info=True)

        rows = reciprocal_rank_fusion(
            [vector_rows, lexical_rows, trigram_rows],
            rrf_k=RAG_RRF_K,
        )
        if not rows:
            return []

        # Raw thresholds are only a minimum relevance guard. Ranking is RRF,
        # and optionally a local cross-encoder reranks the already-authorized
        # candidates. A failed optional reranker never becomes a permission or
        # availability fallback.
        if retrieval_mode == "hybrid":
            rows = [row for row in rows if (
                float(row.get("vector_score") or 0.0) >= RAG_MIN_VECTOR_SCORE
                or float(row.get("lexical_score") or 0.0) >= RAG_MIN_LEXICAL_SCORE
                or float(row.get("trigram_score") or 0.0) >= 0.10
            )]
        if not rows:
            return []

        if self._rerank_is_available() and len(rows) > 1:
            try:
                rerank_indices, rerank_scores, rerank_revision = rerank_texts(
                    safe_query,
                    [str(row.get("content") or "") for row in rows],
                    top_n=top_k,
                    env=self.env,
                )
                reranked = []
                for index, score in zip(rerank_indices, rerank_scores):
                    if 0 <= index < len(rows):
                        row = dict(rows[index])
                        row["rerank_score"] = round(float(score), 6)
                        row["reranker_revision"] = rerank_revision
                        reranked.append(row)
                if reranked:
                    rows = reranked
                    retrieval_mode = retrieval_mode + "_reranked"
            except UserError:
                _logger.info("optional local reranker unavailable; using RRF", exc_info=True)

        rows = rows[:top_k]
        if "ai.customer.configuration.profile" in self.env:
            profile = self.env["ai.customer.configuration.profile"].active_for_company(self.env.company)
            document_policy = profile.runtime_config().get("sections", {}).get("document_policy", {}) if profile else {}
            if document_policy.get("citation_required"):
                rows = [row for row in rows if any(
                    row.get(key) not in (None, "")
                    for key in ("source_page", "source_section", "source_type", "source_table", "source_sheet", "source_slide")
                )]
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
                    "coordinates": row.get("source_coordinates") or "",
                    "table": row.get("source_table") or "",
                    "sheet": row.get("source_sheet") or "",
                    "slide": row.get("source_slide"),
                },
                "similarity": round(float(row["vector_score"] or 0.0), 4),
                "lexical_score": round(float(row["lexical_score"] or 0.0), 4),
                "trigram_score": round(float(row.get("trigram_score") or 0.0), 4),
                "relevance_score": round(float(row["hybrid_score"] or 0.0), 4),
                "rrf_score": round(float(row.get("rrf_score") or row["hybrid_score"] or 0.0), 6),
                "rerank_score": round(float(row.get("rerank_score") or 0.0), 6),
                "retrieval_ranks": row.get("retrieval_ranks") or {},
                "reranker_revision": row.get("reranker_revision") or "",
                "retrieval_mode": retrieval_mode,
            }
            for row in rows
        ]
