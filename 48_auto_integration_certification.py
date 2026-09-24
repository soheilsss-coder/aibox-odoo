"""V47 Universal Auto-Integration Certification.

Run inside a real Odoo shell:
  /opt/odoo/odoo-bin shell -c /opt/odoo.conf -d company_ai < 48_auto_integration_certification.py

This runner is fail-closed. It never turns structural presence into a PASS.
For every selected installed module it verifies discovery, capabilities,
reviewed adapter/operations, unified execution contracts, events, and then
runs the live integration certification runner with runtime probes enabled.
A module is production-eligible only when every check is PASS.
"""
import json
import sys

MODULES = [
    "purchase", "stock", "account", "mrp", "crm", "hr", "hr_holidays",
    "sale_management", "project", "documents", "calendar", "helpdesk", "hr_expense",
]


def out(ok, label, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", label, (" - " + detail) if detail else ""))
    return bool(ok)


def main(env):
    Cert = env["ai.integration.certification.runner"].sudo()
    installed = set(env["ir.module.module"].sudo().search([("state", "=", "installed")]).mapped("name"))
    targets = [m for m in MODULES if m in installed]
    if not targets:
        return out(False, "installed business modules discovered", "none of the certification targets is installed")

    all_ok = True
    for module_name in targets:
        print("\n=== CERTIFY %s ===" % module_name)
        # The runner itself is fail-closed and performs the runtime probes.
        result = Cert.run_for_module(module_name, live_runtime=True)
        checks = result.get("checks", [])
        module_ok = result.get("status") == "pass" and all(c.get("pass") for c in checks)
        all_ok &= out(module_ok, "%s production certification" % module_name,
                      "status=%s" % result.get("status"))
        for check in checks:
            if not check.get("pass"):
                print("    FAIL: %s%s" % (check.get("name"),
                    (" - " + str(check.get("detail"))) if check.get("detail") else ""))

    # Global gate: every installed target must have a latest PASS record.
    latest_ok = True
    for module_name in targets:
        ok = Cert.can_promote(module_name)
        latest_ok &= out(ok, "promotion gate: %s" % module_name)
    all_ok &= latest_ok
    print("\nRESULT: %s" % ("PRODUCTION CERTIFIED" if all_ok else "PRODUCTION BLOCKED"))
    return 0 if all_ok else 1


if "env" in globals():
    raise SystemExit(main(env))
print("This script must run inside an Odoo shell so that `env` is available.")
raise SystemExit(2)
