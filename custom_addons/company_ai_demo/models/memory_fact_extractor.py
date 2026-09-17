"""Local, conservative JSON extraction for candidate memory facts.

The extractor is intentionally separate from persistence. It can only create
candidate facts with a source quote; confirmation and production recall remain
an Odoo business decision.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
from typing import Any

import requests

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def plain_message(body: str) -> str:
    value = html.unescape(str(body or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(value.split())[:12000]


def _routing(env: Any = None) -> tuple[str, str]:
    endpoint = os.getenv("AI_VLLM_CHAT_API_BASE", "http://127.0.0.1:8000/v1")
    model = os.getenv("AI_MEMORY_EXTRACTION_MODEL", "local-model")
    if env is not None and "ai.model.router" in env:
        try:
            profile = env["ai.model.router"].route(
                purpose="chat", requires_tools=False,
            )
            endpoint = profile.endpoint or endpoint
            model = profile.model_id
        except Exception as exc:
            # Candidate extraction is optional, but production must not send
            # data to an unregistered or unbenchmarked fallback model.
            if os.getenv("AI_GATEWAY_ENV", "development") == "production":
                raise UserError("No benchmark-certified local chat model is available for memory extraction") from exc
    return endpoint, model


def extract_candidates(message_body: str, env: Any = None) -> list[dict[str, Any]]:
    """Extract only explicit, low-risk statements from one local message."""
    source = plain_message(message_body)
    if len(source) < 8:
        return []
    endpoint, model = _routing(env)
    schema = {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string", "maxLength": 255},
                        "predicate": {"type": "string", "maxLength": 160},
                        "value": {"type": "string", "maxLength": 4000},
                        "object_type": {"type": "string", "enum": ["text", "number", "date", "boolean", "entity", "json"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "source_quote": {"type": "string", "maxLength": 2000},
                        "valid_from": {"type": "string", "maxLength": 64},
                        "valid_to": {"type": "string", "maxLength": 64},
                    },
                    "required": ["subject", "predicate", "value", "confidence", "source_quote"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["facts"],
        "additionalProperties": False,
    }
    instruction = (
        "Extract only facts explicitly asserted by the user in the source text. "
        "Do not infer preferences, permissions, employment data, identities, secrets, "
        "or future intentions. Return an empty facts array when uncertain. "
        "Every fact must include a verbatim source_quote copied from the source text. "
        "This is a candidate for human confirmation, not a trusted answer."
    )
    try:
        response = requests.post(
            f"{endpoint.rstrip('/')}/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": source},
                ],
                "temperature": 0,
                "max_tokens": 900,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "memory_facts", "schema": schema, "strict": True},
                },
            },
            timeout=max(5, min(int(os.getenv("AI_MEMORY_EXTRACTION_TIMEOUT", "20")), 60)),
        )
        response.raise_for_status()
        payload = response.json()
        content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        content = str(content).strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
        parsed = json.loads(content)
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        raise UserError("local memory extraction is unavailable") from exc

    facts = parsed.get("facts") if isinstance(parsed, dict) else []
    if not isinstance(facts, list):
        return []
    valid = []
    for fact in facts[:8]:
        if not isinstance(fact, dict):
            continue
        subject = str(fact.get("subject") or "").strip()
        predicate = str(fact.get("predicate") or "").strip()
        value = str(fact.get("value") or "").strip()
        quote = str(fact.get("source_quote") or "").strip()
        if not subject or not predicate or not value or not quote:
            continue
        if quote.casefold() not in source.casefold():
            # A model-generated paraphrase is not a valid provenance quote.
            continue
        try:
            confidence = max(0.0, min(float(fact.get("confidence", 0.0)), 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.70:
            continue
        valid.append({
            "subject": subject[:255], "predicate": predicate[:160],
            "value": value[:16000], "object_type": fact.get("object_type", "text"),
            "confidence": confidence, "source_quote": quote[:2000],
            "valid_from": str(fact.get("valid_from") or "")[:64],
            "valid_to": str(fact.get("valid_to") or "")[:64],
        })
    return valid
