"""Offline structural E2E contract suite for v35.
It validates that the release contains the required integration contracts.
Live Odoo/PostgreSQL/vLLM/Buzz/Telegram execution is intentionally not faked.
"""
from pathlib import Path
import ast, json, zipfile, subprocess, sys
ROOT=Path(__file__).resolve().parent
REQ=[
("custom_addons/ai_workflow/models/workflow.py", "class AiWorkflow"),
("custom_addons/ai_collaboration/models/workspace.py", "class AiWorkspace"),
("custom_addons/ai_document_intelligence/models/intelligence.py", "class AiFileJob"),
("custom_addons/ai_correspondence/models/correspondence.py", "class AiCorrespondenceTemplate"),
("custom_addons/ai_production/models/production.py", "class AiReleaseCertification"),
("custom_addons/ai_integration/models/event_dispatch.py", "enqueue_for_event"),
]

def main():
 failures=[]
 for rel,needle in REQ:
  p=ROOT/rel
  if not p.exists() or needle not in p.read_text(): failures.append(f"missing contract: {rel} -> {needle}")
 for p in ROOT.glob('custom_addons/**/*.py'):
  try: ast.parse(p.read_text())
  except Exception as e: failures.append(f"python syntax: {p}: {e}")
 for p in ROOT.glob('custom_addons/**/__manifest__.py'):
  try: ast.literal_eval(p.read_text())
  except Exception as e: failures.append(f"manifest: {p}: {e}")
 if failures:
  print("FAIL"); print("\n".join(failures)); return 1
 print("PASS: structural production contract suite")
 return 0
if __name__=='__main__': raise SystemExit(main())
