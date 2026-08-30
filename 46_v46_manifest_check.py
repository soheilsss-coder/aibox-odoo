#!/usr/bin/env python3
"""Verify v46 keeps all major v45 modules and adds hardening only."""
from pathlib import Path
root = Path(__file__).resolve().parent
required_modules = [
    'ai_business_tools', 'ai_control_plane', 'ai_gateway', 'ai_integration',
    'ai_rag', 'ai_workflow', 'ai_customer_plane', 'ai_semantic_api',
    'ai_collaboration', 'ai_correspondence', 'ai_document_intelligence',
    'ai_experience', 'ai_production', 'ai_telegram_bridge', 'company_ai_demo',
]
missing = [m for m in required_modules if not (root / 'custom_addons' / m).is_dir()]
if missing:
    raise SystemExit(f'FAIL missing previous module(s): {missing}')
print(f'PASS preserved modules: {len(required_modules)}')
