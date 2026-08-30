#!/usr/bin/env python3
"""Static contract tests for the v38 central risk gateway change."""
from pathlib import Path
root=Path(__file__).resolve().parent
text=(root/'custom_addons/ai_gateway/models/execution_gate.py').read_text()
assert 'class AiGatewayExecutionGate' in text
assert 'RISK_5 tools are human-only' in text
assert 'approval_required' in text
assert 'ai_gateway_approved_execution' in text
assert 'execute_approved' in text
ctrl=(root/'custom_addons/ai_gateway/controllers/gateway.py').read_text()
assert '/api/tool/execute' in ctrl
for p in (root/'custom_addons').rglob('*.py'):
    s=p.read_text(errors='ignore')
    if '].enforce(' in s and p.name not in {'tool_risk.py'}:
        raise AssertionError(f'non-central risk enforcement: {p}')
print('PASS: risk gateway contracts')
