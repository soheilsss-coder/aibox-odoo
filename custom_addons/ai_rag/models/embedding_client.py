import logging

import requests

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Third vLLM instance, separate from the chat model (8000) and vision
# model (8001) - see /opt/start_vllm_embed.sh. Qwen3-Embedding-0.6B,
# 1024-dim native output (must match EMBEDDING_DIM in
# document_chunk.py - if you change the served model, change both).
EMBEDDING_API_BASE = "http://127.0.0.1:8002/v1"
EMBEDDING_MODEL = "embedding-model"


def embed_texts(texts, timeout=60, env=None):
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
    if env is not None and "ai.model.router" in env:
        try:
            profile = env["ai.model.router"].route(purpose="embedding")
            endpoint = profile.endpoint or endpoint
            model = profile.model_id
        except Exception as exc:
            raise UserError("No benchmark-certified embedding model is available; certify the embedding model before enabling RAG.") from exc
    try:
        resp = requests.post(
            f"{endpoint.rstrip('/')}/embeddings",
            json={"model": model, "input": texts},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        items = sorted(data["data"], key=lambda item: item["index"])
        vectors = [item["embedding"] for item in items]
        if any(len(v) != 1024 for v in vectors):
            raise UserError("Embedding dimension mismatch: expected 1024. Reconfigure the certified embedding model and reindex documents.")
        return vectors
    except requests.RequestException as exc:
        _logger.error("Embedding server unreachable at %s: %s", EMBEDDING_API_BASE, exc)
        raise UserError(
            "سرور embedding محلی در دسترس نیست (پورت ۸۰۰۲). قبل از استفاده "
            "از جستجوی معنایی اسناد یا reindex، ابتدا اجرا کنید:\n"
            "  /opt/start_vllm_embed.sh"
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
