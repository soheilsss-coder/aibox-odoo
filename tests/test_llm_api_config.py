"""Contract tests for the provider-agnostic LLM API configuration.

These run without Odoo, without a database and without network access, which
is exactly the point: the detection/normalization layer is what decides which
credentials travel to which host, so it has to be checkable on a laptop.

Run:  python3 tests/test_llm_api_config.py     (or pytest tests/)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))

from runtime_workers.llm_api_config import (  # noqa: E402
    PROVIDERS,
    LlmApiConfig,
    detect_provider,
    load_config,
    normalize_base_url,
)


class DetectProviderTests(unittest.TestCase):
    def test_hostname_wins_over_model_name(self):
        # A Groq-hosted Llama model must resolve to Groq, not to "openrouter"
        # or to the generic fallback - the host decides where the key goes.
        pid, reason = detect_provider("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile")
        self.assertEqual(pid, "groq")
        self.assertIn("hostname", reason)

    def test_explicit_override_beats_everything(self):
        pid, reason = detect_provider("https://api.groq.com/openai/v1", "gpt-4o", "openrouter")
        self.assertEqual(pid, "openrouter")
        self.assertIn("explicit", reason)

    def test_unknown_explicit_falls_back_safely(self):
        pid, reason = detect_provider("", "", "made-up-vendor")
        self.assertEqual(pid, "openai-compatible")
        self.assertIn("unknown AI_LLM_PROVIDER", reason)

    def test_known_hosts(self):
        cases = {
            "https://api.openai.com/v1": "openai",
            "https://generativelanguage.googleapis.com/v1beta": "gemini",
            "https://openrouter.ai/api/v1": "openrouter",
            "https://api.anthropic.com": "anthropic",
            "https://api.deepseek.com/v1": "deepseek",
            "https://api.x.ai/v1": "xai",
            "https://api.mistral.ai/v1": "mistral",
            "https://api.deepinfra.com/v1/openai": "deepinfra",
            "https://api.together.xyz/v1": "together",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(detect_provider(url)[0], expected)

    def test_loopback_is_openai_compatible(self):
        # The self-hosted vLLM path and any local test double.
        for url in ("http://127.0.0.1:8000/v1", "http://localhost:11434/v1"):
            with self.subTest(url=url):
                pid, reason = detect_provider(url)
                self.assertEqual(pid, "openai-compatible")
                self.assertIn("loopback", reason)

    def test_model_name_fingerprint_used_when_host_unknown(self):
        self.assertEqual(detect_provider("https://my-proxy.internal/llm", "gpt-4o")[0], "openai")
        self.assertEqual(detect_provider("https://my-proxy.internal/llm", "claude-3-5-haiku")[0], "anthropic")
        self.assertEqual(detect_provider("https://my-proxy.internal/llm", "gemini-2.5-flash")[0], "gemini")
        self.assertEqual(
            detect_provider("https://my-proxy.internal/llm", "anthropic/claude-3.5-haiku")[0],
            "openrouter",
        )

    def test_nothing_supplied_is_openai_compatible(self):
        self.assertEqual(detect_provider("")[0], "openai-compatible")

    def test_hostname_is_case_insensitive_and_port_tolerant(self):
        self.assertEqual(detect_provider("https://API.OpenAI.COM:443/v1")[0], "openai")


class NormalizeBaseUrlTests(unittest.TestCase):
    def test_trailing_endpoint_paths_are_stripped(self):
        for url in (
            "https://api.openai.com/v1/chat/completions",
            "https://api.openai.com/v1/completions",
            "https://api.openai.com/v1/embeddings",
            "https://api.openai.com/v1/models",
        ):
            with self.subTest(url=url):
                base, warnings = normalize_base_url(url, "openai")
                self.assertEqual(base, "https://api.openai.com/v1")
                self.assertTrue(warnings)

    def test_missing_version_path_is_added(self):
        base, warnings = normalize_base_url("https://api.openai.com", "openai")
        self.assertEqual(base, "https://api.openai.com/v1")
        self.assertTrue(any("version path" in w for w in warnings))

    def test_missing_scheme_is_assumed_https(self):
        base, warnings = normalize_base_url("api.openai.com/v1", "openai")
        self.assertEqual(base, "https://api.openai.com/v1")
        self.assertTrue(any("scheme" in w for w in warnings))

    def test_gemini_is_rewritten_to_its_openai_surface(self):
        # The native /v1beta root 404s on /chat/completions; this is the single
        # most common Gemini misconfiguration.
        for url in (
            "https://generativelanguage.googleapis.com/v1beta",
            "https://generativelanguage.googleapis.com/v1beta/models",
            "https://generativelanguage.googleapis.com",
        ):
            with self.subTest(url=url):
                base, _ = normalize_base_url(url, "gemini")
                self.assertEqual(base, "https://generativelanguage.googleapis.com/v1beta/openai")

    def test_anthropic_native_base_keeps_no_version_suffix(self):
        base, _ = normalize_base_url("https://api.anthropic.com", "anthropic")
        self.assertEqual(base, "https://api.anthropic.com")

    def test_local_base_is_untouched(self):
        base, warnings = normalize_base_url("http://127.0.0.1:8000/v1", "openai-compatible")
        self.assertEqual(base, "http://127.0.0.1:8000/v1")
        self.assertEqual(warnings, [])

    def test_trailing_slash(self):
        base, _ = normalize_base_url("https://api.groq.com/openai/v1/", "groq")
        self.assertEqual(base, "https://api.groq.com/openai/v1")

    def test_empty(self):
        self.assertEqual(normalize_base_url("", "openai"), ("", []))


class LoadConfigTests(unittest.TestCase):
    def test_no_environment_yields_unconfigured_chat_and_legacy_embedding(self):
        cfg = load_config(env={})
        self.assertIsInstance(cfg, LlmApiConfig)
        self.assertFalse(cfg.ready)
        self.assertEqual(cfg.chat.api_base, "")
        self.assertTrue(any("AI_LLM_API_BASE is empty" in n for n in cfg.notes))
        # RAG must keep working on the legacy local embedder rather than
        # silently embedding against an empty URL.
        self.assertEqual(cfg.embedding.api_base, "http://127.0.0.1:8002/v1")

    def test_openai_from_environment(self):
        cfg = load_config(env={
            "AI_LLM_API_BASE": "https://api.openai.com",
            "AI_LLM_API_KEY": "sk-test-1234567890",
        })
        self.assertTrue(cfg.ready)
        self.assertEqual(cfg.chat.provider, "openai")
        self.assertEqual(cfg.chat.api_base, "https://api.openai.com/v1")
        self.assertEqual(cfg.chat.model, "gpt-4.1-mini")
        self.assertTrue(cfg.chat.has_key)
        self.assertTrue(cfg.chat.service, "openai")

    def test_key_can_come_from_the_vendor_variable(self):
        cfg = load_config(env={
            "AI_LLM_API_BASE": "https://api.groq.com/openai/v1",
            "GROQ_API_KEY": "gsk_test",
        })
        self.assertTrue(cfg.chat.has_key)
        self.assertEqual(cfg.chat.provider, "groq")

    def test_missing_key_is_reported_not_raised(self):
        cfg = load_config(env={"AI_LLM_API_BASE": "https://api.openai.com/v1"})
        self.assertFalse(cfg.chat.has_key)
        self.assertTrue(any("no API key" in w for w in cfg.chat.warnings))

    def test_chat_vendor_without_embeddings_warns(self):
        cfg = load_config(env={
            "AI_LLM_API_BASE": "https://api.groq.com/openai/v1",
            "AI_LLM_API_KEY": "gsk_test",
        })
        self.assertFalse(PROVIDERS["groq"]["supports_embeddings"])
        self.assertTrue(any("does not serve /v1/embeddings" in n for n in cfg.notes))

    def test_separate_embedding_endpoint_is_honoured(self):
        cfg = load_config(env={
            "AI_LLM_API_BASE": "https://api.groq.com/openai/v1",
            "AI_LLM_API_KEY": "gsk_test",
            "AI_EMBEDDING_API_BASE": "https://api.openai.com/v1",
            "AI_EMBEDDING_MODEL": "text-embedding-3-large",
            "AI_EMBEDDING_API_KEY": "sk-emb",
        })
        self.assertEqual(cfg.embedding.provider, "openai")
        self.assertEqual(cfg.embedding.model, "text-embedding-3-large")
        self.assertFalse(any("does not serve /v1/embeddings" in n for n in cfg.notes))

    def test_embedding_key_falls_back_to_the_chat_key(self):
        cfg = load_config(env={
            "AI_LLM_API_BASE": "https://api.openai.com/v1",
            "AI_LLM_API_KEY": "sk-shared",
            "AI_EMBEDDING_API_BASE": "https://api.openai.com/v1",
        })
        self.assertTrue(cfg.embedding.has_key)

    def test_anthropic_chat_uses_the_anthropic_service(self):
        cfg = load_config(env={
            "AI_LLM_API_BASE": "https://api.anthropic.com",
            "AI_LLM_API_KEY": "sk-ant-test",
        })
        self.assertEqual(cfg.chat.service, "anthropic")
        self.assertEqual(cfg.chat.model, "claude-3-5-haiku-latest")

    def test_local_openai_compatible_endpoint(self):
        cfg = load_config(env={
            "AI_LLM_API_BASE": "http://127.0.0.1:9000/v1",
            "AI_LLM_MODEL": "mock-chat-model",
            "AI_EMBEDDING_API_BASE": "http://127.0.0.1:9002/v1",
            "AI_EMBEDDING_MODEL": "mock-embedding-model",
        })
        self.assertEqual(cfg.chat.provider, "openai-compatible")
        self.assertEqual(cfg.chat.api_base, "http://127.0.0.1:9000/v1")
        self.assertEqual(cfg.embedding.api_base, "http://127.0.0.1:9002/v1")

    def test_latency_budget_is_clamped_into_the_safe_range(self):
        cfg = load_config(env={
            "AI_LLM_API_BASE": "https://api.openai.com/v1",
            "AI_INFERENCE_LATENCY_BUDGET_MS": "99999999",
        })
        self.assertEqual(cfg.latency_budget_ms, 300_000)
        cfg = load_config(env={
            "AI_LLM_API_BASE": "https://api.openai.com/v1",
            "AI_INFERENCE_LATENCY_BUDGET_MS": "not-a-number",
        })
        self.assertEqual(cfg.latency_budget_ms, 45_000)

    def test_describe_never_leaks_the_key(self):
        cfg = load_config(env={
            "AI_LLM_API_BASE": "https://api.openai.com/v1",
            "AI_LLM_API_KEY": "sk-super-secret-value-9999",
        })
        blob = repr(cfg.describe())
        self.assertNotIn("super-secret", blob)
        self.assertIn("has_key", blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
