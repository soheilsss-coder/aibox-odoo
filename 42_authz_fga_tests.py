"""Static guard tests for v42 authorization invariants."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GRANT = ROOT / "custom_addons/ai_business_tools/models/access_grant.py"
AUTH = ROOT / "custom_addons/ai_control_plane/models/authorization.py"


def test_grants_do_not_mutate_group_membership():
    text = GRANT.read_text()
    assert '"users": [(4' not in text
    assert '"users": [(3' not in text
    assert "group_id.write" not in text


def test_authorization_evaluates_grants():
    text = AUTH.read_text()
    assert "grant_allows" in text
    assert "effective_groups" in text


def test_fga_is_time_bounded():
    text = (ROOT / "custom_addons/ai_control_plane/models/fga.py").read_text()
    assert "starts_at" in text and "expires_at" in text
    assert "checked_at" in text
