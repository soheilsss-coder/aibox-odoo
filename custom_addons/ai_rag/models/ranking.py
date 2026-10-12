"""Small, dependency-free ranking primitives for the native RAG path.

The database remains responsible for ACL filtering and candidate generation.
This module only merges already-authorized candidates, which keeps ranking
logic testable without importing Odoo or leaking records through a helper.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def reciprocal_rank_fusion(
    candidate_lists: Iterable[Iterable[dict[str, Any]]],
    *,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Fuse ranked candidate lists without comparing incompatible scores.

    Dense cosine, PostgreSQL ts_rank and trigram similarity have different
    distributions. RRF uses only rank, so a score calibration bug in one
    retriever cannot dominate the other retrievers. Rows are copied before
    augmentation and are keyed by ``chunk_id``.
    """
    try:
        rrf_k = max(1, int(rrf_k))
    except (TypeError, ValueError):
        rrf_k = 60

    merged: dict[Any, dict[str, Any]] = {}
    ranks: dict[Any, dict[str, int]] = {}
    for source_index, candidates in enumerate(candidate_lists):
        source = ("vector", "lexical", "trigram")[source_index] if source_index < 3 else f"source_{source_index}"
        seen: set[Any] = set()
        for rank, original in enumerate(candidates, start=1):
            chunk_id = original.get("chunk_id")
            if chunk_id is None or chunk_id in seen:
                continue
            seen.add(chunk_id)
            row = merged.setdefault(chunk_id, dict(original))
            # A row may first arrive from one scan and later from another;
            # preserve every non-zero signal and the complete source metadata.
            for key, value in original.items():
                if key not in row or row[key] in (None, ""):
                    row[key] = value
            ranks.setdefault(chunk_id, {})[source] = rank

    for chunk_id, row in merged.items():
        row["retrieval_ranks"] = ranks.get(chunk_id, {})
        row["rrf_score"] = sum(
            1.0 / (rrf_k + rank)
            for rank in row["retrieval_ranks"].values()
        )
        # Keep the old public field name for compatibility with callers and
        # audits; it now means the fused rank, not an invalid weighted sum of
        # raw scores.
        row["hybrid_score"] = row["rrf_score"]

    return sorted(
        merged.values(),
        key=lambda row: (-float(row.get("rrf_score") or 0.0), int(row.get("chunk_id") or 0)),
    )


def rerank_ordered_rows(rows: list[dict[str, Any]], scores: Iterable[float]) -> list[dict[str, Any]]:
    """Apply local reranker scores to rows while preserving stable ties."""
    scored = []
    for position, (row, score) in enumerate(zip(rows, scores)):
        try:
            numeric = float(score)
        except (TypeError, ValueError):
            numeric = float("-inf")
        updated = dict(row)
        updated["rerank_score"] = numeric
        scored.append((numeric, -position, updated))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored]
