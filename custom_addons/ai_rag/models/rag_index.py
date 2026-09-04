import base64
import hashlib
import logging
import os
import tempfile

from odoo import api, fields, models
from odoo.exceptions import UserError

from .chunking import chunk_blocks, normalize_search_text
from .embedding_client import embed_texts

_logger = logging.getLogger(__name__)
RAG_INDEX_VERSION = os.getenv("AI_RAG_INDEX_VERSION", "rag-v1")
EMBEDDING_BATCH_SIZE = 64


class AiRagIndexSnapshot(models.Model):
    _name = "ai.rag.index.snapshot"
    _description = "RAG Index Revision Snapshot"
    _order = "created_at desc, id desc"

    version = fields.Char(required=True, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True, ondelete="restrict",
        default=lambda self: self.env.company,
    )
    status = fields.Selection([
        ("building", "Building"), ("active", "Active"), ("failed", "Failed"),
    ], default="building", required=True, index=True)
    embedding_dimension = fields.Integer(required=True, default=1024)
    document_count = fields.Integer(default=0)
    chunk_count = fields.Integer(default=0)
    content_checksum = fields.Char(index=True)
    created_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    activated_at = fields.Datetime(readonly=True)
    note = fields.Text()

    _sql_constraints = [
        ("version_company_unique", "unique(version, company_id)", "RAG index version already exists for this company."),
    ]


