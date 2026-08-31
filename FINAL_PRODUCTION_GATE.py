#!/usr/bin/env python3
"""Fail-closed static release gate for the AI Control Plane."""
from pathlib import Path
import re, sys, ast, xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parent
checks=[]
def check(name, ok, detail=""):
    checks.append((name,bool(ok),detail))

def text(rel):
    path = ROOT / rel
    return path.read_text(encoding='utf-8', errors='ignore') if path.exists() else ''

# deploy.sh is the only supported checkout entrypoint. The historical
# 01/02 installers are not fabricated merely to satisfy a source check.
install=text('deploy.sh')
check('no blanket assistant tool assignment', "all_tools = env['llm.tool'].search([])" not in install)
check('generic rpc permanently disabled', 'permanently disabled' in text('custom_addons/ai_gateway/controllers/gateway.py') and 'status=410' in text('custom_addons/ai_gateway/controllers/gateway.py'))
check('production CORS fail closed', 'AI_GATEWAY_ALLOWED_ORIGIN must be a concrete HTTPS origin in production' in text('custom_addons/ai_gateway/controllers/gateway.py'))
check('telegram code atomic consume', 'FOR UPDATE' in text('custom_addons/ai_telegram_bridge/models/telegram_link_code.py'))
check('temporary grants do not mutate group membership', 'group_id.write({"users"' not in text('custom_addons/ai_business_tools/models/access_grant.py'))
check('Excel has no secret output', not re.search(r'(?:_change_password|ai\.gateway\.api\.key.*create|service_api_key)', text('onboarding/onboard_from_excel.py'), re.I))
check('unknown Excel role blocks import', 'IMPORT BLOCKED' in text('onboarding/onboard_from_excel.py'))
check('vision is registry routed', 'ai.model.router' in text('custom_addons/company_ai_demo/models/vision_analysis.py'))
check('frontend admin is capability driven', 'capabilitySet.has("admin.console.read")' in text('frontend/src/App.jsx'))
check('model router benchmark gated', 'security_score' in text('custom_addons/ai_integration/models/model_registry.py') and 'benchmark_score desc' in text('custom_addons/ai_integration/models/model_registry.py'))
check('self contained deployment exists', (ROOT/'deploy.sh').exists() and (ROOT/'requirements.lock').exists())
check('workflow cron is recovery only', 'process_due(50)' not in text('custom_addons/ai_workflow/data/cron.xml') and 'recover_due' in text('custom_addons/ai_workflow/data/cron.xml'))
check('event bus triggers workflow processing', 'process_due(limit=max(1, len(runs)))' in text('custom_addons/ai_integration/models/event_dispatch.py'))
check('core subscriber matrix exists', (ROOT/'custom_addons/ai_integration/data/core_event_subscribers.xml').exists())
check('enterprise audit context/hash fields', 'entry_hash' in text('custom_addons/ai_business_tools/models/audit_log.py') and 'trace_id' in text('custom_addons/ai_business_tools/models/audit_log.py'))
check('customer designer plane exists', (ROOT/'custom_addons/ai_customer_plane/models/customer_designer.py').exists() and (ROOT/'custom_addons/ai_customer_plane/controllers/customer_designer_api.py').exists())
check('memory retention/deletion controls', 'erase_user' in text('custom_addons/company_ai_demo/models/memory_record.py') and 'expires_at' in text('custom_addons/company_ai_demo/models/memory_record.py'))
check('FGA project/folder dimensions', 'project_id' in text('custom_addons/ai_control_plane/models/fga.py') and 'folder_id' in text('custom_addons/ai_control_plane/models/fga.py'))

# forbidden dangerous patterns in product code
forbidden=[r'grant\.group_id\.write\(\{[\'\"]users', r'localStorage\.setItem\([^\n]*api', r'"model"\s*:\s*"vision-model"']
blob='\n'.join(x.read_text(encoding='utf-8',errors='ignore') for x in ROOT.rglob('*') if x.suffix in {'.py','.js','.jsx','.sh','.xml'})
for pat in forbidden:
    check('forbidden pattern '+pat, not re.search(pat, blob, re.I))

# syntax gates over all shipped Python/XML
for path in ROOT.rglob('*.py'):
    try: ast.parse(path.read_text(encoding='utf-8', errors='ignore'))
    except Exception as exc: check('python syntax '+str(path.relative_to(ROOT)), False, str(exc))
for path in ROOT.rglob('*.xml'):
    try: ET.parse(path)
    except Exception as exc: check('xml syntax '+str(path.relative_to(ROOT)), False, str(exc))

bad=[x for x in checks if not x[1]]
for n,ok,d in checks: print(('PASS' if ok else 'FAIL').ljust(5), n, d)
print(f"\n{len(checks)-len(bad)}/{len(checks)} static gates passed")
sys.exit(1 if bad else 0)
