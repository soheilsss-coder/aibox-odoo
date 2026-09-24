import logging
import re
import tempfile
import os
import mimetypes

from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool

_logger = logging.getLogger(__name__)

_embedder = None
_ocr_engine = None


def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    return _embedder


def get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    return _ocr_engine


def ocr_image_file(image_path):
    try:
        engine = get_ocr()
        result, _ = engine(image_path)
        if not result:
            return ""
        return "\n".join([line[1] for line in result])
    except Exception as exc:  # noqa: BLE001
        _logger.warning("RapidOCR failed on %s: %s", image_path, exc)
        return ""


def ocr_scanned_pdf(pdf_path):
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        texts = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                pix.save(tmp_img.name)
                page_text = ocr_image_file(tmp_img.name)
                os.unlink(tmp_img.name)
            if page_text:
                texts.append(page_text)
        return "\n\n".join(texts)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Scanned-PDF OCR failed on %s: %s", pdf_path, exc)
        return ""


def chunk_text(text, chunk_size=800, overlap=100):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
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
        raw = attachment.raw
        mimetype = attachment.mimetype or mimetypes.guess_type(name)[0] or ""

        text = ""
        try:
            suffix = os.path.splitext(name)[1] or ".bin"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name

            try:
                if mimetype.startswith("image/"):
                    text = ocr_image_file(tmp_path)

                elif suffix.lower() == ".pdf":
                    from unstructured.partition.auto import partition
                    elements = partition(filename=tmp_path)
                    text = "\n".join(str(el) for el in elements)
                    if len(text.strip()) < 30:
                        _logger.info("PDF looks scanned, falling back to OCR: %s", name)
                        text = ocr_scanned_pdf(tmp_path)

                else:
                    from unstructured.partition.auto import partition
                    elements = partition(filename=tmp_path)
                    text = "\n".join(str(el) for el in elements)

            finally:
                os.unlink(tmp_path)

        except Exception as exc:  # noqa: BLE001
            _logger.exception("File extraction failed for %s", name)
            return {"error": f"Could not read file {name}"}

        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text:
            return {
                "filename": name,
                "content": "(no extractable text found - the file may be empty, corrupted, or unreadable even with OCR)",
            }

        chunks = chunk_text(text)

        if not question or len(chunks) <= 4:
            selected = chunks[:4]
        else:
            embedder = get_embedder()
            chunk_embeddings = embedder.encode(chunks)
            question_embedding = embedder.encode([question])[0]

            import numpy as np
            sims = np.dot(chunk_embeddings, question_embedding) / (
                np.linalg.norm(chunk_embeddings, axis=1)
                * np.linalg.norm(question_embedding)
                + 1e-8
            )
            top_indices = np.argsort(sims)[-4:][::-1]
            selected = [chunks[i] for i in sorted(top_indices)]

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
