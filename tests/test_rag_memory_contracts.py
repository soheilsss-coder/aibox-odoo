"""Pure unit tests for the dependency-light RAG and memory boundaries."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class RagMemoryContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ranking = load("ranking_contract", ROOT / "custom_addons/ai_rag/models/ranking.py")
        # The extractor only needs UserError at import time. Keep this unit
        # test runnable on a developer machine without installing Odoo.
        try:
            import odoo.exceptions  # noqa: F401
        except ModuleNotFoundError:
            odoo = types.ModuleType("odoo")
            exceptions = types.ModuleType("odoo.exceptions")
            exceptions.UserError = type("UserError", (Exception,), {})
            odoo.exceptions = exceptions
            sys.modules["odoo"] = odoo
            sys.modules["odoo.exceptions"] = exceptions
        try:
            import requests  # noqa: F401
        except ModuleNotFoundError:
            requests = types.ModuleType("requests")
            requests.RequestException = type("RequestException", (Exception,), {})
            requests.post = None
            sys.modules["requests"] = requests
        cls.extractor = load(
            "memory_extractor_contract",
            ROOT / "custom_addons/company_ai_demo/models/memory_fact_extractor.py",
        )

    def test_rrf_merges_rankings_without_mixing_raw_score_scales(self):
        rows = self.ranking.reciprocal_rank_fusion([
            [
                {"chunk_id": 2, "content": "semantic", "vector_score": 0.92},
                {"chunk_id": 1, "content": "lexical", "vector_score": 0.91},
            ],
            [
                {"chunk_id": 1, "content": "lexical", "lexical_score": 1.0},
                {"chunk_id": 2, "content": "semantic", "lexical_score": 0.01},
            ],
            [],
        ])
        self.assertEqual([row["chunk_id"] for row in rows], [1, 2])
        self.assertEqual(rows[0]["retrieval_ranks"], {"vector": 2, "lexical": 1})
        self.assertAlmostEqual(rows[0]["hybrid_score"], rows[0]["rrf_score"])
        self.assertEqual(rows[0]["content"], "lexical")

    def test_memory_extractor_strips_html_and_rejects_paraphrased_quotes(self):
        source = "<p>من ترجیح می‌دهم گزارش به زبان فارسی باشد.</p>"
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": '{"facts": [{"subject": "user", "predicate": "language", "value": "فارسی", "confidence": 0.95, "source_quote": "من ترجیح می‌دهم گزارش به زبان فارسی باشد."}]}'}}]
        }
        with patch.object(self.extractor.requests, "post", return_value=response):
            facts = self.extractor.extract_candidates(source)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["source_quote"], "من ترجیح می‌دهم گزارش به زبان فارسی باشد.")

        response.json.return_value = {
            "choices": [{"message": {"content": '{"facts": [{"subject": "user", "predicate": "language", "value": "فارسی", "confidence": 0.95, "source_quote": "کاربر زبان فارسی را ترجیح می‌دهد"}]}'}}]
        }
        with patch.object(self.extractor.requests, "post", return_value=response):
            self.assertEqual(self.extractor.extract_candidates(source), [])

    def test_low_confidence_and_empty_messages_do_not_create_candidates(self):
        self.assertEqual(self.extractor.extract_candidates("کوتاه"), [])
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": '{"facts": [{"subject": "user", "predicate": "x", "value": "y", "confidence": 0.69, "source_quote": "یک پیام صریح برای آزمون"}]}'}}]
        }
        with patch.object(self.extractor.requests, "post", return_value=response):
            self.assertEqual(self.extractor.extract_candidates("یک پیام صریح برای آزمون"), [])


if __name__ == "__main__":
    unittest.main()
