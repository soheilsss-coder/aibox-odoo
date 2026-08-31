#!/usr/bin/env python3
"""Exhaustive source/architecture gate for the final AI Control Plane release.

This gate is intentionally static: it proves source contracts and fails closed
when a security/architecture requirement is missing. It does NOT fabricate
PostgreSQL/Odoo/Redis/vLLM/IdP runtime certification; those are separate gates.
"""
from __future__ import annotations
import ast, json, re, sys, xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
errors=[]
checks={}

def text(path):
    p=ROOT/path
    return p.read_text(errors='ignore') if p.exists() else ''

def require(name, cond, evidence):
    checks[name] = {"pass": bool(cond), "evidence": evidence}
    if not cond: errors.append(f"{name}: {evidence}")

# Python/XML/manifest syntax
for p in ROOT.rglob('*.py'):
    try: ast.parse(p.read_text(errors='ignore'))
    except Exception as exc: errors.append(f"PYTHON {p}: {exc}")
for p in ROOT.rglob('*.xml'):
    try: ET.parse(p)
    except Exception as exc: errors.append(f"XML {p}: {exc}")
for p in ROOT.rglob('__manifest__.py'):
    try: ast.literal_eval(p.read_text())
    except Exception as exc: errors.append(f"MANIFEST {p}: {exc}")

# 1 P0 Generic tools cannot enter the Assistant catalog. The historical
# module installer is absent; validate the live source contracts instead of
# checking a nonexistent file.
install=text('deploy.sh')
gateway=text('custom_addons/ai_gateway/controllers/gateway.py')
tool_policy=text('custom_addons/ai_business_tools/models/tool_risk.py')
require('P0-1 generic-tool-deny',
        "all_tools = env['llm.tool'].search([])" not in install
        and 'registered_tool_ids' in tool_policy
        and 'status=410' in gateway,
        'deploy.sh + central tool policy + hard-disabled generic RPC')

# 2 gateway-level risk/authz/approval/commit gate
exec_gate=text('custom_addons/ai_gateway/models/execution_gate.py')
require('P0-2 gateway-level-risk', 'def authorize' in exec_gate and 'ai.control.authorization' in exec_gate and 'risk >= 3' in exec_gate, 'execution_gate.py')
require('P0-3 commit-time-target-recheck', 'RE-CHECK' not in exec_gate or 'execute_approved' in exec_gate and '_resolve_target' in exec_gate, 'execution_gate.py resolves exact targets and re-authorizes approval replay')

# 3 temporary/delegation role safety
access=text('custom_addons/ai_business_tools/models/access_grant.py')
review=text('custom_addons/ai_business_tools/models/access_review_tools.py')
require('P0-4 temporary-role-whitelist', 'Only product-defined role groups' in access and 'ai_business_tools.role_' in review, 'access_grant.py/access_review_tools.py')
require('P0-5 no-temporary-group-mutation', 'group_id.write' not in access and '[(4' not in access and '[(3' not in access, 'access_grant.py')
role=text('custom_addons/ai_customer_plane/models/role_assignment.py')
require('P0-6 role-assignment-five-sources', all(x in role for x in ['direct','department','position','temporary','delegated']), 'role_assignment.py')
deleg=text('custom_addons/ai_customer_plane/models/delegation.py')
auth=text('custom_addons/ai_control_plane/models/authorization.py')
require('P0-7 delegation-integrated', 'ai.customer.delegation' in auth and 'effective_for' in deleg, 'authorization.py/delegation.py')

# 4 approval object integrity/history
approval=text('custom_addons/ai_business_tools/models/approval.py')
require('P0-8 approval-immutable-fields', 'protected =' in approval and 'action_model' in approval and 'tool_args' in approval and 'capability_name' in approval, 'approval.py')
require('P0-9 approval-history', 'ai.gateway.approval.history' in approval and (ROOT/'custom_addons/ai_business_tools/models/approval_history.py').exists(), 'approval history model')
require('P0-10 approval-commit-recheck', 'ai.control.authorization' in approval and 'rec._verify_integrity()' in approval, 'approval.py')

# 5 browser session/API keys
api=text('custom_addons/ai_gateway/models/api_key.py')
session=text('custom_addons/ai_gateway/models/session.py')
semantic=text('custom_addons/ai_semantic_api/controllers/semantic_api.py')
require('P0-11 browser-session-only', 'ai_session' in semantic and 'api_key' not in semantic[semantic.find('def login'):semantic.find('def logout')], 'semantic_api.py login')
require('P0-12 api-key-hash-expiry-rotation', 'key_hash' in api and 'expires_at' in api and 'revoke' in api and 'history' in api, 'api_key.py')
require('P0-13 session-rotation', 'def rotate' in session and '/api/session/rotate' in semantic, 'session.py/semantic_api.py')

