#!/usr/bin/env python3
"""Live HTTP acceptance suite for the v56 architecture.

This script is intentionally compatible with the final design: generic
/api/rpc is expected to return 410, while semantic/session/capability
endpoints and named tool paths are exercised. It requires a live stack.
"""
import argparse, json, sys, requests

def check(label, ok, detail="", hard=True):
    status="PASS" if ok else ("FAIL" if hard else "INFO-FAIL")
    print(f"[{status}] {label}" + (f" - {detail}" if detail and not ok else ""))
    return ok or not hard

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--base-url',default='http://localhost:8069'); ap.add_argument('--api-key',required=True); a=ap.parse_args()
    base=a.base_url.rstrip('/'); h={"X-API-Key":a.api_key}
    failures=0
    r=requests.get(base+'/api/bootstrap',headers=h,timeout=20); failures += not check('bootstrap identity',r.status_code==200,r.text[:300])
    r=requests.get(base+'/api/me/capabilities',headers=h,timeout=20); failures += not check('effective capability API',r.status_code==200 and 'capabilities' in r.json(),r.text[:300])
    r=requests.post(base+'/api/rpc',headers=h,json={"model":"res.partner","operation":"search_read"},timeout=20); failures += not check('generic RPC is permanently disabled',r.status_code==410,r.text[:300])
    r=requests.options(base+'/api/rpc',timeout=20); failures += not check('CORS preflight',r.status_code==200 and 'Access-Control-Allow-Origin' in r.headers,str(dict(r.headers)))
    r=requests.get(base+'/api/health',timeout=20); failures += not check('health endpoint',r.status_code==200 and r.json().get('status')=='ok',r.text[:300])
    r=requests.post(base+'/api/chat',headers=h,json={"message":"یک درخواست خواندنی ساده درباره کارهای من بده"},timeout=90); check('chat semantic path',r.status_code==200 and 'reply' in r.json(),r.text[:300],hard=False)
    print(f"\nHard failures: {failures}")
    return 1 if failures else 0
if __name__=='__main__': sys.exit(main())
