import base64
import hashlib
import logging
import mimetypes
import os
import tempfile

from odoo import api, fields, models

from .chunking import chunk_text
from .embedding_client import embed_texts

_logger = logging.getLogger(__name__)
RAG_INDEX_VERSION = os.getenv("AI_RAG_INDEX_VERSION", "rag-v1")


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

    def _compute_chunk_count(self):
        for doc in self:
            doc.chunk_count = self.env["ai.document.chunk"].search_count(
                [("document_id", "=", doc.id)]
            )

    def _rag_extract_text(self):
        """Reuses the SAME extraction backends as read_attached_file
        (unstructured + OCR fallback) instead of a second parser, so a
        document reads identically whether a tool opens it ad hoc or
        the RAG index chunks it ahead of time."""
        self.ensure_one()
        if not self.file:
            return ""

        from odoo.addons.company_ai_demo.models.file_reader import (
            ocr_image_file,
            ocr_scanned_pdf,
        )

        raw = base64.b64decode(self.file)
        name = self.file_name or self.name or "file"
        suffix = os.path.splitext(name)[1] or ".bin"
        mimetype = mimetypes.guess_type(name)[0] or ""

        text = ""
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name

            if mimetype.startswith("image/"):
                text = ocr_image_file(tmp_path)
            else:
                from unstructured.partition.auto import partition

                elements = partition(filename=tmp_path)
                text = "\n".join(str(el) for el in elements)
                if suffix.lower() == ".pdf" and len(text.strip()) < 30:
                    text = ocr_scanned_pdf(tmp_path)
        except Exception:  # noqa: BLE001
            _logger.exception("RAG text extraction failed for document %s", self.id)
            text = ""
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        return text

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
        """Re-chunk + re-embed this document. Skips embedding any
        chunk whose content is byte-identical to one already indexed
        (by content_hash) - so editing one paragraph of a large
        document doesn't re-embed the whole thing, and re-running this
        on an unchanged document costs one text extraction + zero
        embedding calls."""
        self.ensure_one()
        Chunk = self.env["ai.document.chunk"].sudo()
        self._rag_update_snapshot("document reindex started")

        # Context Firewall (roadmap #28) applies to indexing too, not
        # just to what a tool returns: a company document can contain
        # a password/API key just as easily as a chat attachment can -
        # scrub BEFORE the text is embedded and stored, not only
        # before a search result is handed back to the model. Reuses
        # the exact same scrub_value() the rest of the project uses
        # (recall_memory, read_attached_file, the audit log writer) -
        # one denylist/regex set, not a second copy to keep in sync.
        from odoo.addons.ai_business_tools.models.context_firewall import scrub_value

        raw_text = ((self.description or "") + "\n\n" + self._rag_extract_text()).strip()
        text = scrub_value(raw_text) if raw_text else ""

        existing = Chunk.search([("document_id", "=", self.id)])
        if not text:
            existing.unlink()
            self.write({
                "rag_indexed_date": fields.Datetime.now(),
                "rag_index_version": RAG_INDEX_VERSION,
            })
            self._rag_update_snapshot()
            return

        pieces = chunk_text(text)
        existing_by_hash = {c.content_hash: c for c in existing}
        wanted_hashes = [hashlib.md5(p.encode("utf-8")).hexdigest() for p in pieces]

        to_embed_texts, to_embed_positions = [], []
        for i, h in enumerate(wanted_hashes):
            current = existing_by_hash.get(h)
            if current is None or current.index_version != RAG_INDEX_VERSION:
                to_embed_texts.append(pieces[i])
                to_embed_positions.append(i)

        vectors = embed_texts(to_embed_texts, env=self.env) if to_embed_texts else []
        vector_by_position = dict(zip(to_embed_positions, vectors))

        keep_hashes = set()
        for i, piece in enumerate(pieces):
            h = wanted_hashes[i]
            keep_hashes.add(h)
            current = existing_by_hash.get(h)
            if current:
                current.sequence = i
                current.index_version = RAG_INDEX_VERSION
                if i in vector_by_position:
                    current.write_embedding(vector_by_position[i])
                continue
            chunk = Chunk.create(
                {
                    "document_id": self.id,
                    "sequence": i,
                    "content": piece,
                    "content_hash": h,
                    "index_version": RAG_INDEX_VERSION,
                }
            )
            chunk.write_embedding(vector_by_position[i])

        stale = existing.filtered(lambda c: c.content_hash not in keep_hashes)
        stale.unlink()
        self.write({
            "rag_indexed_date": fields.Datetime.now(),
            "rag_index_version": RAG_INDEX_VERSION,
        })
        self._rag_update_snapshot()

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
