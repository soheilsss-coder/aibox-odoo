from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parent
checks={}
def read(rel): return (ROOT/rel).read_text(encoding='utf-8')
checks['v47 certification runner exists']=(ROOT/'48_auto_integration_certification.py').exists()
checks['certification is fail closed']="PRODUCTION BLOCKED" in read('48_auto_integration_certification.py')
checks['runtime certification explicitly enabled']="live_runtime=True" in read('48_auto_integration_certification.py')
checks['promotion requires PASS']="latest.status == 'pass'" in read('custom_addons/ai_integration/models/certification.py')
checks['workflow uses central gate']="ai.gateway.execution.gate" in read('custom_addons/ai_workflow/models/workflow.py')
checks['unified registry contract enforced']="execution_contract" in read('custom_addons/ai_integration/models/unified_registry.py')
checks['idempotency has atomic claim']="ON CONFLICT" in read('custom_addons/ai_business_tools/models/idempotency.py')
checks['rpc remains disabled by default']='permanently disabled' in read('custom_addons/ai_gateway/controllers/gateway.py') and 'status=410' in read('custom_addons/ai_gateway/controllers/gateway.py')
checks['rag async job remains present']=any('ai.document.index.job' in p.read_text(encoding='utf-8',errors='ignore') for p in (ROOT/'custom_addons').rglob('*.py'))
checks['v46 docs preserved']=(ROOT/'V46_CERTIFICATION_AND_RUNTIME_HARDENING.md').exists()
for p in (ROOT/'custom_addons').rglob('*.py'):
    try: ast.parse(p.read_text(encoding='utf-8'))
    except Exception as e: checks['syntax:'+str(p.relative_to(ROOT))]=False
for k,v in checks.items(): print(('PASS' if v else 'FAIL')+' - '+k)
raise SystemExit(0 if all(checks.values()) else 1)