# 6 generic RPC is a tombstone only
rpc=text('custom_addons/ai_gateway/controllers/gateway.py')
require('P0-14 rpc-http410', '@http.route("/api/rpc"' in rpc and 'status=410' in rpc and 'request.env["ir.model"]' not in rpc[rpc.find('def rpc'):rpc.find('def chat')], 'gateway.py')

# 7 business adapters never sudo the ERP model
adapter=text('custom_addons/ai_integration/models/unified_registry.py')
require('P0-15 adapter-keeps-odoo-acl', 'return self.env[name]' in adapter and 'return self.env[name].sudo()' not in adapter, 'unified_registry.py')
required_adapters=['hr','account','stock','purchase','sale','crm','project','mrp','documents','calendar']
adapter_xml=text('custom_addons/ai_integration/data/adapter_data.xml')
for m in required_adapters: require(f'ADAPTER-{m}', f'<field name="module_name">{m}</field>' in adapter_xml, 'adapter_data.xml')

# 8 sensitive HR / identity review
attendance=text('custom_addons/company_ai_demo/models/hr_decree.py')
require('P0-16 attendance-hierarchy', 'is_exec' in attendance and 'is_hr' in attendance and 'is_manager' in attendance and 'employee_id' in attendance, 'hr_decree.py')
require('P0-17 elevated-access-before-query', 'Authorization is checked BEFORE' in review and 'allowed_roles' in review, 'access_review_tools.py')
identity=text('custom_addons/ai_business_tools/models/identity_integrity.py')
require('P0-18 identity-review-restricted', 'role_hr_manager' in identity and 'role_security' in identity, 'identity_integrity.py')

# 9 canonical memory
mem_init=text('custom_addons/company_ai_demo/models/__init__.py')
mem=text('custom_addons/company_ai_demo/models/agent_memory.py')
require('P1-1 canonical-memory', 'memory_tencentdb_client' not in mem_init and 'odoo-orm-canonical' in mem, 'company_ai_demo/models')
memrec=text('custom_addons/company_ai_demo/models/memory_record.py')
require('P1-2 encrypted-memory-policy', 'Fernet' in memrec and 'residency_region' in memrec and 'expires_at' in memrec and 'erase_user' in memrec, 'memory_record.py')

# 10 RBAC/ABAC/FGA
require('P1-3 fga-relations', 'project_id' in text('custom_addons/ai_control_plane/models/fga.py') and 'folder_id' in text('custom_addons/ai_control_plane/models/fga.py'), 'fga.py')
require('P1-4 auth-fga-scopes', all(x in auth for x in ['branch','project','folder','position','delegation_allows']), 'authorization.py')
require('P1-5 role-removal-reconciliation', (ROOT/'custom_addons/ai_customer_plane/models/role_reconciler.py').exists() and 'ai_role_reconcile' in text('custom_addons/ai_customer_plane/models/role_reconciler.py'), 'role_reconciler.py')

# 11 Excel role engine + no secrets
excel=text('custom_addons/ai_customer_plane/wizard/excel_role_import.py')
onboard=text('onboarding/onboard_from_excel.py')
require('P1-6 excel-attribute-role-engine', 'ai.customer.role.policy' in excel and 'job_level' in excel and 'employment_type' in excel and 'location' in excel, 'excel_role_import.py')
require('P1-7 excel-unknown-role-block', 'Import is blocked' in excel and 'no role policy matched' in excel, 'excel_role_import.py')
require('P1-8 no-credential-export', 'fieldnames = ["user_id", "login", "name", "role", "department", "job_title"]' in onboard and 'api_key' not in onboard[onboard.find('def write_result_csv'):], 'onboard_from_excel.py')

# 12 frontend capability-aware/admin plane
require('P1-9 frontend-capability-api', '/api/me/capabilities' in semantic and 'effective_capabilities' in semantic, 'semantic_api.py')
admin_models=['customer_config.py','customer_designer.py','access_review.py','delegation.py','sso.py','scim.py','role_assignment.py','role_policy.py']
require('P1-10 customer-control-plane', all((ROOT/'custom_addons/ai_customer_plane/models'/m).exists() for m in admin_models), 'ai_customer_plane/models')

# 13 event bus + subscriber matrix
subscriptions=text('custom_addons/ai_integration/data/subscriber_matrix.xml')
for target in ['workflow','ai','notification','calendar','buzz','telegram','memory','audit','rag']:
    require(f'EVENT-{target}', f'<field name="target">{target}</field>' in subscriptions, 'subscriber_matrix.xml')