class CompanyDocumentRag(models.Model):
    """Extends company.document (defined in ai_business_tools) with the
    indexing side of RAG (roadmap #27). No new UI is added here on
    purpose (see roadmap #16's own reasoning for company-wide docs:
    don't build a screen nobody asked for yet) - indexing is fully
    automatic on create/write, with a catch-up cron for anything that
    slips through (imports, sudo() writes, a module upgrade that
    changes chunking and needs a full re-embed)."""

    _inherit = "company.document"

    chunk_count = fields.Integer(compute="_compute_chunk_count")
    rag_indexed_date = fields.Datetime(readonly=True)
    rag_index_version = fields.Char(readonly=True)
    rag_ingestion_state = fields.Selection([
        ("pending", "Pending"), ("extracting", "Extracting"),
        ("embedding", "Embedding"), ("indexed", "Indexed"),
        ("empty", "Empty"), ("failed", "Failed"),
    ], default="pending", index=True, readonly=True)
    rag_ingestion_error = fields.Text(readonly=True)
    rag_ingestion_warnings = fields.Text(readonly=True)
    rag_ingestion_parser = fields.Char(readonly=True)
    rag_ingestion_parser_version = fields.Char(readonly=True)
    rag_ingestion_page_count = fields.Integer(readonly=True)
    rag_ingestion_char_count = fields.Integer(readonly=True)
    rag_ingestion_checksum = fields.Char(index=True, readonly=True)
    rag_ingestion_started_at = fields.Datetime(readonly=True)
    rag_ingestion_finished_at = fields.Datetime(readonly=True)

    def _compute_chunk_count(self):
        for doc in self:
            doc.chunk_count = self.env["ai.document.chunk"].search_count(
                [("document_id", "=", doc.id)]
            )

    def _rag_extract_payload(self):
        """Validate and extract the document into bounded canonical blocks."""
        self.ensure_one()
        if not self.file:
            return None

        from odoo.addons.ai_gateway.controllers.file_policy import validate_upload
        from odoo.addons.company_ai_demo.models.document_extractor import (
            ExtractionError,
            extract_file,
        )
        from odoo.addons.company_ai_demo.models.file_reader import (
            MAX_ATTACHMENT_BYTES,
            MAX_EXTRACTED_CHARS,
        )

        try:
            raw = base64.b64decode(self.file, validate=True)
        except (TypeError, ValueError) as exc:
            raise UserError("document payload is not valid base64") from exc
        if len(raw) > MAX_ATTACHMENT_BYTES:
            raise UserError("document exceeds the safe indexing size limit")
        name = self.file_name or self.name or "file"
        try:
            validate_upload(name, raw, max_bytes=MAX_ATTACHMENT_BYTES)
        except (TypeError, ValueError) as exc:
            raise UserError("document type or signature is not allowed") from exc

        suffix = os.path.splitext(name)[1] or ".bin"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            result = extract_file(tmp_path, filename=name, max_chars=MAX_EXTRACTED_CHARS)
            result.checksum = hashlib.sha256(raw).hexdigest()
            return result
        except ExtractionError as exc:
            _logger.exception("RAG text extraction failed for document %s", self.id)
            raise UserError(exc.message) from exc
        except Exception as exc:  # noqa: BLE001
            _logger.exception("RAG text extraction failed for document %s", self.id)
            raise UserError("document extraction is temporarily unavailable") from exc
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _rag_extract_text(self):
        """Compatibility helper returning only canonical extracted text."""
        payload = self._rag_extract_payload()
        return payload.text if payload else ""

    def _rag_update_snapshot(self, status_note=None):
        """Record revision completeness and a deterministic integrity digest.

        A revision is only marked active after every file-bearing document has
        the current index version. Older active revisions remain retained so a
        deployment can point routing back to a known-good revision during a
        rollback; no model response cache is used for this decision.
        """
        Snapshot = self.env["ai.rag.index.snapshot"].sudo()
        company_id = self.env.company.id
        snapshot = Snapshot.search([
            ("version", "=", RAG_INDEX_VERSION), ("company_id", "=", company_id),
        ], limit=1)
        if not snapshot:
            snapshot = Snapshot.create({
                "version": RAG_INDEX_VERSION,
                "company_id": company_id,
                "embedding_dimension": 1024,
                "status": "building",
            })
        Chunk = self.env["ai.document.chunk"].sudo()
        Document = self.env["company.document"].sudo()
        all_docs = Document.search([
            ("company_id", "=", company_id), ("file", "!=", False),
        ])
        indexed_docs = all_docs.filtered(lambda doc: doc.rag_index_version == RAG_INDEX_VERSION)
        chunks = Chunk.search([
            ("index_version", "=", RAG_INDEX_VERSION),
            ("document_id", "in", all_docs.ids or [0]),
        ])
        pending = len(all_docs) != len(indexed_docs)
        digest_material = ",".join(sorted(chunks.mapped("content_hash")))
        values = {
            "status": "building" if pending else "active",
            "document_count": len(indexed_docs),
            "chunk_count": len(chunks),
            "content_checksum": hashlib.sha256(digest_material.encode("utf-8")).hexdigest(),
            "note": status_note or ("revision is complete" if not pending else "revision rebuild is in progress"),
        }
        if not pending:
            values["activated_at"] = fields.Datetime.now()
        snapshot.write(values)
        return snapshot

    def action_reindex(self):
        for doc in self:
            doc._rag_reindex()

    def _rag_reindex(self):
        """Extract, chunk and embed one document with durable status.

        Extraction and embedding are intentionally outside the document write
        transaction (the index job calls this method).  Every failure is made
        visible on the document and leaves the previous chunks untouched until
        the new revision has enough data to replace them safely.
        """
        self.ensure_one()
        Chunk = self.env["ai.document.chunk"].sudo()
        now = fields.Datetime.now()
        self.write({
            "rag_ingestion_state": "extracting",
            "rag_ingestion_error": False,
            "rag_ingestion_started_at": now,
            "rag_ingestion_finished_at": False,
        })
        try:
            self._rag_update_snapshot("document reindex started")
            payload = self._rag_extract_payload()

            # Context Firewall applies before text is embedded and stored.
            from odoo.addons.ai_business_tools.models.context_firewall import scrub_value
            from odoo.addons.company_ai_demo.models.file_reader import MAX_EXTRACTED_CHARS

            blocks = [dict(block) for block in (payload.blocks if payload else [])]
            if self.description:
                blocks.insert(0, {"text": self.description, "content_type": "description"})
            blocks = [
                {**block, "text": scrub_value(block.get("text", ""))}
                for block in blocks if block.get("text")
            ]
            raw_text = "\n\n".join(block["text"] for block in blocks).strip()
            if len(raw_text) > MAX_EXTRACTED_CHARS:
                raise UserError("combined document text exceeds the safe indexing limit")

            parser = payload.parser if payload else "description"
            parser_version = payload.parser_version if payload else "builtin"
            page_count = payload.page_count if payload else 0
            checksum = payload.checksum if payload else hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            self.write({
                "rag_ingestion_parser": parser,
                "rag_ingestion_parser_version": parser_version,
                "rag_ingestion_warnings": "\n".join(payload.warnings if payload else []),
                "rag_ingestion_page_count": page_count,
                "rag_ingestion_char_count": len(raw_text),
                "rag_ingestion_checksum": checksum,
            })

            existing = Chunk.search([("document_id", "=", self.id)])
            if not raw_text:
                existing.unlink()
                self.write({
                    "rag_indexed_date": fields.Datetime.now(),
                    "rag_index_version": RAG_INDEX_VERSION,
                    "rag_ingestion_state": "empty",
                    "rag_ingestion_finished_at": fields.Datetime.now(),
                })
                self._rag_update_snapshot("document contains no extractable text")
                return

            pieces = chunk_blocks(blocks)
            self.write({"rag_ingestion_state": "embedding"})
            existing_by_hash = {c.content_hash: c for c in existing}
            wanted_hashes = [hashlib.md5(piece["text"].encode("utf-8")).hexdigest() for piece in pieces]

            to_embed_texts, to_embed_positions = [], []
            for i, content_hash in enumerate(wanted_hashes):
                current = existing_by_hash.get(content_hash)
                if current is None or current.index_version != RAG_INDEX_VERSION:
                    to_embed_texts.append(pieces[i]["text"])
                    to_embed_positions.append(i)

            vectors = []
            for start in range(0, len(to_embed_texts), EMBEDDING_BATCH_SIZE):
                vectors.extend(embed_texts(
                    to_embed_texts[start:start + EMBEDDING_BATCH_SIZE],
                    env=self.env,
                ))
            vector_by_position = dict(zip(to_embed_positions, vectors))

            keep_hashes = set()
            for i, piece in enumerate(pieces):
                content_hash = wanted_hashes[i]
                keep_hashes.add(content_hash)
                metadata = {
                    "source_page": piece.get("page"),
                    "source_section": piece.get("section"),
                    "source_type": piece.get("content_type"),
                    "source_coordinates": piece.get("coordinates"),
                    "source_table": piece.get("table"),
                    "source_sheet": piece.get("sheet"),
                    "source_slide": piece.get("slide"),
                    "parser_name": parser,
                    "parser_version": parser_version,
                }
                current = existing_by_hash.get(content_hash)
                if current:
                    current.write({
                        "sequence": i,
                        "normalized_content": normalize_search_text(piece["text"]),
                        "index_version": RAG_INDEX_VERSION,
                        **metadata,
                    })
                    if i in vector_by_position:
                        current.write_embedding(vector_by_position[i])
                    continue
                chunk = Chunk.create({
                    "document_id": self.id,
                    "sequence": i,
                    "content": piece["text"],
                    "normalized_content": normalize_search_text(piece["text"]),
                    "content_hash": content_hash,
                    "index_version": RAG_INDEX_VERSION,
                    **metadata,
                })
                chunk.write_embedding(vector_by_position[i])

            stale = existing.filtered(lambda c: c.content_hash not in keep_hashes)
            stale.unlink()
            finished = fields.Datetime.now()
            self.write({
                "rag_indexed_date": finished,
                "rag_index_version": RAG_INDEX_VERSION,
                "rag_ingestion_state": "indexed",
                "rag_ingestion_finished_at": finished,
                "rag_ingestion_error": False,
            })
            self._rag_update_snapshot()
        except Exception as exc:  # noqa: BLE001
            self.write({
                "rag_ingestion_state": "failed",
                "rag_ingestion_error": str(exc)[:2000],
                "rag_ingestion_finished_at": fields.Datetime.now(),
            })
            raise

    @api.model_create_multi
    def create(self, vals_list):
        docs = super().create(vals_list)
        Event = self.env["ai.control.event"] if "ai.control.event" in self.env else None
        if Event:
            for doc in docs.filtered(lambda d: d.file):
                Event.sudo().publish(
                    event_type="document.created",
                    aggregate=doc,
                    payload={"document_id": doc.id, "operation": "create"},
                    user=self.env.user,
                )
        return docs

    def write(self, vals):
        res = super().write(vals)
        if "file" in vals or "description" in vals:
            Event = self.env["ai.control.event"] if "ai.control.event" in self.env else None
            if Event:
                for doc in self.filtered(lambda d: d.file):
                    Event.sudo().publish(
                        event_type="document.updated",
                        aggregate=doc,
                        payload={"document_id": doc.id, "operation": "update"},
                        user=self.env.user,
                    )
        return res

    def cron_reindex_stale_documents(self):
        """Catch-up cron (roadmap #27) for anything the create/write
        hooks above missed. Cheap to run regularly since _rag_reindex
        hashes and skips unchanged chunks - this is NOT a full re-embed
        of everything every time, only actually-changed content costs
        an embedding call."""
        docs = self.env["company.document"].sudo().search([
            ("company_id", "=", self.env.company.id), ("file", "!=", False),
            "|", ("rag_indexed_date", "=", False),
            ("rag_index_version", "!=", RAG_INDEX_VERSION),
        ])
        for doc in docs:
            if "ai.document.index.job" in self.env:
                self.env["ai.document.index.job"].enqueue(doc)
