#!/usr/bin/env python3
"""Fail-closed final production promotion gate."""
from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('report',type=Path); a=ap.parse_args()
    data=json.loads(a.report.read_text())
    failures=[]
    for module in data.get('modules',[]):
        if module.get('state')!='PASS': failures.append(module.get('name','unknown'))
        for gate in module.get('gates',[]):
            if gate.get('status')!='PASS': failures.append(f"{module.get('name','unknown')}:{gate.get('name','unknown')}")
    runtime=data.get('runtime',{})
    required_runtime=['postgres','odoo','redis','vector_store','llm_gateway']
    for key in required_runtime:
        if runtime.get(key)!='PASS': failures.append('runtime:'+key)
    out={'production_eligible':not failures,'failures':failures}
    print(json.dumps(out,indent=2))
    return 0 if not failures else 2

if __name__=='__main__': raise SystemExit(main())
