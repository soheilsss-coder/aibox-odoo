#!/usr/bin/env python3
import ast, json, os, re, subprocess, sys, xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parent
errors=[]; warnings=[]
def req(cond,msg):
    if not cond: errors.append(msg)
def read(rel): return (ROOT/rel).read_text(encoding='utf-8')

def _sh_path(p):
    s = os.fspath(p)
    if os.name != "nt":
        return s
    drive, rest = os.path.splitdrive(s)
    drive = (drive or "C").rstrip(":").lower()
    return "/mnt/" + drive + "/" + rest.replace("\\", "/").lstrip("/")
# 1. Parse every source artifact.
for p in ROOT.rglob('*'):
    if p.is_dir() and p.name=='__pycache__': errors.append(f'compiled artifact directory: {p}')
    if p.is_file() and p.suffix=='.py' and '__pycache__' not in p.parts:
        try: ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
        except Exception as e: errors.append(f'python syntax: {p}: {e}')
    if p.is_file() and p.suffix=='.xml':
        try: ET.parse(p)
        except Exception as e: errors.append(f'xml syntax: {p}: {e}')
    if p.is_file() and p.suffix=='.json':
        try: json.loads(p.read_text(encoding='utf-8'))
        except Exception as e: errors.append(f'json syntax: {p}: {e}')
for p in (ROOT/'custom_addons').glob('*/__manifest__.py'):
    try:
        d=ast.literal_eval(p.read_text(encoding='utf-8')); req(isinstance(d,dict),'invalid manifest: '+str(p))
    except Exception as e: errors.append(f'manifest syntax: {p}: {e}')
# 2. Duplicate top-level classes.
for p in ROOT.rglob('*.py'):
    if '__pycache__' in p.parts: continue
    try: tree=ast.parse(p.read_text(encoding='utf-8'))
    except: continue
    names={}
    for n in tree.body:
        if isinstance(n,ast.ClassDef): names[n.name]=names.get(n.name,0)+1
    for n,c in names.items():
        if c>1: errors.append(f'duplicate top-level class {n}: {p}')
# 3. Credentials and generic RPC.
gw=read('custom_addons/ai_gateway/controllers/gateway.py')
# NOTE: the current implementation intentionally has NO feature flag -
# /api/rpc is a permanent tombstone with a hard-coded 410, not something
# toggled by a variable. So the check here is (a) no such flag exists,
# and (b) the hard-410 tombstone with its "permanently disabled" message
# is actually present - not a check for a specific flag name/value.
req('_ENABLE_RPC' not in gw,'generic RPC still has a feature-flag toggle instead of being permanently disabled in code')
req('status=410' in gw,'generic RPC endpoint is not hard-410')
req('permanently disabled' in gw,'generic RPC tombstone message missing')
req('api_key=\n' not in gw,'malformed credential code marker')
req('?api_key=' not in gw and '?api_key=' not in read('README.md'),'query-string API credentials remain documented or implemented')
api=read('custom_addons/ai_gateway/models/api_key.py')
req(re.search(r'^\s*key\s*=\s*fields\.',api,re.M) is None,'plaintext API-key field remains')
on=read('onboarding/onboard_from_excel.py'); shell=read('15_customer_onboarding.sh')
for phrase in ('_change_password(', 'api.gateway.api.key'):
    req(phrase not in on,f'Excel onboarding still creates credential material: {phrase}')
for phrase in ('onboarding_result.csv','logins/passwords/API keys','Hand /opt/onboarding_result.csv'):
    req(phrase not in shell,f'onboarding credential export remnant: {phrase}')
# 4. Central role assignment + auth.
req((ROOT/'custom_addons/ai_customer_plane/models/role_assignment.py').exists(),'central role assignment model missing')
role=read('custom_addons/ai_customer_plane/models/role_assignment.py')
for src in ('direct','department','position','temporary','delegated'): req(f'("{src}"' in role,f'role source missing: {src}')
auth=read('custom_addons/ai_control_plane/models/authorization.py')
req('def check_capability' in auth,'check_capability missing from central authorization')
req('role.assignment' in auth,'role assignment not consumed by authorization')
req('data.classification' in auth,'data classification not consumed by authorization')
# 5. Data classification/context firewall.
req((ROOT/'custom_addons/ai_control_plane/models/data_classification.py').exists(),'data classification engine missing')
fire=read('custom_addons/ai_business_tools/models/context_firewall.py')
for k in ('password','api_key','pii','iban','credit_card'): req(k in fire,f'context firewall missing key: {k}')
# 6. FGA dimensions.
fga=read('custom_addons/ai_control_plane/models/fga.py')
for x in ('project_id','folder_id','expires_at','delegate'): req(x in fga,f'FGA dimension missing: {x}')
# 7. Explicit subscriber matrix.
subs=read('custom_addons/ai_integration/models/event_subscribers.py')
for name in ['ai.integration.workflow.subscriber','ai.integration.audit.subscriber','ai.integration.notification.subscriber','ai.integration.buzz.subscriber','ai.integration.telegram.subscriber','ai.integration.memory.subscriber','ai.integration.rag.subscriber','ai.integration.calendar.subscriber','ai.integration.ai.subscriber']:
    req(f'_name = "{name}"' in subs,f'missing subscriber: {name}')
