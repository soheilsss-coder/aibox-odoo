#!/usr/bin/env python3
"""Static v46 tests. These complement, not replace, live Odoo E2E tests."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent

def text(rel):
    return (ROOT / rel).read_text(errors='ignore')

gate = text('custom_addons/ai_gateway/models/execution_gate.py')
unified = text('custom_addons/ai_integration/models/unified_registry.py')
approval = text('custom_addons/ai_business_tools/models/approval.py')
idem = text('custom_addons/ai_business_tools/models/idempotency.py')
scim = text('custom_addons/ai_customer_plane/controllers/scim_api.py')
cert = text('custom_addons/ai_integration/models/certification.py')

for rel in [
    'custom_addons/ai_gateway/models/execution_gate.py',
    'custom_addons/ai_integration/models/unified_registry.py',
    'custom_addons/ai_business_tools/models/approval.py',
    'custom_addons/ai_business_tools/models/idempotency.py',
    'custom_addons/ai_customer_plane/models/scim.py',
    'custom_addons/ai_customer_plane/controllers/scim_api.py',
    'custom_addons/ai_integration/models/certification.py',
]:
    ast.parse(text(rel), filename=rel)

assert 'execution_contract(tool_name)' in gate
assert 'ON CONFLICT (user_id, key) DO NOTHING RETURNING id' in idem
assert 'FOR UPDATE' in approval
assert 'approval_payload_hash' in approval
assert 'approved_args != args' in gate
assert 'ai.customer.scim.group' in scim
assert 'self._mapped_group(token, group_id)' in scim
assert "'blocked'" in cert
assert "live_runtime=False" in cert

# No business module is allowed to call the legacy risk shim directly.
for p in (ROOT / 'custom_addons').rglob('*.py'):
    s = p.read_text(errors='ignore')
    if 'ai.gateway.tool.risk' in s and '.enforce(' in s and p.name not in {'tool_risk.py'}:
        raise AssertionError(f'legacy direct risk enforcement: {p}')

print('PASS v46 static security contracts')
