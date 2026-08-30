import ast
import os
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[2]


def all_py():
    return [p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts]


def test_python_compiles():
    for path in all_py():
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_rpc_is_hard_disabled():
    text=(ROOT/"ai_gateway/controllers/gateway.py").read_text()
    # No feature flag - /api/rpc is a permanent tombstone hard-coded to
    # 410, not something gated by a togglable variable.
    assert "_ENABLE_RPC" not in text
    assert 'status=410' in text
    assert 'permanently disabled' in text


def test_workflow_does_not_sudo_mutate_arbitrary_activity_target():
    text=(ROOT/"ai_workflow/models/workflow.py").read_text()
    start=text.index('if action == "activity":')
    end=text.index('if action == "event":', start)
    block=text[start:end]
    assert ".activity_schedule(" not in block
    assert ".sudo().browse" not in block
    assert 'workflow.activity.requested' in block


def test_customer_plane_contracts():
    customer=ROOT.parent/"ai_customer_plane"
    assert (customer/"models/delegation.py").exists()
    assert (customer/"models/sso.py").exists()
    assert (customer/"models/scim.py").exists()
    assert (customer/"controllers/scim_api.py").exists()
    text=(customer/"controllers/scim_api.py").read_text()
    assert "/scim/v2/Users" in text
    assert "/scim/v2/Groups" in text


def test_no_plaintext_api_key_model_field():
    text=(ROOT/"ai_gateway/models/api_key.py").read_text()
    assert re.search(r'^\s*key\s*=\s*fields\.', text, re.M) is None
    assert "key_hash" in text
