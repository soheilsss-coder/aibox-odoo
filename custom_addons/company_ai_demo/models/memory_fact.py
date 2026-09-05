"""Structured, source-linked memory facts kept in the Odoo ORM.

The legacy ``ai.agent.memory.record`` model remains compatible with existing
users. Facts add temporal state, provenance and semantic recall without
introducing a second memory database or bypassing Odoo's company/department
boundaries.
"""
from __future__ import annotations

import html
import logging
import math
import os
import re
from typing import Any

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)
FACT_EMBEDDING_DIM = 1024
FACT_INDEX_VERSION = os.getenv("AI_RAG_INDEX_VERSION", "rag-v1")
FACT_EMBEDDING_REVISION = os.getenv(
    "AI_VLLM_EMBEDDING_REVISION",
    os.getenv("AI_VLLM_EMBEDDING_MODEL", "embedding-model"),
)


def _normal(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _plain_message(body: Any) -> str:
    value = html.unescape(str(body or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(value.split())


class AiAgentMemoryFact(models.Model):
    _name = "ai.agent.memory.fact"
    _description = "Structured Enterprise Agent Memory Fact"
    _order = "valid_from desc, created_at desc, id desc"

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company, ondelete="cascade",
    )
    department_id = fields.Many2one("hr.department", index=True, ondelete="set null")
    scope = fields.Selection([
        ("personal", "Personal"), ("department", "Department"), ("company", "Company"),
    ], required=True, default="personal", index=True)
    classification = fields.Selection([
        ("public", "Public"), ("internal", "Internal"),
        ("confidential", "Confidential"), ("restricted", "Restricted"),
    ], required=True, default="internal", index=True)

    # Subject and predicate are kept as bounded metadata for indexed matching;
    # the object and source quote are encrypted through the existing memory
    # codec because they are the sensitive part of a fact.
    subject = fields.Char(required=True, index=True)
    predicate = fields.Char(required=True, index=True)
    object_value = fields.Text(required=True, copy=False, readonly=True)
    object_type = fields.Selection([
        ("text", "Text"), ("number", "Number"), ("date", "Date"),
        ("boolean", "Boolean"), ("entity", "Entity"), ("json", "JSON"),
    ], required=True, default="text")
    search_tokens = fields.Text(copy=False, readonly=True, index=True)

    status = fields.Selection([
        ("candidate", "Candidate"), ("confirmed", "Confirmed"),
        ("superseded", "Superseded"), ("rejected", "Rejected"), ("expired", "Expired"),
    ], required=True, default="candidate", index=True)
    confirmation_required = fields.Boolean(default=True, index=True)
    confidence = fields.Float(default=0.0, index=True)
    importance = fields.Float(default=0.5, index=True)

    source_message_id = fields.Many2one("mail.message", index=True, ondelete="set null")
    source_thread_id = fields.Integer(index=True)
    source_document_model = fields.Char(index=True)
    source_document_res_id = fields.Integer(index=True)
    source_page = fields.Integer()
    source_section = fields.Char()
    source_quote = fields.Text(copy=False, readonly=True)
    source_type = fields.Selection([
        ("explicit_user", "Explicit user statement"),
        ("assistant_extraction", "Assistant extraction"),
        ("document", "Document"), ("system", "System"),
    ], default="explicit_user", required=True)

    observed_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    valid_from = fields.Datetime(index=True)
    valid_to = fields.Datetime(index=True)
    supersedes_id = fields.Many2one("ai.agent.memory.fact", index=True, ondelete="set null")
    contradicted_by_id = fields.Many2one("ai.agent.memory.fact", index=True, ondelete="set null")

    embedding_state = fields.Selection([
        ("pending", "Pending"), ("indexed", "Indexed"), ("failed", "Failed"),
    ], default="pending", required=True, index=True)
    embedding_model_revision = fields.Char(index=True)
    embedding_index_version = fields.Char(default=FACT_INDEX_VERSION, required=True, index=True)
    embedding_error = fields.Char()
    created_at = fields.Datetime(default=fields.Datetime.now, readonly=True, index=True)
    last_recalled_at = fields.Datetime(index=True)
    recall_count = fields.Integer(default=0)
    created_by = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)

    def init(self):
        """Create the optional pgvector column without breaking a partial install."""
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS vector")
                self.env.cr.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'ai_agent_memory_fact' AND column_name = 'embedding'"
                )
                if not self.env.cr.fetchone():
                    self.env.cr.execute(
                        "ALTER TABLE ai_agent_memory_fact ADD COLUMN embedding vector(%s)"
                        % FACT_EMBEDDING_DIM
                    )
                self.env.cr.execute(
                    """
                    CREATE INDEX IF NOT EXISTS ai_agent_memory_fact_embedding_hnsw_idx
                    ON ai_agent_memory_fact USING hnsw (embedding vector_cosine_ops)
                    WHERE embedding IS NOT NULL
                    """
                )
        except Exception:  # pgvector may be installed later by ai_rag deployment.
            _logger.info("structured memory vector column is not available yet", exc_info=True)
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS ai_agent_memory_fact_subject_predicate_idx "
            "ON ai_agent_memory_fact (company_id, scope, subject, predicate, status)"
        )
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS ai_agent_memory_fact_search_tokens_fts_idx "
            "ON ai_agent_memory_fact USING gin "
            "(to_tsvector('simple', coalesce(search_tokens, '')))"
        )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("memory_fact_internal"):
            raise AccessError("structured facts must be created through the audited create_fact path")
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get("memory_fact_internal") and {
            "object_value", "source_quote",
        }.intersection(vals):
            raise AccessError("encrypted fact values cannot be edited directly")
        return super().write(vals)

    @api.model
    def _memory_codec(self):
        return self.env["ai.agent.memory.record"]

    @api.model
    def _department_for(self, user):
        employee = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
        return employee.department_id if employee else self.env["hr.department"]

    @api.model
    def _validate_scope(self, user, scope):
        if scope not in {"personal", "department", "company"}:
            raise ValidationError("Invalid memory scope")
        department = self._department_for(user)
        if scope == "department" and not department:
            raise AccessError("department memory requires an employee department")
        if scope == "company" and not any(user.has_group(group) for group in (
            "hr.group_hr_manager", "ai_business_tools.role_executive",
            "ai_business_tools.role_system_admin",
        )):
            raise AccessError("company memory is restricted to HR/Executive/Admin")
        return department

    @api.model
    def _raw_search_tokens(self, value):
        return self._memory_codec()._search_tokens(value)

    @api.model
    def _visible_domain(self, user, include_history=False):
        department = self._department_for(user)
        privileged_company = any(user.has_group(group) for group in (
            "hr.group_hr_manager", "ai_business_tools.role_executive",
            "ai_business_tools.role_system_admin", "ai_business_tools.role_security",
        ))
        scope_domain = [
            "|",
            "&", ("scope", "=", "personal"), ("user_id", "=", user.id),
            "&", ("scope", "=", "department"), ("department_id", "=", department.id if department else False),
        ]
        if privileged_company:
            scope_domain = ["|", ("scope", "=", "company"), *scope_domain]
        domain = [
            ("company_id", "=", user.company_id.id),
            *scope_domain,
        ]
        if not include_history:
            domain.extend([
                "|", ("valid_to", "=", False), ("valid_to", ">=", fields.Datetime.now()),
            ])
        return domain

    @api.model
    def visible_for(self, user=None, limit=1000, include_history=False):
        user = user or self.env.user
        domain = self._visible_domain(user, include_history=include_history)
        # Candidate and rejected assertions are never recallable, even when
        # a caller asks for history. History means confirmed superseded or
        # expired versions only; promotion happens through explicit save/ORM
        # review, not through the recall tool.
        domain.append((
            "status", "=", "confirmed",
        ) if not include_history else (
            "status", "in", ["confirmed", "superseded", "expired"],
        ))
        try:
            limit = max(1, min(int(limit), 5000))
        except (TypeError, ValueError):
            limit = 1000
        return self.sudo().search(domain, order="valid_from desc, created_at desc, id desc", limit=limit)

    @api.model
    def create_fact(
        self, subject, predicate, object_value, scope="personal", user=None,
        *, confirmed=False, confidence=1.0, importance=0.5,
        source_message_id=None, source_thread_id=None,
        source_document_model=None, source_document_res_id=None,
        source_page=None, source_section=None, source_quote=None,
        source_type="explicit_user", object_type="text", valid_from=None, valid_to=None,
    ):
        user = user or self.env.user
        subject = str(subject or "").strip()
        predicate = str(predicate or "").strip()
        object_value = str(object_value if object_value is not None else "").strip()
        if not subject or len(subject) > 255:
            raise ValidationError("Fact subject must contain 1 to 255 characters")
        if not predicate or len(predicate) > 160:
            raise ValidationError("Fact predicate must contain 1 to 160 characters")
        if not object_value or len(object_value) > 16000:
            raise ValidationError("Fact value must contain 1 to 16000 characters")
        department = self._validate_scope(user, scope)
        try:
            confidence = max(0.0, min(float(confidence), 1.0))
            importance = max(0.0, min(float(importance), 1.0))
        except (TypeError, ValueError) as exc:
            raise ValidationError("confidence and importance must be bounded numbers") from exc
        if object_type not in {"text", "number", "date", "boolean", "entity", "json"}:
            raise ValidationError("Invalid fact object type")
        if source_type not in {"explicit_user", "assistant_extraction", "document", "system"}:
            raise ValidationError("Invalid fact source type")
        source_quote = str(source_quote or "").strip()
        if len(source_quote) > 2000:
            raise ValidationError("source_quote must contain at most 2000 characters")
        if source_type in {"explicit_user", "assistant_extraction"} and not source_quote:
            raise ValidationError("explicit and extracted facts require a source quote")

        source_message = self.env["mail.message"].sudo().browse(int(source_message_id)).exists() if source_message_id else False
        if source_type in {"explicit_user", "assistant_extraction"} and not source_message:
            raise ValidationError("explicit and extracted facts require a source message")
        if source_message_id and not source_message:
            raise ValidationError("source_message_id does not identify a message")
        if source_message and source_type in {"explicit_user", "assistant_extraction"}:
            if source_message.author_id and source_message.author_id != user.partner_id:
                raise AccessError("a memory fact must cite a message authored by the requesting user")
        if source_message and source_quote:
            if _normal(source_quote) not in _normal(_plain_message(source_message.body)):
                raise ValidationError("source_quote must be verbatim text from source_message_id")
        codec = self._memory_codec()
        token_text = "%s %s %s" % (subject, predicate, object_value)

        # Idempotence: identical open facts are returned instead of creating
        # duplicates. History is never overwritten.
        open_facts = self.sudo().search([
            ("company_id", "=", user.company_id.id),
            ("user_id", "=", user.id), ("scope", "=", scope),
            ("subject", "=", subject), ("predicate", "=", predicate),
            ("status", "in", ["candidate", "confirmed"]),
        ], order="id desc", limit=100)
        for existing in open_facts:
            try:
                if _normal(codec._decrypt(existing.object_value)) == _normal(object_value):
                    if confirmed and existing.status == "candidate":
                        prior = open_facts.filtered(
                            lambda rec: rec.status == "confirmed" and rec.id != existing.id
                        )
                        if prior:
                            prior.write({
                                "status": "superseded",
                                "valid_to": valid_from or fields.Datetime.now(),
                            })
                            existing.write({"supersedes_id": prior[0].id})
                        existing.write({
                            "status": "confirmed", "confirmation_required": False,
                            "confidence": confidence,
                        })
                    return existing
            except Exception:
                _logger.warning("unable to decrypt candidate fact %s during dedup", existing.id)

        supersedes = self.env["ai.agent.memory.fact"]
        if confirmed:
            # A user-confirmed new assertion supersedes prior confirmed values
            # for the same subject/predicate/scope while retaining history.
            prior = open_facts.filtered(lambda rec: rec.status == "confirmed")
            if prior:
                supersedes = prior[0]
                prior.write({"status": "superseded", "valid_to": valid_from or fields.Datetime.now()})

        values = {
            "user_id": user.id,
            "company_id": user.company_id.id,
            "department_id": department.id if department else False,
            "scope": scope,
            "classification": self.env.context.get("memory_classification", "internal"),
            "subject": subject,
            "predicate": predicate,
            "object_value": codec._encrypt(object_value),
            "object_type": object_type,
            "search_tokens": codec._search_tokens(token_text),
            "status": "confirmed" if confirmed else "candidate",
            "confirmation_required": not confirmed,
            "confidence": confidence,
            "importance": importance,
            "source_message_id": source_message.id if source_message else False,
            "source_thread_id": int(source_thread_id or 0) or False,
            "source_document_model": source_document_model or False,
            "source_document_res_id": int(source_document_res_id or 0) or False,
            "source_page": source_page,
            "source_section": source_section or False,
            "source_quote": codec._encrypt(source_quote) if source_quote else False,
            "source_type": source_type,
            "observed_at": fields.Datetime.now(),
            "valid_from": valid_from or fields.Datetime.now(),
            "valid_to": valid_to or False,
            "supersedes_id": supersedes.id if supersedes else False,
            "embedding_state": "pending",
        }
        return self.sudo().with_context(memory_fact_internal=True).create(values)

    @api.model
    def confirm_fact(self, fact_id, user=None):
        """Promote one owned candidate after explicit user confirmation."""
        user = user or self.env.user
        try:
            fact_id = int(fact_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError("fact_id must be an integer") from exc
        fact = self.sudo().browse(fact_id).exists()
        if not fact or fact.company_id != user.company_id or fact.user_id != user:
            raise AccessError("memory candidate is not owned by the requesting user")
        if fact.status != "candidate":
            raise ValidationError("only candidate facts can be confirmed")
        prior = self.sudo().search([
            ("company_id", "=", user.company_id.id), ("user_id", "=", user.id),
            ("scope", "=", fact.scope), ("subject", "=", fact.subject),
            ("predicate", "=", fact.predicate), ("status", "=", "confirmed"),
            ("id", "!=", fact.id),
        ])
        if prior:
            prior.write({"status": "superseded", "valid_to": fact.valid_from or fields.Datetime.now()})
            fact.write({"supersedes_id": prior[0].id})
        fact.write({"status": "confirmed", "confirmation_required": False})
        return fact

    def _plain_value(self):
        self.ensure_one()
        return self._memory_codec()._decrypt(self.object_value)

    def _plain_quote(self):
        self.ensure_one()
        return self._memory_codec()._decrypt(self.source_quote) if self.source_quote else ""

    def _embedding_text(self):
        self.ensure_one()
        return "%s: %s = %s" % (self.subject, self.predicate, self._plain_value())

    def write_embedding(self, vector, revision=None):
        self.ensure_one()
        if len(vector) != FACT_EMBEDDING_DIM or any(not math.isfinite(float(item)) for item in vector):
            raise ValidationError("Fact embedding dimension/value mismatch")
        from odoo.addons.ai_rag.models.embedding_client import to_pgvector_literal
        self.env.cr.execute(
            "UPDATE ai_agent_memory_fact SET embedding = %s::vector, embedding_state = 'indexed', embedding_model_revision = %s, embedding_index_version = %s, embedding_error = NULL WHERE id = %s",
            (to_pgvector_literal(vector), revision or FACT_EMBEDDING_REVISION, FACT_INDEX_VERSION, self.id),
        )

    @api.model
    def cron_embed_pending(self, limit=32):
        """Asynchronously embed confirmed facts; never block a chat write."""
        try:
            from odoo.addons.ai_rag.models.embedding_client import embed_texts
        except ImportError:
            return 0
        facts = self.sudo().search([
            ("status", "=", "confirmed"), ("embedding_state", "in", ["pending", "failed"]),
        ], order="importance desc, created_at", limit=max(1, min(int(limit or 32), 100)))
        count = 0
        for fact in facts:
            try:
                vectors = embed_texts([fact._embedding_text()], env=self.env)
                fact.write_embedding(vectors[0], revision=FACT_EMBEDDING_REVISION)
                count += 1
            except Exception as exc:  # noqa: BLE001
                fact.sudo().write({"embedding_state": "failed", "embedding_error": str(exc)[:250]})
        return count

    @api.model
    def search_facts(self, query, user=None, limit=8, include_history=False):
        user = user or self.env.user
        query = str(query or "").strip()[:8000]
        if not query:
            return []
        try:
            limit = max(1, min(int(limit), 50))
        except (TypeError, ValueError):
            limit = 8
        visible = self.visible_for(user, limit=2000, include_history=include_history)
        if not visible:
            return []
        allowed_ids = visible.ids
        vector_rows = []
        try:
            from odoo.addons.ai_rag.models.embedding_client import embed_texts, to_pgvector_literal
            vector = embed_texts([query], env=self.env, is_query=True)[0]
            self.env.cr.execute(
                """
                SELECT id, 1 - (embedding <=> %s::vector) AS vector_score
                FROM ai_agent_memory_fact
                WHERE id = ANY(%s)
                  AND embedding IS NOT NULL
                  AND embedding_state = 'indexed'
                  AND embedding_model_revision = %s
                  AND embedding_index_version = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    to_pgvector_literal(vector), allowed_ids, FACT_EMBEDDING_REVISION,
                    FACT_INDEX_VERSION, to_pgvector_literal(vector), min(60, max(20, int(limit) * 6)),
                ),
            )
            vector_rows = self.env.cr.fetchall()
        except Exception:
            _logger.info("structured memory semantic recall unavailable", exc_info=True)

        query_tokens = set(re.findall(r"[\w]{2,}", query.casefold(), flags=re.UNICODE))
        lexical = []
        codec = self._memory_codec()
        lexical_visible = visible
        try:
            token_hashes = self._raw_search_tokens(query).split()
            if token_hashes:
                self.env.cr.execute(
                    """
                    SELECT id
                    FROM ai_agent_memory_fact
                    WHERE id = ANY(%s)
                      AND to_tsvector('simple', coalesce(search_tokens, ''))
                          @@ to_tsquery('simple', %s)
                    LIMIT 2000
                    """,
                    (allowed_ids, " | ".join(token_hashes)),
                )
                lexical_ids = {row[0] for row in self.env.cr.fetchall()}
                lexical_visible = visible.filtered(lambda fact: fact.id in lexical_ids)
        except Exception:
            # Search-token backfill is intentionally best effort during an
            # upgrade; the bounded visible recordset remains the safe fallback.
            _logger.info("structured memory lexical index unavailable", exc_info=True)
        for fact in lexical_visible:
            try:
                plain = "%s %s %s" % (fact.subject, fact.predicate, codec._decrypt(fact.object_value))
                overlap = len(query_tokens & set(re.findall(r"[\w]{2,}", plain.casefold(), flags=re.UNICODE)))
                if overlap or _normal(query) in _normal(plain):
                    lexical.append((fact.id, overlap))
            except Exception:
                continue
        vector_rank = {row[0]: position for position, row in enumerate(vector_rows, start=1)}
        lexical_rank = {row[0]: position for position, row in enumerate(sorted(lexical, key=lambda row: (-row[1], -row[0])), start=1)}
        ids = set(vector_rank) | set(lexical_rank)
        ranked = sorted(
            ids,
            key=lambda fact_id: (
                -(1 / (60 + vector_rank[fact_id]) if fact_id in vector_rank else 0)
                - (1 / (60 + lexical_rank[fact_id]) if fact_id in lexical_rank else 0),
                -next((fact.valid_from.timestamp() for fact in visible if fact.id == fact_id and fact.valid_from), 0),
            ),
        )[:limit]
        result = []
        # ``visible`` is the explicit authorization boundary. Use sudo only
        # for the already-authorized IDs so Odoo's generic rule composition
        # cannot accidentally drop an executive/company-scope result between
        # the ACL check and the final citation.
        selected = self.sudo().browse(ranked).exists()
        now = fields.Datetime.now()
        for fact in selected:
            value = fact._plain_value()
            quote = fact._plain_quote()
            result.append({
                "subject": fact.subject,
                "predicate": fact.predicate,
                "value": value,
                "object_type": fact.object_type,
                "scope": fact.scope,
                "confidence": round(fact.confidence, 4),
                "status": fact.status,
                "valid_from": fact.valid_from,
                "valid_to": fact.valid_to,
                "source": {
                    "message_id": fact.source_message_id.id if fact.source_message_id else None,
                    "thread_id": fact.source_thread_id,
                    "document_model": fact.source_document_model or "",
                    "document_id": fact.source_document_res_id,
                    "page": fact.source_page,
                    "section": fact.source_section or "",
                    "quote": quote,
                    "type": fact.source_type,
                },
            })
            fact.sudo().write({"last_recalled_at": now, "recall_count": fact.recall_count + 1})
        return result

    @api.model
    def cleanup_expired(self):
        now = fields.Datetime.now()
        return self.sudo().search([("valid_to", "!=", False), ("valid_to", "<", now), ("status", "=", "confirmed")]).write({"status": "expired"})