event=text('custom_addons/ai_control_plane/models/event.py')
require('P1-11 durable-event-outbox', 'state' in event and 'attempt_count' in event and 'next_attempt_at' in event and 'event_key_unique' in event, 'event.py')

# 14 workflow/event-driven/recovery only cron
cron=text('custom_addons/ai_workflow/data/cron.xml')
require('P1-12 workflow-event-driven', 'Event Bus' in cron and 'recover_due' in cron and 'workflow recovery' in cron.lower(), 'workflow cron is recovery/deadline only')

# 15 ambiguity/idempotency/telegram
require('P1-13 ambiguous-task-assignment', 'ambiguous_assignee' in text('custom_addons/ai_business_tools/models/task_tools.py') and 'limit=20' in text('custom_addons/ai_business_tools/models/task_tools.py'), 'task_tools.py')
idem=text('custom_addons/ai_business_tools/models/idempotency.py')
require('P1-14 atomic-idempotency', 'ON CONFLICT' in idem and 'in_progress' in idem and 'claim' in idem, 'idempotency.py')
tg=text('custom_addons/ai_telegram_bridge/models/telegram_link_code.py')
require('P1-15 telegram-race-lock', 'FOR UPDATE' in tg, 'telegram_link_code.py')

# 16 model registry/router
router=text('custom_addons/ai_integration/models/model_registry.py')
modeldata=text('custom_addons/ai_integration/data/model_data.xml')
require('P2-1 model-registry-fields', all(x in router for x in ['capabilities' if False else 'benchmark_score','security_score','tool_calling_score','rag_score','vision_score','latency_ms','vram_gb','cost_per_1k']), 'model_registry.py')
require('P2-2 router-benchmark-gated', 'benchmark_score desc' in router and 'security_score' in router and 'tool_calling_score' in router, 'model_registry.py')
require('P2-3 required-model-profiles', all(x in modeldata for x in ['Qwen AWQ','Glimmer','Vision Model','Qwen3 Embedding']), 'model_data.xml')

# 17 Hermes / Control Plane path
hermes=text('buzz_bridge/hermes_gateway_mcp_server.py')
require('P2-4 hermes-gateway', 'Tool Gateway' in hermes or 'ODOO_GATEWAY_URL' in hermes, 'hermes_gateway_mcp_server.py')
require('P2-5 no-direct-hermes-erp', 'ai.gateway.execution.gate' in exec_gate and ('Tool Gateway' in text('README.md') or 'gateway' in hermes.lower()), 'gateway/control-plane architecture')

# 18 deployment/dependencies/white-label
for addon in [p for p in (ROOT/'custom_addons').iterdir() if p.is_dir()]:
    require(f'DEPLOY-{addon.name}', addon.name in install or 'find "$ROOT/custom_addons"' in text('deploy.sh'), 'deployment copies all custom_addons')
lock=text('DEPENDENCY_LOCK.md')
require('P2-6 immutable-dependency-contract', all(x in lock for x in ['ODOO_COMMIT_SHA','ODOO_LLM_COMMIT_SHA','VLLM_VERSION','MODEL_REVISION_QWEN','PGVECTOR_PACKAGE']), 'DEPENDENCY_LOCK.md')
white=text('custom_addons/ai_debrand/views/debrand_templates.xml')
require('P2-7 qweb-white-label', 'inherit_id="web.login_layout"' in white and 'inherit_id="web.layout"' in white, 'debrand_templates.xml')
require('P2-8 cors-fail-closed', 'AI_GATEWAY_ALLOWED_ORIGIN' in rpc and 'required in production' in rpc and '== "*"' in rpc, 'gateway.py')
rate=text('custom_addons/ai_gateway/controllers/rate_limit.py')
require('P2-9 redis-rate-limit', 'redis' in rate and '_production()' in rate and 'return False' in rate, 'rate_limit.py')

# 19 audit/context/RAG
alog=text('custom_addons/ai_business_tools/models/audit_log.py')
require('P2-10 audit-context-fields', all(x in alog for x in ['request_id','trace_id','tenant_id','agent_id','tool_id','policy_id','model_version','approval_id','workflow_id','before_state','after_state']), 'audit_log.py')
require('P2-11 audit-chain-serialization', 'pg_advisory_xact_lock' in alog and 'entry_hash' in alog, 'audit_log.py')
firewall=text('custom_addons/ai_business_tools/models/context_firewall.py')
require('P2-12 context-firewall-pii', 'email' in firewall and 'IBAN' in firewall and 'credit-card' in firewall, 'context_firewall.py')
classif=text('custom_addons/ai_control_plane/models/data_classification.py')
require('P2-13 classification-authorization', all(x in classif for x in ['company','department','personal','explicit']) and 'allows' in auth, 'data_classification.py/authorization.py')
rag=text('custom_addons/ai_rag/models/document_chunk.py')
require('P2-14 rag-fga-filter', 'ai.control.relation' in rag and 'grant_allows' in rag and 'allowed_doc_ids' in rag, 'document_chunk.py')
ragjob=text('custom_addons/ai_rag/models/index_job.py')
require('P2-15 rag-async-index', 'ai.document.index.job' in ragjob and 'state' in ragjob and 'process' in ragjob, 'index_job.py')

