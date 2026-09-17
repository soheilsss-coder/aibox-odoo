"""Pure-Python inference policy primitives.

The serving process owns batching and KV-cache scheduling. The application
owns workload classification and safe budgets so a simple request cannot
silently consume the reasoning/long-context budget. No provider or model name
is returned by these helpers; they are internal routing inputs only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_budget(default):
    """Allow ops to tune the request latency budget for their inference
    hardware. The stock defaults assume a fast accelerator; a CPU-served
    deployment needs a much larger window or every route call fails the
    benchmark gate and no model is ever routable."""
    try:
        return max(100, min(int(os.environ.get("AI_INFERENCE_LATENCY_BUDGET_MS", default)), 300_000))
    except (TypeError, ValueError):
        return max(100, min(default, 300_000))


@dataclass(frozen=True)
class InferenceBudget:
    """Validated request budget passed to the internal model selector."""

    purpose: str = "chat"
    latency_budget_ms: int = 12_000
    max_input_chars: int = 32_000
    max_output_tokens: int = 1_024
    temperature: float = 0.2
    requires_tools: bool = True
    requires_vision: bool = False

    def __post_init__(self):
        if self.purpose not in {"chat", "reasoning", "vision", "embedding", "rerank"}:
            raise ValueError("unsupported inference purpose")
        if not 100 <= int(self.latency_budget_ms) <= 300_000:
            raise ValueError("latency budget is outside the safe range")
        if not 256 <= int(self.max_input_chars) <= 2_000_000:
            raise ValueError("input budget is outside the safe range")
        if not 1 <= int(self.max_output_tokens) <= 32_768:
            raise ValueError("output budget is outside the safe range")
        if not 0.0 <= float(self.temperature) <= 2.0:
            raise ValueError("temperature is outside the safe range")
        if self.requires_vision and self.purpose != "vision":
            raise ValueError("vision requests must use the vision purpose")


def classify_request(message: str = "", has_attachment: bool = False) -> InferenceBudget:
    """Classify a request conservatively without asking the model to classify it.

    This is not authorization and never grants a tool. It only selects a
    latency/output budget; the execution gate remains authoritative.
    """
    text = str(message or "")
    lowered = text.casefold()
    if has_attachment and any(word in lowered for word in ("عکس", "تصویر", "image", "photo", "نشان", "what is")):
        return InferenceBudget(
            purpose="vision", latency_budget_ms=30_000, max_input_chars=64_000,
            max_output_tokens=1_500, temperature=0.1, requires_tools=False,
            requires_vision=True,
        )
    reasoning_markers = (
        "approve", "reject", "post", "payment", "invoice", "workflow", "policy",
        "تایید", "رد", "پرداخت", "فاکتور", "فرآیند", "چند مرحله", "مقایسه کن",
    )
    if len(text) > 2_000 or any(marker in lowered for marker in reasoning_markers):
        long_budget = _env_budget(45_000)
        return InferenceBudget(
            purpose="reasoning", latency_budget_ms=long_budget, max_input_chars=128_000,
            max_output_tokens=3_072, temperature=0.1, requires_tools=True,
        )
    chat_budget = _env_budget(300_000)
    return InferenceBudget(latency_budget_ms=chat_budget)
