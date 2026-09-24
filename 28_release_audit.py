#!/usr/bin/env python3
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent
checks = {}

def text(p): return (ROOT / p).read_text(encoding='utf-8')
checks['universal integration addon exists'] = (ROOT/'custom_addons/ai_integration/__manifest__.py').exists()
checks['installer installs integration addon'] = 'ai_integration' in text('02_install_modules.sh')
checks['generic assistant assignment absent'] = "all_tools = env['llm.tool'].search([])" not in text('02_install_modules.sh')
checks['generic rpc permanently disabled'] = 'permanently disabled' in text('custom_addons/ai_gateway/controllers/gateway.py') and 'status=410' in text('custom_addons/ai_gateway/controllers/gateway.py')
checks['browser login does not return api key'] = '"api_key": key_rec.key' not in text('custom_addons/ai_semantic_api/controllers/semantic_api.py')
checks['session cookie is httponly'] = 'httponly=True' in text('custom_addons/ai_semantic_api/controllers/semantic_api.py')
checks['memory is ORM based'] = 'class AiAgentMemoryRecord' in text('custom_addons/company_ai_demo/models/memory_record.py')
checks['rag indexing is queued'] = 'ai.document.index.job' in text('custom_addons/ai_rag/models/rag_index.py')
checks['approval integrity hash'] = 'approval_hash' in text('custom_addons/ai_business_tools/models/approval.py')
checks['temporary role whitelist'] = 'Only product-defined role groups' in text('custom_addons/ai_business_tools/models/access_grant.py')
checks['unknown excel roles block import'] = 'Import is blocked' in text('onboarding/onboard_from_excel.py')
checks['hermes has no raw rpc tool'] = 'def gateway_rpc' not in text('buzz_bridge/hermes_gateway_mcp_server.py')
checks['release docs present'] = (ROOT/'RELEASE_V33.md').exists() and (ROOT/'ARCHITECTURE_V33.md').exists()
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(('PASS' if v else 'FAIL')+' - '+k)
print('\nRESULT:', 'PASS' if not failed else 'FAIL')
raise SystemExit(1 if failed else 0)