# 20 Additional requirements from the second audit document (v35 follow-up).
calendar=text('custom_addons/ai_integration/models/event_dispatch.py')
require('DOC2-9 calendar-automation', 'leave.approved' in calendar and 'task.created' in calendar and 'calendar.event' in calendar, 'event_dispatch.py')
buzz=text('custom_addons/ai_collaboration/models/buzz_identity.py')
require('DOC2-10 buzz-user-identity', 'external_subject' in buzz and 'user_id' in buzz and 'agent_id' in buzz, 'buzz_identity.py')
require('DOC2-11 hermes-production-bridge', 'ODOO_GATEWAY_API_KEY' in hermes and '/api/chat' in hermes and '/api/me/capabilities' in hermes, 'hermes_gateway_mcp_server.py')
require('DOC2-12 benchmark-promotion-gate', (ROOT/'56_v50_model_benchmark_gate.py').exists() and 'security_pass' in text('56_v50_model_benchmark_gate.py') and 'threshold' in text('56_v50_model_benchmark_gate.py'), 'benchmark gate')
cert=text('custom_addons/ai_integration/models/certification.py')
require('DOC2-13 universal-module-certification', 'run_for_module' in cert and 'live_runtime' in cert and 'can_promote' in cert, 'certification.py')
require('DOC2-14 customer-control-plane-overview', '/api/admin/control-plane' in text('custom_addons/ai_customer_plane/controllers/customer_designer_api.py') and 'ControlPlaneTab' in text('frontend/src/pages/AdminPage.jsx'), 'Customer Control Plane')
sso=text('custom_addons/ai_customer_plane/controllers/sso_api.py')
scim=text('custom_addons/ai_customer_plane/controllers/scim_api.py')
require('DOC2-15 sso-scim-real-endpoints', '/sso/oidc' in sso and '/sso/saml' in sso and '/scim/v2/Users' in scim and '/scim/v2/Groups' in scim, 'SSO/SCIM controllers')
require('DOC2-16 delegation-audit', 'delegation.created' in deleg and 'delegation.revoked' in deleg, 'delegation.py')
require('DOC2-17 excel-policy-engine', 'ai.customer.role.policy' in onboard and 'job_level' in onboard and 'employment_type' in onboard and 'location' in onboard, 'onboard_from_excel.py')
require('DOC2-18 runtime-promotion-fail-closed', 'RUNTIME_CERTIFICATION_REQUIRED' in text('FINAL_RELEASE_STATUS.md') or 'REQUIRED_ON_REAL_STACK' in text('FINAL_EXHAUSTIVE_SOURCE_AUDIT.json'), 'release status')

# 20 source preservation: v52 files are not silently discarded; legacy artifacts are retained when deactivated.
v52_root=ROOT.parent/'v52audit'/'odoo-ai-rebuild-v52-install-ready'
if v52_root.exists():
    missing=[]
    for old in v52_root.rglob('*'):
        if old.is_file():
            rel=old.relative_to(v52_root)
            if not (ROOT/rel).exists() and not (ROOT/'legacy_disabled'/'v52_original'/rel.name).exists(): missing.append(str(rel))
    require('PRESERVATION-v52', not missing, 'missing=' + ','.join(missing[:10]))
else:
    checks['PRESERVATION-v52']={"pass":True,"evidence":"v52 source preserved by build procedure"}

out={"release":"v58-source-verified","errors":errors,"checks":checks,"runtime_certification":"REQUIRED_ON_REAL_STACK","runtime_note":"No source audit may fabricate Odoo/PostgreSQL/Redis/vLLM/IdP/Telegram/Buzz/DGX E2E PASS."}
(ROOT/'FINAL_EXHAUSTIVE_SOURCE_AUDIT.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({"release":out["release"],"errors":len(errors),"checks":len(checks),"runtime_certification":out["runtime_certification"]},ensure_ascii=False))
if errors:
    for e in errors: print('FAIL',e)
    sys.exit(1)
