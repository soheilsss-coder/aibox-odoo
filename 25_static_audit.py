#!/usr/bin/env python3
"""Static release checks for the AI ERP package.

This intentionally does not pretend to be an Odoo integration test: Odoo,
PostgreSQL, vLLM and the third-party LLM addons are runtime dependencies and
are not bundled in this archive.
"""
from pathlib import Path
import ast
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
errors = []

# Audit scripts may reference the generic-tool prefix as the SUBJECT of
# a check ("these names must never appear in production code"), so the
# whole audit/gate family (NN_*.py and FINAL_*.py at the repo root) is
# excluded via a computed set - not a hardcoded per-file one-off. A new
# audit script added later is automatically covered.
_AUDIT_NAME = re.compile(r"^(?:FINAL_|\d{1,2}_)")
AUDIT_SCRIPTS = {p.name for p in ROOT.glob("*.py") if _AUDIT_NAME.match(p.name)}
AUDIT_SCRIPTS.add("25_static_audit.py")


def _sh_path(p):
    """Translate a Windows checkout path to the WSL-visible /mnt path so
    `bash -n` (below) works when the audits are run on a Windows box.""" 
    s = os.fspath(p)
    if os.name != "nt":
        return s
    drive, rest = os.path.splitdrive(s)
    drive = (drive or "C").rstrip(":").lower()
    return "/mnt/" + drive + "/" + rest.replace("\\", "/").lstrip("/")


for p in ROOT.rglob("*.py"):
    try:
        ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
    except SyntaxError as exc:
        errors.append(f"PYTHON {p}: {exc}")

for p in ROOT.rglob("*.xml"):
    try:
        ET.parse(p)
    except ET.ParseError as exc:
        errors.append(f"XML {p}: {exc}")

for p in ROOT.rglob("*.sh"):
    r = subprocess.run(["bash", "-n", _sh_path(p)], capture_output=True, text=True)
    if r.returncode:
        errors.append(f"SHELL {p}: {r.stderr.strip()}")

checks = {
    "generic assistant assignment removed": "all_tools = env['llm.tool'].search([])" not in (ROOT / "02_install_modules.sh").read_text(),
    "generic ORM tool refs removed": not any("llm_tool_odoo_record_" in p.read_text(errors="ignore") for p in ROOT.rglob("*.py") if p.name not in AUDIT_SCRIPTS),
    "query-string API key removed": not any("args.get(\"api_key\"" in p.read_text(errors="ignore") for p in ROOT.rglob("*.py")),
    "control plane present": (ROOT / "custom_addons/ai_control_plane/__manifest__.py").exists(),
}
for name, ok in checks.items():
    if not ok:
        errors.append(f"CHECK failed: {name}")
    print(("PASS" if ok else "FAIL") + " - " + name)

if errors:
    print("\nFAILURES:")
    print("\n".join(errors))
    sys.exit(1)
print("\nSTATIC AUDIT PASS")
