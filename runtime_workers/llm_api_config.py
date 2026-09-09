"""Provider-agnostic LLM API configuration with automatic provider detection.

Why this module exists
----------------------
Up to v58 the appliance was wired to a *self-hosted* inference stack: three
vLLM processes on 127.0.0.1:8000 (chat), :8001 (vision) and :8002 (embedding),
each pinned to one downloaded model revision. That is the right shape for a
customer's own GPU box, and it stays supported.

This module adds the other shape: point the same gateway at a **hosted API**
instead. The operator supplies a base URL and a key; the appliance figures out
which vendor that is, normalizes the URL to the dialect the Odoo ``llm``
framework speaks, and picks sane default model names. No code change and no
re-install is needed to move between vendors - only environment variables (or
the ``llm.provider`` form in the Odoo backend).

The detection is deliberately *advisory*. Every value it produces can be
overridden explicitly, because guessing a vendor from a hostname must never be
the thing that decides which credentials get sent where.

Design constraints
------------------
* Pure Python, no Odoo import. Must be importable from the seed script, from
  the runtime workers and from a plain unit test (see
  ``tests/test_llm_api_config.py``).
* Never log or return the API key. ``describe()`` returns a redacted view.
* Chat and embedding are configured **separately**. Several popular chat
  vendors (Groq, OpenRouter) do not serve ``/v1/embeddings`` at all, so forcing
  one base URL for both would silently break RAG.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "LlmEndpoint",
    "LlmApiConfig",
    "PROVIDERS",
    "detect_provider",
    "normalize_base_url",
    "load_config",
    "default_config",
]

# --------------------------------------------------------------------------
# Provider catalogue
# --------------------------------------------------------------------------
# ``base`` is the OpenAI-compatible root the Odoo ``llm`` framework needs: the
# client appends ``/chat/completions`` and ``/embeddings`` itself, so ``base``
# must NOT include those paths.
#
# ``embedding_base`` is only set for vendors that actually serve embeddings on
# the same credentials. When it is None the caller must configure embeddings
# separately (AI_EMBEDDING_API_BASE) or RAG indexing stays disabled.

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "label": "OpenAI",
        "hosts": ("api.openai.com", "openai.azure.com"),
        "base": "https://api.openai.com/v1",
        "chat_models": ("gpt-4.1-mini", "gpt-4o-mini", "gpt-4o"),
        "default_chat_model": "gpt-4.1-mini",
        "default_embedding_model": "text-embedding-3-small",
        "default_embedding_dim": 1536,
        "embedding_base": None,  # same base as chat
        "supports_embeddings": True,
        "key_env": "OPENAI_API_KEY",
        "key_prefix": ("sk-",),
    },
    "groq": {
        "label": "Groq Cloud",
        "hosts": ("api.groq.com",),
        "base": "https://api.groq.com/openai/v1",
        "chat_models": ("llama-3.3-70b-versatile", "qwen/qwen3-32b"),
        "default_chat_model": "llama-3.3-70b-versatile",
        "default_embedding_model": "",
        "default_embedding_dim": 0,
        "embedding_base": None,
        "supports_embeddings": False,  # Groq does not serve /v1/embeddings
        "key_env": "GROQ_API_KEY",
        "key_prefix": ("gsk_",),
    },
    "gemini": {
        "label": "Google Gemini",
        "hosts": ("generativelanguage.googleapis.com", "aiplatform.googleapis.com"),
        # Gemini exposes an OpenAI-compatible surface under /v1beta/openai.
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "chat_models": ("gemini-2.5-flash", "gemini-2.5-pro"),
        "default_chat_model": "gemini-2.5-flash",
        "default_embedding_model": "gemini-embedding-001",
        "default_embedding_dim": 768,
        "embedding_base": None,
        "supports_embeddings": True,
        "key_env": "GEMINI_API_KEY",
        "key_prefix": ("AIza",),
    },
    "openrouter": {
        "label": "OpenRouter",
        "hosts": ("openrouter.ai", "www.openrouter.ai"),
        "base": "https://openrouter.ai/api/v1",
        "chat_models": ("openai/gpt-4.1-mini", "anthropic/claude-3.5-haiku"),
        "default_chat_model": "openai/gpt-4.1-mini",
        "default_embedding_model": "",
        "default_embedding_dim": 0,
        "embedding_base": None,
        "supports_embeddings": False,  # chat aggregator only
        "key_env": "OPENROUTER_API_KEY",
        "key_prefix": ("sk-or-",),
    },
    "anthropic": {
        "label": "Anthropic",
        "hosts": ("api.anthropic.com",),
        # Native Anthropic API. Requires the llm_anthropic addon to be
        # installed; the caller downgrades to OpenAI-compatible via a proxy
        # when it is not.
        "base": "https://api.anthropic.com",
        "service": "anthropic",
        "chat_models": ("claude-3-5-haiku-latest", "claude-sonnet-4-5"),
        "default_chat_model": "claude-3-5-haiku-latest",
        "default_embedding_model": "",
        "default_embedding_dim": 0,
        "embedding_base": None,
        "supports_embeddings": False,
        "key_env": "ANTHROPIC_API_KEY",
        "key_prefix": ("sk-ant-",),
    },
    "mistral": {
        "label": "Mistral AI",
        "hosts": ("api.mistral.ai",),
        "base": "https://api.mistral.ai/v1",
        "chat_models": ("mistral-large-latest", "open-mistral-nemo"),
        "default_chat_model": "mistral-large-latest",
        "default_embedding_model": "mistral-embed",
        "default_embedding_dim": 1024,
        "embedding_base": None,
        "supports_embeddings": True,
        "key_env": "MISTRAL_API_KEY",
        "key_prefix": ("",),
    },
    "deepseek": {
        "label": "DeepSeek",
        "hosts": ("api.deepseek.com",),
        "base": "https://api.deepseek.com/v1",
        "chat_models": ("deepseek-chat", "deepseek-reasoner"),
        "default_chat_model": "deepseek-chat",
        "default_embedding_model": "",
        "default_embedding_dim": 0,
        "embedding_base": None,
        "supports_embeddings": False,
        "key_env": "DEEPSEEK_API_KEY",
        "key_prefix": ("sk-",),
    },
    "xai": {
        "label": "xAI (Grok)",
        "hosts": ("api.x.ai",),
        "base": "https://api.x.ai/v1",
        "chat_models": ("grok-4-latest", "grok-3-mini"),
        "default_chat_model": "grok-4-latest",
        "default_embedding_model": "",
        "default_embedding_dim": 0,
        "embedding_base": None,
        "supports_embeddings": False,
        "key_env": "XAI_API_KEY",
        "key_prefix": ("xai-",),
    },
    "deepinfra": {
        "label": "DeepInfra",
        "hosts": ("api.deepinfra.com",),
        "base": "https://api.deepinfra.com/v1/openai",
        "chat_models": ("meta-llama/Llama-3.3-70B-Instruct",),
        "default_chat_model": "meta-llama/Llama-3.3-70B-Instruct",
        "default_embedding_model": "BAAI/bge-m3",
        "default_embedding_dim": 1024,
        "embedding_base": None,
        "supports_embeddings": True,
        "key_env": "DEEPINFRA_API_KEY",
        "key_prefix": ("",),
    },
    "together": {
        "label": "Together AI",
        "hosts": ("api.together.xyz", "api.together.ai"),
        "base": "https://api.together.xyz/v1",
        "chat_models": ("meta-llama/Llama-3.3-70B-Instruct-Turbo",),
        "default_chat_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "default_embedding_model": "BAAI/bge-base-en-v1.5",
        "default_embedding_dim": 768,
        "embedding_base": None,
        "supports_embeddings": True,
        "key_env": "TOGETHER_API_KEY",
        "key_prefix": ("",),
    },
    # OpenAI-compatible *servers* rather than vendors. These are what the
    # self-hosted path and any local test double present as.
    "openai-compatible": {
        "label": "OpenAI-compatible endpoint",
        "hosts": (),
        "base": "",
        "chat_models": (),
        "default_chat_model": "local-model",
        "default_embedding_model": "embedding-model",
        "default_embedding_dim": 384,
        "embedding_base": None,
        "supports_embeddings": True,
        "key_env": "AI_LLM_API_KEY",
        "key_prefix": ("",),
    },
}

# Model-name fingerprints used only when neither AI_LLM_PROVIDER nor a known
# hostname is available. Ordered: first match wins.
_MODEL_FINGERPRINTS: Tuple[Tuple[str, str], ...] = (
    (r"^gpt-", "openai"),
    (r"^o[134](-|$)", "openai"),
    (r"^chatgpt-", "openai"),
    (r"^text-embedding-", "openai"),
    (r"^gemini-", "gemini"),
    (r"^claude-", "anthropic"),
    (r"^mistral-|^open-mistral|^codestral", "mistral"),
    (r"^deepseek-", "deepseek"),
    (r"^grok-", "xai"),
    (r"^[a-z0-9_.-]+/[a-z0-9_.-]+$", "openrouter"),  # vendor/model slug
)

# Only true loopback counts as "local". A private DNS name such as
# ``gateway.corp.internal`` is NOT loopback: it is usually a corporate egress
# proxy in front of a real vendor, and treating it as local would send a vendor
# key to a host nobody audited. Loopback, on the other hand, must never receive
# a vendor key, so it short-circuits detection below.
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0", "::1")


@dataclass
class LlmEndpoint:
    """One resolved inference endpoint (chat or embedding)."""

    provider: str
    label: str
    api_base: str
    model: str
    service: str = "openai"
    has_key: bool = False
    detected_from: str = ""
    warnings: List[str] = field(default_factory=list)

    def describe(self) -> Dict[str, Any]:
        """Redacted, JSON-safe view. Never includes the key itself."""
        return {
            "provider": self.provider,
            "label": self.label,
            "api_base": self.api_base,
            "model": self.model,
            "service": self.service,
            "has_key": self.has_key,
            "detected_from": self.detected_from,
            "warnings": list(self.warnings),
        }


@dataclass
class LlmApiConfig:
    """Resolved chat + embedding configuration for the whole appliance."""

    chat: LlmEndpoint
    embedding: Optional[LlmEndpoint]
    latency_budget_ms: int
    max_output_tokens: int
    notes: List[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.chat.api_base and self.chat.model)

    def describe(self) -> Dict[str, Any]:
        return {
            "chat": self.chat.describe(),
            "embedding": self.embedding.describe() if self.embedding else None,
            "latency_budget_ms": self.latency_budget_ms,
            "max_output_tokens": self.max_output_tokens,
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------
# Detection helpers
# --------------------------------------------------------------------------

def _host_of(url: str) -> str:
    """Lower-case hostname of ``url`` without importing urlsplit's port logic."""
    if not url:
        return ""
    match = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#]+)", url.strip())
    authority = match.group(1) if match else url.strip().split("/")[0]
    return authority.rsplit("@", 1)[-1].split(":")[0].lower()


