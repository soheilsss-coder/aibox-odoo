#!/usr/bin/env python3
from pathlib import Path
root=Path(__file__).resolve().parent
required=[
 "custom_addons/ai_gateway/models/execution_gate.py",
 "custom_addons/ai_gateway/controllers/gateway.py",
]
missing=[p for p in required if not (root/p).exists()]
if missing:
 print("FAIL", missing); raise SystemExit(1)
for p in (root / "custom_addons").rglob("*.py"):
 s=p.read_text(errors="ignore")
 if 'ai.gateway.tool.risk"].enforce(' in s and p.name != '32_risk_gateway_audit.py':
  print("FAIL direct risk enforcement:",p); raise SystemExit(2)
print("PASS: central execution gate is the only risk entrypoint")
