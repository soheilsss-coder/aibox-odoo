"""
HTTP client for TencentDB Agent Memory's MemoryCore, kept as an optional external indexing/provider integration. The canonical
Odoo memory record remains the authoritative store; this client is never the
authorization source or a fallback data store.

⚠️ HONESTY NOTE (read before trusting this blindly): the exact request/
response JSON shape below is a best-effort reconstruction from public
blog posts and the project's marketing pages, NOT a primary API
reference I was able to read in full - the project is very new (open-
sourced May 2026) and its documented endpoints (/capture, /recall,
/v3/tools/list, /health) are consistent across multiple independent
sources, but exact field names inside the request/response bodies are
not verified. After running 18_setup_tencentdb_memory.sh and getting
MemoryCore actually running:
    curl -X POST http://127.0.0.1:8125/capture -H 'Content-Type: application/json' \\
      -d '{"test": "hello"}'
and compare the real response/error against what CaptureClient.capture()
below assumes - fix field names here to match, they are marked below.
"""
import logging
import os

import requests

_logger = logging.getLogger(__name__)

MEMORY_CORE_URL = os.environ.get("MEMORY_CORE_URL", "http://127.0.0.1:8125")
_TIMEOUT_SECONDS = 5  # External provider is optional indexing only; Odoo memory remains authoritative.


class MemoryCoreUnavailable(Exception):
    """Raised whenever the optional external provider cannot be reached.
    The canonical Odoo memory record remains authoritative."""


def is_configured():
    return bool(MEMORY_CORE_URL)


def health_check():
    try:
        resp = requests.get(f"{MEMORY_CORE_URL}/health", timeout=2)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def capture(user_login, key, value, scope):
    """Send one memory turn to MemoryCore for L0->L1->L2->L3 layering.
    FIELD NAMES BELOW ARE BEST-EFFORT - verify against your real
    instance and adjust the `payload` dict if MemoryCore rejects it."""
    payload = {
        "agent_id": f"odoo-{scope}",     # VERIFY: may need a real registered Agent id
        "user_id": user_login,
        "content": f"{key}: {value}",
        "metadata": {"key": key, "scope": scope, "source": "odoo-ai-gateway"},
    }
    try:
        resp = requests.post(f"{MEMORY_CORE_URL}/capture", json=payload, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        _logger.warning("MemoryCore capture failed, canonical Odoo memory remains authoritative: %s", exc)
        raise MemoryCoreUnavailable(str(exc)) from exc


def recall(user_login, query, scope_filter=None):
    """Query MemoryCore for relevant memories. FIELD NAMES BELOW ARE
    BEST-EFFORT - verify against your real instance."""
    payload = {
        "user_id": user_login,
        "query": query or "",
        "limit": 10,
    }
    if scope_filter:
        payload["filter"] = {"scope": scope_filter}
    try:
        resp = requests.post(f"{MEMORY_CORE_URL}/recall", json=payload, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        # VERIFY: assumes a `results` list of {content, metadata, score} -
        # adjust the mapping in agent_memory.py's recall_memory() if the
        # real shape differs.
        return data.get("results", [])
    except requests.RequestException as exc:
        _logger.warning("MemoryCore recall failed, canonical Odoo memory remains authoritative: %s", exc)
        raise MemoryCoreUnavailable(str(exc)) from exc
