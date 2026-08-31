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
    (re.compile(r"\b(?:res\.[a-z_]+|ir\.[a-z_]+|mail\.[a-z_]+|ai\.[a-z_]+)\b", re.IGNORECASE), "the relevant business record"),
    (re.compile(r"(?:/api|/scim|/web|/longpolling)/[A-Za-z0-9_./{}<>:-]*", re.IGNORECASE), "the secure service endpoint"),
    (re.compile(r"\b(?:Traceback|AccessError|ValidationError|NameError|TypeError|KeyError|psycopg2|SQLAlchemy)\b", re.IGNORECASE), "an internal service error"),
    (re.compile(r"\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?\b", re.IGNORECASE), "the service host"),
)


def scrub_public_text(value):
    """Return text safe for customer-facing assistant channels."""
    if value is None:
        return ""
    text = str(value)
    for pattern, replacement in _REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text
