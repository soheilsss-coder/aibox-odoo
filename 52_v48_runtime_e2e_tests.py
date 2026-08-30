"""Static tests for the v48 runtime E2E harness."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent
p = ROOT / '51_v48_runtime_e2e.py'
text = p.read_text(encoding='utf-8')
checks = {
    'live harness exists': p.exists(),
    'fail closed': "return 0 if passed else 1" in text,
    'unknown tool denial': 'gateway_unknown_tool_denied' in text,
    'unified registry': 'execution_contract' in text,
    'event probe': 'event_outbox_publish' in text,
    'rag contract': 'rag_pipeline_contract' in text,
    'mutation opt-in': "AI_V48_ALLOW_BUSINESS_MUTATIONS" in text,
}
for name, ok in checks.items():
    print('[%s] %s' % ('PASS' if ok else 'FAIL', name))
    if not ok:
        raise SystemExit(1)
ast.parse(text)
print('PASS - v48 runtime harness static suite')