def _is_loopback(url: str) -> bool:
    return _host_of(url) in _LOOPBACK_HOSTS


def detect_provider(api_base: str = "", model: str = "", explicit: str = "") -> Tuple[str, str]:
    """Return ``(provider_id, reason)`` for a base URL and/or model name.

    Order of precedence: explicit override, then known hostname, then the
    model-name fingerprint, then loopback, then the generic OpenAI-compatible
    fallback. Nothing here is authorization - it only chooses defaults.

    Loopback is checked *after* the hostname table on purpose: a URL like
    ``http://127.0.0.1:8000/v1`` never matches a vendor host, so it lands on
    ``openai-compatible`` and no vendor key is ever selected for it.
    """
    explicit = (explicit or "").strip().lower()
    if explicit:
        if explicit in PROVIDERS:
            return explicit, "explicit AI_LLM_PROVIDER"
        return "openai-compatible", "unknown AI_LLM_PROVIDER=%r, using OpenAI-compatible" % explicit

    base = (api_base or "").strip()
    host = _host_of(base)
    if host:
        for pid, spec in PROVIDERS.items():
            if host in spec["hosts"]:
                return pid, "hostname %s" % host

    # A private/internal host we do not recognize is most often a corporate
    # proxy in front of a real vendor, so the model name is still a useful
    # hint. It is only a hint: AI_LLM_PROVIDER overrides it.
    name = (model or "").strip().lower()
    if name:
        for pattern, pid in _MODEL_FINGERPRINTS:
            if re.match(pattern, name):
                return pid, "model name %r" % model

    if _is_loopback(base):
        return "openai-compatible", "loopback host %s" % host
    if base:
        return "openai-compatible", "unrecognized host %s, using OpenAI-compatible" % (host or "?")
    return "openai-compatible", "no base URL supplied"


