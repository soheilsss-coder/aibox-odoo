"""Client for the local vLLM score/rerank API.

This is deliberately an optional stage. Candidate generation and ACL
filtering stay in PostgreSQL/Odoo; a failed or unregistered reranker falls
back to the deterministic RRF ordering rather than making document search
unavailable.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

RERANK_API_BASE = os.getenv(
    "AI_VLLM_RERANK_API_BASE", "http://127.0.0.1:8003"
)
RERANK_MODEL = os.getenv("AI_VLLM_RERANK_MODEL", "reranker-model")
RERANK_REVISION = os.getenv("AI_VLLM_RERANK_REVISION", RERANK_MODEL)
try:
    RERANK_TIMEOUT = max(1.0, min(float(os.getenv("AI_RAG_RERANK_TIMEOUT", "8")), 60.0))
except (TypeError, ValueError):
    RERANK_TIMEOUT = 8.0


def _profile(env: Any = None) -> tuple[str, str, str]:
    endpoint, model, revision = RERANK_API_BASE, RERANK_MODEL, RERANK_REVISION
    if env is not None and "ai.model.router" in env:
        profile = env["ai.model.router"].route(
            purpose="rerank", requires_tools=False,
        )
        endpoint = profile.endpoint or endpoint
        model = profile.model_id
        revision = profile.version or model
    return endpoint, model, revision


def rerank_texts(
    query: str,
    documents: list[str],
    *,
    top_n: int,
    env: Any = None,
    timeout: float | None = None,
) -> tuple[list[int], list[float], str]:
    """Return ``(indices, scores, revision)`` from the local rerank API.

    vLLM's Cohere-compatible endpoint returns original document indices, so
    the caller never has to trust response ordering. No document is sent to
    this function before the caller's ACL boundary has been applied.
    """
    if not query or not documents:
        return [], [], RERANK_REVISION
    endpoint, model, revision = _profile(env)
    try:
        timeout = float(timeout if timeout is not None else RERANK_TIMEOUT)
        response = requests.post(
            f"{endpoint.rstrip('/')}/rerank",
            json={
                "model": model,
                "query": query,
                "documents": documents,
                "top_n": max(1, min(int(top_n), len(documents))),
                "truncate_prompt_tokens": 4096,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results")
        if not isinstance(results, list):
            raise UserError("reranker response has no results list")
        parsed: list[tuple[int, float]] = []
        for item in results:
            index = int(item["index"])
            score = float(item["relevance_score"])
            if index < 0 or index >= len(documents):
                raise UserError("reranker returned an invalid document index")
            parsed.append((index, score))
        parsed.sort(key=lambda item: item[1], reverse=True)
        return (
            [item[0] for item in parsed[:top_n]],
            [item[1] for item in parsed[:top_n]],
            revision,
        )
    except requests.RequestException as exc:
        _logger.info("local reranker unavailable at %s: %s", endpoint, exc)
        raise UserError("local reranker unavailable") from exc
    except (KeyError, TypeError, ValueError) as exc:
        _logger.warning("invalid local reranker response: %s", exc)
        raise UserError("invalid local reranker response") from exc
