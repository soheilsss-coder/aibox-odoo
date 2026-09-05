import hashlib
import logging
import math
import os
from array import array
from collections import OrderedDict
from threading import Lock

import requests

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Third native serving unit, separate from chat (8000) and vision
# (8001). The deployment alias is configurable; the default embedding
# revision is expected to produce 1024 dimensions.
# 1024-dim native output (must match EMBEDDING_DIM in
# document_chunk.py - if you change the served model, change both).
EMBEDDING_API_BASE = os.getenv(
    "AI_VLLM_EMBEDDING_API_BASE", "http://127.0.0.1:8002/v1"
)
EMBEDDING_MODEL = os.getenv("AI_VLLM_EMBEDDING_MODEL", "embedding-model")
EMBEDDING_REVISION = os.getenv("AI_VLLM_EMBEDDING_REVISION", EMBEDDING_MODEL)
# Qwen3 uses an instruction on the query side only. BGE-M3 explicitly does
# not require a query instruction, so the model-name guard below keeps the
# same client compatible with both benchmark candidates.
EMBEDDING_QUERY_INSTRUCTION = os.getenv(
    "AI_RAG_EMBEDDING_QUERY_INSTRUCTION",
    "Retrieve the authorized document passage that answers the user's query",
).strip()
try:
    _QUERY_CACHE_SIZE = max(0, int(os.getenv("AI_RAG_QUERY_CACHE_SIZE", "2048")))
except (TypeError, ValueError):
    _QUERY_CACHE_SIZE = 2048
_query_cache = OrderedDict()
_query_cache_lock = Lock()


def _query_cache_key(endpoint, model, text):
    # Store only a digest, never the user's query text. The endpoint/model are
    # part of the key so a deployment change cannot reuse a vector from the
    # wrong embedding revision.
    value = "%s\x00%s\x00%s" % (endpoint, model, text)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cached_query_vector(key):
    if not _QUERY_CACHE_SIZE:
        return None
    with _query_cache_lock:
        vector = _query_cache.get(key)
        if vector is not None:
            _query_cache.move_to_end(key)
            return list(vector)
    return None


def _cache_query_vector(key, vector):
    if not _QUERY_CACHE_SIZE:
        return
    with _query_cache_lock:
        # float32 keeps the bounded cache small: 2,048 x 1,024 dimensions
        # are about 8 MiB rather than tens of MiB of Python float objects.
        _query_cache[key] = array("f", vector)
        _query_cache.move_to_end(key)
        while len(_query_cache) > _QUERY_CACHE_SIZE:
            _query_cache.popitem(last=False)


def embed_texts(texts, timeout=60, env=None, is_query=False, instruction=None):
    """Call the local embedding server. Returns a list of float-vectors
    in the SAME order as `texts` (defensively re-sorted by the
    response's own `index` field, since the OpenAI-compatible spec
    does not guarantee response order matches request order).

    Raises UserError (never returns an empty/silent result) if the
    embedding server is unreachable - a semantic search tool that
    quietly returns nothing because a dependency was down would be
    worse than one that visibly tells the model/user to check it,
    same reasoning applied elsewhere in this project (e.g. the Golden
    Rule note about never kill -9'ing vLLM).
    """
    if not texts:
        return []
    endpoint = EMBEDDING_API_BASE
    model = EMBEDDING_MODEL
    revision = EMBEDDING_REVISION
    if env is not None and "ai.model.router" in env:
        try:
            profile = env["ai.model.router"].route(purpose="embedding")
            endpoint = profile.endpoint or endpoint
            model = profile.model_id
            revision = profile.version or model
        except Exception as exc:
            raise UserError("No benchmark-certified embedding model is available; certify the embedding model before enabling RAG.") from exc
    input_texts = list(texts)
    if is_query and len(input_texts) == 1:
        query_instruction = (instruction or EMBEDDING_QUERY_INSTRUCTION).strip()
        # BGE-M3's model card says not to add instructions. Qwen3 and other
        # instruction-aware profiles benefit from a one-sentence task prompt.
        if query_instruction and "bge-m3" not in model.casefold():
            input_texts[0] = "Instruct: %s\nQuery: %s" % (query_instruction, input_texts[0])
    cache_model = "%s@%s" % (model, revision)
    cache_key = _query_cache_key(endpoint, cache_model, input_texts[0]) if len(input_texts) == 1 else None
    if cache_key:
        cached = _cached_query_vector(cache_key)
        if cached is not None:
            return [cached]
    try:
        resp = requests.post(
            f"{endpoint.rstrip('/')}/embeddings",
            json={"model": model, "input": input_texts},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        items = sorted(data["data"], key=lambda item: item["index"])
        if len(items) != len(input_texts) or [item["index"] for item in items] != list(range(len(input_texts))):
            raise UserError("Embedding response does not contain one ordered vector per input.")
        vectors = [[float(value) for value in item["embedding"]] for item in items]
        if any(len(v) != 1024 or any(not math.isfinite(value) for value in v) for v in vectors):
            raise UserError("Embedding dimension/value mismatch: expected 1024 finite values. Reconfigure the certified embedding model and reindex documents.")
        if cache_key and vectors:
            _cache_query_vector(cache_key, vectors[0])
        return vectors
    except requests.RequestException as exc:
        _logger.error("Embedding server unreachable at %s: %s", endpoint, exc)
        raise UserError(
            "جستجوی اسناد موقتاً در دسترس نیست. لطفاً بعداً دوباره تلاش کنید."
        ) from exc
    except (KeyError, ValueError, TypeError) as exc:
        _logger.error("Unexpected embedding response shape: %s", exc)
        raise UserError(f"پاسخ غیرمنتظره از سرور embedding: {exc}") from exc


def to_pgvector_literal(vector):
    """Format a Python float list as a pgvector text literal
    ('[0.123,-0.456,...]') for use with an explicit ::vector cast in
    raw SQL. Deliberately NOT relying on a pgvector psycopg2 adapter
    being registered - Odoo's own psycopg2 connection setup is not
    something this module should reach into, so plain text + cast is
    the more robust integration point."""
    return "[" + ",".join(f"{x:.8f}" for x in vector) + "]"
