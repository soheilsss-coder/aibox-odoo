import logging
import os
import tempfile

from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool

from .document_extractor import extract_file

_logger = logging.getLogger(__name__)

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_EXTRACTED_CHARS = 2_000_000
EMBEDDING_BATCH_SIZE = 64


def chunk_text(text, chunk_size=1000, overlap=150):
    """Use the persistent RAG chunker when the RAG addon is installed.

    The fallback keeps this standalone file tool usable during a partial
    module installation, but the delivered appliance installs ai_rag and
    therefore uses the paragraph/sentence-aware implementation everywhere.
    """
    try:
        from odoo.addons.ai_rag.models.chunking import chunk_text as rag_chunk_text
        return rag_chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    except ImportError:
        try:
            chunk_size = max(128, int(chunk_size))
            overlap = max(0, min(int(overlap), chunk_size // 2))
        except (TypeError, ValueError):
            chunk_size, overlap = 1000, 150
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = end - overlap
        return [c for c in chunks if c.strip()]


class LLMToolFileReader(models.Model):
    _inherit = "llm.tool"

    @llm_tool(read_only_hint=True)
    def read_attached_file(self, question: str = "") -> dict:
        """Read the most recently attached file in this conversation -
        supports PDF (including scanned/image-only PDFs via OCR), Word,
        Excel, PowerPoint, CSV, HTML, TXT, and images (photos of text,
        screenshots) - and return only the parts relevant to the user's
        question. Call this immediately whenever the user attaches a
        file and asks something about it - the file is already
        available, never ask the user to upload it again.

        Parameters:
            question: The user's actual question about the file.
        """
        current_message = self.env.context.get("message")
        if not current_message or current_message.model != "llm.thread":
            return {"error": "Could not determine the current chat thread."}

        thread_id = current_message.res_id
        messages = self.env["mail.message"].search(
            [("model", "=", "llm.thread"), ("res_id", "=", thread_id)],
            order="create_date desc",
        )
        attachments = messages.mapped("attachment_ids")
        if not attachments:
            return {"error": "No attached file found in this conversation."}

        attachment = attachments[0]
        name = attachment.name or "file"
        validate_upload = None
        try:
            from odoo.addons.ai_gateway.controllers.file_policy import (
                MAX_CHAT_UPLOAD_BYTES,
                validate_upload as shared_validate_upload,
            )
            validate_upload = shared_validate_upload
            upload_limit = MAX_CHAT_UPLOAD_BYTES
        except ImportError:
            upload_limit = MAX_ATTACHMENT_BYTES
        declared_size = getattr(attachment, "file_size", 0) or 0
        if declared_size > upload_limit:
            return {"error": "attached file exceeds the safe processing limit"}
        raw = attachment.raw
        if len(raw or b"") > upload_limit:
            return {"error": "attached file exceeds the safe processing limit"}
        try:
            validate_upload(name, raw, max_bytes=upload_limit)
        except (ImportError, TypeError, ValueError):
            return {"error": "unsupported or unsafe attachment"}

        text = ""
        tmp_path = None
        try:
            suffix = os.path.splitext(name)[1] or ".bin"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            result = extract_file(tmp_path, filename=name, max_chars=MAX_EXTRACTED_CHARS)
            text = result.text
        except Exception as exc:  # noqa: BLE001
            _logger.exception("File extraction failed for %s", name)
            return {"error": f"Could not read file {name}"}
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        if len(text) > MAX_EXTRACTED_CHARS:
            return {"error": "extracted file text exceeds the safe processing limit"}
        if not text:
            return {
                "filename": name,
                "content": "(no extractable text found - the file may be empty, corrupted, or unreadable even with OCR)",
            }

        chunks = chunk_text(text)

        if not question or len(chunks) <= 4:
            selected = chunks[:4]
        else:
            # Use the same certified embedding service as the persistent RAG
            # index. A second CPU embedding model here caused a cold-start
            # stall, different rankings from semantic search, and duplicated
            # model memory. If the embedding service is unavailable, fail
            # explicitly instead of returning arbitrary first chunks.
            try:
                from odoo.addons.ai_rag.models.embedding_client import embed_texts
                vectors = []
                for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
                    vectors.extend(embed_texts(
                        chunks[start:start + EMBEDDING_BATCH_SIZE],
                        env=self.env,
                    ))
                question_embedding = embed_texts([question], env=self.env)[0]
                import numpy as np
                chunk_embeddings = np.asarray(vectors, dtype=float)
                question_embedding = np.asarray(question_embedding, dtype=float)
                sims = np.dot(chunk_embeddings, question_embedding) / (
                    np.linalg.norm(chunk_embeddings, axis=1)
                    * np.linalg.norm(question_embedding)
                    + 1e-8
                )
                top_indices = np.argsort(sims)[-4:][::-1]
                selected = [chunks[i] for i in sorted(top_indices)]
            except Exception as exc:  # noqa: BLE001
                _logger.warning("File relevance embedding failed: %s", exc)
                return {"error": "file relevance search is temporarily unavailable; try again shortly"}

        content = "\n\n---\n\n".join(selected)
        result = {"filename": name, "relevant_excerpts": content}
        # Context Firewall (roadmap #28): an uploaded document (a
        # screenshot, an exported config, a scanned form) can easily
        # contain a password or API key that has nothing to do with
        # the user's actual question - scrub before it reaches the
        # model's context, not just before it reaches the user.
        if hasattr(self, "_context_firewall"):
            result = self._context_firewall(result)
        return result
