"""Pure tests for the bounded, local RAG ingestion contract."""
from __future__ import annotations

import base64
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class RagIngestionContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_module(
            "rag_policy_contract",
            ROOT / "custom_addons/ai_gateway/controllers/file_policy.py",
        )
        cls.extractor = load_module(
            "rag_extractor_contract",
            ROOT / "custom_addons/company_ai_demo/models/document_extractor.py",
        )
        cls.chunking = load_module(
            "rag_chunking_contract",
            ROOT / "custom_addons/ai_rag/models/chunking.py",
        )

    def test_policy_accepts_tier_a_and_rejects_mismatches(self):
        self.assertIn(".html", self.policy.ALLOWED_EXTENSIONS)
        self.assertIn(".tiff", self.policy.ALLOWED_EXTENSIONS)
        self.assertEqual(
            self.policy.validate_upload("report.json", b'{"policy": "ok"}')['extension'],
            ".json",
        )
        with self.assertRaises(ValueError):
            self.policy.validate_upload("report.json", b"not-json")
        with self.assertRaises(ValueError):
            self.policy.validate_upload("report.tiff", b"not-an-image")
        with self.assertRaises(ValueError):
            self.policy.validate_upload("report.docm", b"PK")

    def test_json_and_html_are_deterministic_and_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_path = root / "data.json"
            json_path.write_text('{"employee": {"name": "سارا"}, "items": [1, 2]}', encoding="utf-8")
            result = self.extractor.extract_file(json_path, max_chars=1000)
            self.assertIn("$.employee.name: سارا", result.text)
            self.assertIn("$.items[0]: 1", result.text)

            html_path = root / "page.html"
            html_path.write_text("<h1>Policy</h1><script>secret()</script><p>Visible text</p>", encoding="utf-8")
            result = self.extractor.extract_file(html_path, max_chars=1000)
            self.assertIn("Policy", result.text)
            self.assertIn("Visible text", result.text)
            self.assertNotIn("secret", result.text)

    def test_chunk_blocks_preserve_source_metadata_and_normalize_search(self):
        blocks = self.chunking.chunk_blocks([
            {"text": "بخش اول", "page": 2, "content_type": "Title"},
            {"text": "متن اول", "page": 2, "content_type": "Paragraph"},
            {"text": "بخش دوم", "page": 3, "content_type": "Title"},
        ], chunk_size=128)
        # Page is retained, but differing parser block types are kept in
        # separate citations so a title is never cited as paragraph text.
        self.assertEqual([block["page"] for block in blocks], [2, 2, 3])
        self.assertEqual([block["content_type"] for block in blocks], ["Title", "Paragraph", "Title"])
        self.assertIn("بخش اول", blocks[0]["text"])
        provenance = self.chunking.chunk_blocks([{
            "text": "جدول فروش",
            "page": 4,
            "table": "table-1",
            "sheet": "فروش",
            "slide": 2,
        }])
        self.assertEqual(provenance[0]["table"], "table-1")
        self.assertEqual(provenance[0]["sheet"], "فروش")
        self.assertEqual(provenance[0]["slide"], 2)
        self.assertEqual(self.chunking.normalize_search_text("ي ك ۱۲۳\u200cالف"), "ی ک 123 الف")

    def test_retrieval_contract_keeps_acl_and_citation_bounds(self):
        source = (ROOT / "custom_addons/ai_rag/models/document_chunk.py").read_text()
        for marker in (
            "allowed_doc_ids",
            "source_coordinates",
            "source_table",
            "source_sheet",
            "source_slide",
            "CREATE EXTENSION IF NOT EXISTS pg_trgm",
            "normalized_content %% %s",
        ):
            self.assertIn(marker, source)

    def test_safe_upload_round_trip_is_bounded(self):
        raw = b"hello"
        encoded = base64.b64encode(raw)
        self.assertEqual(len(encoded), 8)
        self.assertEqual(self.policy.validate_upload("hello.txt", raw)["size"], 5)


if __name__ == "__main__":
    unittest.main()
