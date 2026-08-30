"""Static security gates for CI; runtime Odoo tests should import these checks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_no_plaintext_api_key_model_field():
    text = (ROOT / "ai_gateway/models/api_key.py").read_text()
    assert "key = fields.Char" not in text


def test_rpc_disabled():
    text = (ROOT / "ai_gateway/controllers/gateway.py").read_text()
    # No feature flag - /api/rpc is a permanent tombstone hard-coded to
    # 410, not something gated by a togglable variable.
    assert '_ENABLE_RPC' not in text
    assert 'status=410' in text


def test_production_origin_fails_closed():
    text = (ROOT / "ai_gateway/controllers/gateway.py").read_text()
    assert 'AI_GATEWAY_ALLOWED_ORIGIN is required in production' in text


def test_shared_rate_limiter():
    text = (ROOT / "ai_gateway/controllers/gateway.py").read_text()
    assert 'from .rate_limit import check as _shared_rate_limit' in text
    assert 'defaultdict' not in text