req('subscriber_matrix.xml' in read('custom_addons/ai_integration/__manifest__.py'),'subscriber matrix not installed')
# 8. Cron restriction.
allowed=('cleanup','overdue','escalate','expire','recover','deadline')
for p in ROOT.rglob('*.xml'):
    txt=p.read_text(encoding='utf-8')
    if 'model="ir.cron"' in txt:
        for m in re.findall(r'<field name="code">\s*([^<]+)',txt):
            if m.strip() and not any(k in m.lower() for k in allowed): errors.append(f'non-maintenance cron remains: {p}: {m.strip()}')
req((ROOT/'runtime_workers/run_event_worker.sh').exists(),'event worker missing')
req((ROOT/'runtime_workers/run_rag_worker.sh').exists(),'RAG worker missing')
# 9. Memory contract.
mem=read('custom_addons/company_ai_demo/models/memory_record.py'); tool=read('custom_addons/company_ai_demo/models/agent_memory.py')
for x in ('Fernet','expires_at','residency_region','erase_user'): req(x in mem,f'memory control missing: {x}')
req('odoo-orm-canonical' in tool,'memory provider is not canonical ORM service')
# 10. SSO/SCIM.
req((ROOT/'custom_addons/ai_customer_plane/controllers/sso_api.py').exists(),'SSO runtime controller missing')
sso=read('custom_addons/ai_customer_plane/controllers/sso_api.py')
for x in ('oidc/start','oidc/callback','saml/acs','JsonWebKey','claims.validate'): req(x in sso,f'SSO contract missing: {x}')
scim=read('custom_addons/ai_customer_plane/controllers/scim_api.py'); req('/scim/v2/Users' in scim and '/scim/v2/Groups' in scim,'SCIM endpoints incomplete')
# 11. Customer control plane.
cd=read('custom_addons/ai_customer_plane/models/customer_designer.py')
for k in ('role','permission','policy','workflow','approval_matrix','document_policy','agent','tool','configuration_profile','deployment'): req(k in cd,f'customer designer kind missing: {k}')
# 12. Adapter gate bypass regression.
uni=read('custom_addons/ai_integration/models/unified_registry.py'); req('ai_gateway_gate_checked' not in uni,'adapter still trusts forgeable gate-bypass context')
# 13. Approval context hardening.
gate=read('custom_addons/ai_gateway/models/execution_gate.py'); req('approval_action' in gate and 'decided_by_id' in gate,'approval replay is not bound to internal approval executor')
# 14. Static shell syntax.
for p in ROOT.rglob('*.sh'):
    r=subprocess.run(['bash','-n',_sh_path(p)],capture_output=True,text=True)
    if r.returncode: errors.append(f'shell syntax: {p}: {r.stderr.strip()}')
# 15. No obvious default secrets.
alltxt=[]
for p in ROOT.rglob('*'):
    if p.is_file() and p.name != 'FINAL_SOURCE_AUDIT.py' and p.suffix in ('.py','.sh','.md','.xml','.js','.jsx'):
        try: alltxt.append(p.read_text(encoding='utf-8'))
        except: pass
blob='\n'.join(alltxt)
for secret in ('Demo12345!','password123','changeme','sk-live-'):
    req(secret not in blob,f'hard-coded secret/default credential remains: {secret}')
# 16. Preserve v50 source paths.
v50=Path('/tmp/v50/odoo-ai-rebuild-v50-final-candidate')
if v50.exists():
    old={p.relative_to(v50).as_posix() for p in v50.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    new={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    missing=sorted(old-new)
    if missing: errors.append('paths removed from v50: '+', '.join(missing[:50]))
# 17. Source package is never allowed to call itself runtime certified.
for rel in ['FINAL_RELEASE_STATUS.md','INSTALL_READY.md','ROADMAP_FINAL_MATRIX.md']:
    t=read(rel)
    if 'PRODUCTION CERTIFIED' in t and 'NOT_RUN' not in t: warnings.append(f'document may overstate runtime certification: {rel}')
result={'source_audit_pass':not errors,'errors':errors,'warnings':warnings,'runtime_certification':'NOT_RUN','release_base':'v52-install-ready','source_preservation_checked_against':'v50-final-candidate'}
print(json.dumps(result,ensure_ascii=False,indent=2)); sys.exit(0 if not errors else 2)
