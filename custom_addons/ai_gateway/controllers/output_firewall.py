"""Customer-facing output firewall.

The assistant must not reveal implementation branding, internal ORM names,
provider/model identifiers, stack traces, or internal API paths.  This is a
last-line control in addition to prompt instructions; it is intentionally
conservative and should be complemented by runtime output tests.
"""
from __future__ import annotations

import re


_REPLACEMENTS = (
    (re.compile(r"\b(?:odoo|odoo-llm)\b", re.IGNORECASE), "the enterprise system"),
    (re.compile(r"\b(?:vllm|qwen|glimmer|llama|huggingface)\b", re.IGNORECASE), "the configured AI service"),
    (re.compile(
        r"\b(?:res|ir|mail|ai|hr|project|sale|purchase|stock|account|crm|calendar|documents|pos|mrp)\.[a-z_][a-z0-9_]*\b",
        re.IGNORECASE,
    ), "the relevant business record"),
    (re.compile(r"(?:/api|/scim|/web|/longpolling)/[A-Za-z0-9_./{}<>:-]*", re.IGNORECASE), "the secure service endpoint"),
    (re.compile(r"\b(?:Traceback|AccessError|ValidationError|NameError|TypeError|KeyError|psycopg2|SQLAlchemy)\b", re.IGNORECASE), "an internal service error"),
    (re.compile(r"\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?\b", re.IGNORECASE), "the service host"),
)

# Keys that describe the implementation/control plane.  Business values are
# retained; technical metadata is omitted before a direct tool result reaches
# a browser, channel bridge, or model context.
_TECHNICAL_KEYS = {
    "model", "model_name", "fields", "field_names", "module", "module_name",
    "technical_name", "handler", "handler_key", "source", "coverage",
    "integration_level", "adapter", "adapter_state", "event_type", "scope",
    "index_version", "retrieval_mode", "chunk_id",
}


def scrub_public_text(value):
    """Return text safe for customer-facing assistant channels."""
    if value is None:
        return ""
    text = str(value)
    for pattern, replacement in _REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def scrub_public_payload(value):
    """Remove technical metadata recursively from a public result.

    This is intentionally separate from ``scrub_dict`` in the context
    firewall: the latter redacts secrets, while this function enforces the
    product contract that ORM/control-plane identifiers do not become a
    customer-facing API or assistant response.
    """
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized = key.strip().lower() if isinstance(key, str) else key
            if normalized in _TECHNICAL_KEYS:
                continue
            cleaned[key] = scrub_public_payload(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [scrub_public_payload(item) for item in value]
    if isinstance(value, str):
        return scrub_public_text(value)
    return value
