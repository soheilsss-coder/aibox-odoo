#!/usr/bin/env python3
"""Offline release gate for the model/evaluation pipeline.
Reads JSON evaluation reports and only emits PROMOTE when all mandatory suites pass.
"""
import json, sys
from pathlib import Path

MANDATORY = ("security", "tool_calling", "role", "rag", "vision", "latency")

def main(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    suites = data.get("suites", {})
    missing = [x for x in MANDATORY if x not in suites]
    failed = [x for x in MANDATORY if suites.get(x) not in (True, "PASS", "pass")]
    if missing or failed:
        print(json.dumps({"decision":"BLOCK","missing":missing,"failed":failed}, ensure_ascii=False))
        return 2
    print(json.dumps({"decision":"PROMOTE","model":data.get("model"),"version":data.get("version")}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