def normalize_base_url(api_base: str, provider: str = "openai-compatible") -> Tuple[str, List[str]]:
    """Return a base URL the OpenAI client can append ``/chat/completions`` to.

    Operators paste all of these in the wild and every one of them should work:
        https://api.openai.com
        https://api.openai.com/v1
        https://api.openai.com/v1/
        https://api.openai.com/v1/chat/completions
        https://generativelanguage.googleapis.com/v1beta/models
    """
    warnings: List[str] = []
    url = (api_base or "").strip().rstrip("/")
    if not url:
        return "", warnings

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        warnings.append("api_base has no scheme; assuming https://")
        url = "https://" + url

    # Strip a trailing endpoint path if the operator pasted the full URL.
    for suffix in ("/chat/completions", "/completions", "/embeddings", "/models"):
        if url.lower().endswith(suffix):
            warnings.append("stripped %r from api_base" % suffix)
            url = url[: -len(suffix)].rstrip("/")
            break

    # Gemini's OpenAI-compatible surface lives under /v1beta/openai; the plain
    # /v1beta root is the native REST dialect and will 404 on /chat/completions.
    host = _host_of(url)
    if "generativelanguage.googleapis.com" in host and not url.rstrip("/").endswith("/openai"):
        rewritten = "https://generativelanguage.googleapis.com/v1beta/openai"
        if "/v1beta" not in url:
            warnings.append("rewrote Gemini base to %s (OpenAI-compatible surface)" % rewritten)
            url = rewritten
        else:
            warnings.append("Gemini base rewritten to %s" % rewritten)
            url = rewritten

    # Everything else: make sure a /vN segment is present unless the vendor's
    # canonical base deliberately has none (native Anthropic).
    spec = PROVIDERS.get(provider, {})
    canonical = (spec.get("base") or "").rstrip("/")
    if provider == "anthropic":
        return url, warnings
    if canonical and _host_of(url) == _host_of(canonical) and not re.search(r"/v\d+[a-z]*(/.*)?$", url):
        warnings.append("appended the version path from the canonical base: %s" % canonical)
        url = canonical

    return url, warnings


