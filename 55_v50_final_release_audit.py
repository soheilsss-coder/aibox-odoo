#!/usr/bin/env python3
"""Final release audit: additive integrity + source-level safety + runtime gate presence."""
from __future__ import annotations
import argparse, ast, json, re, sys, zipfile
from pathlib import Path

FORBIDDEN = [
    r'\.sudo\(\)\.create\(.*mail\.activity',
]
REQUIRED = [
    '51_v48_runtime_e2e.py', '52_v48_runtime_e2e_tests.py',
    '48_auto_integration_certification.py', '54_v49_release_integrity.py',
    'custom_addons/ai_gateway/models/execution_gate.py',
    'custom_addons/ai_integration/models/unified_registry.py',
    'custom_addons/ai_rag/models/index_job.py',
    'custom_addons/ai_customer_plane/wizard/excel_role_import.py',
]

def files(root):
    return {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}

def audit(root: Path, previous: Path | None = None):
    fs=files(root); errors=[]
    for r in REQUIRED:
        if r not in fs: errors.append(f'missing required: {r}')
    for p in root.rglob('*.py'):
        try: ast.parse(p.read_text(encoding='utf-8'))
        except Exception as e: errors.append(f'python syntax: {p}: {e}')
    wf=root/'custom_addons/ai_workflow/models/workflow.py'
    if wf.exists():
        s=wf.read_text()
        if 'mail.activity' in s and '.sudo().create({' in s:
            errors.append('workflow contains direct sudo mail.activity creation')
    if previous:
        old=files(previous); missing=sorted(old-fs)
        if missing: errors.append('deleted files: '+', '.join(missing))
    result={'ok':not errors,'file_count':len(fs),'missing_from_previous':0,'errors':errors}
    if previous: result['missing_from_previous']=len(files(previous)-fs)
    print(json.dumps(result,indent=2))
    return 0 if not errors else 2

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('root',nargs='?',default='.')
    ap.add_argument('--previous'); a=ap.parse_args()
    raise SystemExit(audit(Path(a.root).resolve(), Path(a.previous).resolve() if a.previous else None))
