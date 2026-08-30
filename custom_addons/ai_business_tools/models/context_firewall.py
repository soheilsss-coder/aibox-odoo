import re

from odoo import models

# Roadmap #28 - Context Firewall.
#
# Before any tool result (or audit-log payload) can reach the model's
# context, strip anything that looks like a secret. This is
# deliberately a simple, explicit denylist + a couple of regex
# patterns, NOT an attempt at a general PII/secret classifier - in the
# same honest spirit as ai.gateway.tool.risk's docstring: a "smart"
# filter that silently misses things is more dangerous than a dumb one
# everyone can read and extend in one place.
#
# HONEST LIMITATION: the long-token regex below (32+ chars, no
# whitespace) is intentionally broad. Persian/English prose almost
# never contains a single 32-character run with no spaces, so in
# practice this mostly catches API keys/tokens/hashes - but it CAN
# also redact a legitimate long identifier (an order number, a hash
# the user actually wanted to see). That trade-off is deliberate: for
# a business assistant, silently leaking a credential is worse than
# occasionally over-redacting a harmless-looking token. If this proves
# too aggressive in real use, narrow it per-tool rather than removing
# it globally.

_FORBIDDEN_KEYS = {
    "password", "passwd", "pwd", "api_key", "apikey", "api_secret",
    "secret", "secret_key", "token", "access_token", "refresh_token",
    "private_key", "pii", "ssn", "national_id", "credit_card", "card_number",
    "cvv", "iban", "bank_account", "db_password", "db_pass",
}

_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),          # OpenAI-style API keys
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),           # generic long tokens/hex/base64 runs
    re.compile(r"\b\d{13,19}\b"),                      # credit-card-length digit runs
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),  # email
    re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)"),  # phone-like PII
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", re.I),  # IBAN-like
]

REDACTED = "[REDACTED-by-context-firewall]"


def scrub_value(value):
    """Recursively scrub a single value (str/dict/list/anything else)."""
    if isinstance(value, str):
        text = value
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text
    if isinstance(value, dict):
        return scrub_dict(value)
    if isinstance(value, (list, tuple)):
        return [scrub_value(v) for v in value]
    return value


def scrub_dict(data):
    """Scrub a dict: forbidden KEY names are fully replaced regardless
    of their value's shape; every other value is recursively scrubbed
    for secret-shaped strings."""
    if not isinstance(data, dict):
        return scrub_value(data)
    cleaned = {}
    for key, value in data.items():
        normalized_key = key.strip().lower().replace(" ", "_") if isinstance(key, str) else key
        if normalized_key in _FORBIDDEN_KEYS:
            cleaned[key] = REDACTED
        else:
            cleaned[key] = scrub_value(value)
    return cleaned


class LLMToolContextFirewall(models.Model):
    """Mixin: any llm.tool method can call self._context_firewall(data)
    on whatever it is about to return to the model, to strip forbidden
    fields / secret-shaped strings first. Applied so far to:
    recall_memory, read_attached_file, search_documents_semantic,
    list_documents/get_document (added in v22, see company_document.py
    for why those two had been missed), and the central audit-log
    writer (ai.gateway.audit.log.log(), so a secret a tool was careless
    with never even reaches the DB). Extend this to any NEW tool that
    echoes back user-supplied or document-sourced free text."""

    _inherit = "llm.tool"

    def _context_firewall(self, data):
        return scrub_dict(data)