def _resolve_key(provider: str, env: Dict[str, str], explicit_key: str = "") -> Tuple[str, str]:
    """Pick the API key, preferring the explicit appliance variable.

    ``env`` is passed in rather than read from ``os.environ`` so a caller can
    resolve a configuration from an arbitrary mapping - which is what makes
    this unit-testable without mutating the process environment.
    """
    if explicit_key:
        return explicit_key, "AI_LLM_API_KEY"
    spec = PROVIDERS.get(provider, {})
    vendor_env = spec.get("key_env") or ""
    if vendor_env and vendor_env != "AI_LLM_API_KEY":
        value = (env.get(vendor_env) or "").strip()
        if value:
            return value, vendor_env
    return (env.get("AI_LLM_API_KEY") or "").strip(), "AI_LLM_API_KEY"


def _redact(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return "%s...%s" % (key[:4], key[-4:])


def _as_int(value, fallback, minimum=1, maximum=300_000):
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return max(minimum, min(int(fallback), maximum))


def _build_endpoint(
    role: str,
    base: str,
    key: str,
    model: str,
    explicit_provider: str,
    default_model: str,
) -> Tuple[Optional[LlmEndpoint], List[str]]:
    """Resolve one endpoint (role is ``chat`` or ``embedding``)."""
    notes: List[str] = []
    base = (base or "").strip()
    if not base:
        return None, notes

    provider, reason = detect_provider(base, model or default_model, explicit_provider)
    url, url_warnings = normalize_base_url(base, provider)
    notes.extend("[%s] %s" % (role, w) for w in url_warnings)
    notes.append("[%s] provider=%s (%s)" % (role, provider, reason))

    spec = PROVIDERS.get(provider, {})
    chosen_model = (model or "").strip() or default_model or spec.get("default_chat_model", "")
    if not (model or "").strip() and chosen_model:
        notes.append("[%s] no model configured, defaulting to %s" % (role, chosen_model))

    service = "anthropic" if (spec.get("service") == "anthropic" and role == "chat") else "openai"

    endpoint = LlmEndpoint(
        provider=provider,
        label=spec.get("label") or provider,
        api_base=url,
        model=chosen_model,
        service=service,
        has_key=bool(key),
        detected_from=reason,
        warnings=list(url_warnings),
    )
    if not key:
        endpoint.warnings.append(
            "no API key resolved for %s; set AI_LLM_API_KEY (or %s)"
            % (provider, spec.get("key_env") or "the vendor key variable")
        )
    return endpoint, notes


def load_config(env: Optional[Dict[str, str]] = None) -> LlmApiConfig:
    """Resolve the appliance's chat + embedding configuration from the environment.

    Chat variables
        AI_LLM_API_BASE      base URL of the chat API (vendor or self-hosted)
        AI_LLM_API_KEY       key; falls back to the vendor's own variable
        AI_LLM_MODEL         chat model name
        AI_LLM_PROVIDER      force a provider id, skipping detection

    Embedding variables (separate on purpose - several chat vendors do not
    serve embeddings, and RAG vectors must stay on one pinned dimension)
        AI_EMBEDDING_API_BASE
        AI_EMBEDDING_API_KEY   (falls back to AI_LLM_API_KEY)
        AI_EMBEDDING_MODEL
        AI_EMBEDDING_DIM

    When no embedding base is configured the appliance falls back to the
    legacy local inference endpoint so an existing deployment keeps working.
    """
    e = dict(env) if env is not None else dict(os.environ)

    explicit = (e.get("AI_LLM_PROVIDER") or "").strip()
    chat_base = (e.get("AI_LLM_API_BASE") or "").strip()
    chat_model = (e.get("AI_LLM_MODEL") or "").strip()

    chat_provider = detect_provider(chat_base, chat_model, explicit)[0]
    chat_key, _key_source = _resolve_key(chat_provider, e, (e.get("AI_LLM_API_KEY") or "").strip())

    default_chat_model = (
        PROVIDERS.get(chat_provider, {}).get("default_chat_model") or "local-model"
    )
    chat, notes = _build_endpoint(
        "chat", chat_base, chat_key, chat_model, explicit, default_chat_model
    )
    if chat is None:
        notes.append("[chat] AI_LLM_API_BASE is empty - no chat endpoint configured")
        chat = LlmEndpoint(
            provider="openai-compatible",
            label="Not configured",
            api_base="",
            model="",
            detected_from="AI_LLM_API_BASE unset",
            has_key=False,
        )

    emb_base = (e.get("AI_EMBEDDING_API_BASE") or "").strip()
    emb_model = (e.get("AI_EMBEDDING_MODEL") or "").strip()
    emb_key = (e.get("AI_EMBEDDING_API_KEY") or chat_key or "").strip()
    embedding, emb_notes = _build_endpoint(
        "embedding", emb_base, emb_key, emb_model,
        (e.get("AI_EMBEDDING_PROVIDER") or "").strip(),
        PROVIDERS.get(chat.provider, {}).get("default_embedding_model") or "embedding-model",
    )
    notes.extend(emb_notes)

    if embedding is None:
        legacy = "http://127.0.0.1:8002/v1"
        notes.append(
            "[embedding] AI_EMBEDDING_API_BASE is empty - keeping the legacy "
            "local inference endpoint %s" % legacy
        )
        embedding = LlmEndpoint(
            provider="openai-compatible",
            label="Local inference (legacy fallback)",
            api_base=legacy,
            model=emb_model or "embedding-model",
            detected_from="AI_EMBEDDING_API_BASE unset",
            has_key=bool(emb_key),
        )

    if chat.provider in PROVIDERS and not PROVIDERS[chat.provider]["supports_embeddings"] \
            and not (e.get("AI_EMBEDDING_API_BASE") or "").strip():
        notes.append(
            "[embedding] %s does not serve /v1/embeddings; RAG indexing will fail "
            "until AI_EMBEDDING_API_BASE points at an embedding-capable API"
            % chat.provider
        )

    latency = _as_int(e.get("AI_INFERENCE_LATENCY_BUDGET_MS"), 45_000, 100, 300_000)
    max_out = _as_int(e.get("AI_LLM_MAX_OUTPUT_TOKENS"), 2_048, 1, 32_768)

    return LlmApiConfig(
        chat=chat,
        embedding=embedding,
        latency_budget_ms=latency,
        max_output_tokens=max_out,
        notes=notes,
    )


def default_config() -> LlmApiConfig:
    """Configuration with no environment present - used by tests and --help."""
    return load_config(env={})
