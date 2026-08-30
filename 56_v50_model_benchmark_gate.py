#!/usr/bin/env python3
"""Deterministic model promotion gate. No candidate becomes production by registration alone."""
from __future__ import annotations
import argparse, json, statistics
from pathlib import Path

REQUIRED=['reasoning','tool_calling','rag','security','vision','latency']

def evaluate(payload):
    scores=payload.get('scores',{})
    missing=[k for k in REQUIRED if k not in scores]
    if missing: return {'eligible':False,'reason':'missing:'+','.join(missing)}
    vals=[float(scores[k]) for k in REQUIRED]
    threshold=float(payload.get('threshold',0.80))
    latency=float(scores['latency'])
    max_latency=float(payload.get('max_latency_ms',2000))
    eligible=min(vals)>=threshold and latency<=max_latency and bool(payload.get('security_pass'))
    return {'eligible':eligible,'minimum_score':min(vals),'mean_score':statistics.mean(vals),'latency_ms':latency,'threshold':threshold,'max_latency_ms':max_latency}

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('input',type=Path); ap.add_argument('--output',type=Path)
    a=ap.parse_args(); data=json.loads(a.input.read_text()); out=evaluate(data)
    if a.output: a.output.write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps(out,indent=2)); raise SystemExit(0 if out['eligible'] else 2)
