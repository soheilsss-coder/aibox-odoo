#!/usr/bin/env python3
"""Produce a fail-closed capability/adapter matrix from a live Odoo registry.

Run inside an Odoo shell after module installation. Static lists are only a
classification hint; the installed module table is the source of truth. The
report is written outside the repository by default and deliberately
 distinguishes reviewed operational coverage from generic read-only discovery.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


# Business applications that require a reviewed operational adapter when
# installed. Technical/base modules still receive discovery/capability/audit
# coverage, but are not falsely certified as business-operation adapters.
BUSINESS_MODULES = {
    "account", "calendar", "crm", "documents", "event", "helpdesk", "hr",
    "hr_attendance", "hr_expense", "hr_holidays", "lunch", "maintenance",
    "mrp", "point_of_sale", "pos_restaurant", "project", "purchase", "quality",
    "repair", "sale", "sale_management", "sale_renting", "sale_subscription",
    "stock", "website", "mass_mailing", "barcodes", "fleet", "hr_payroll",
    "hr_recruitment", "event_sale", "event_crm", "pos_sale", "sale_project",
    "sale_stock", "stock_barcode", "stock_account", "mrp_workorder",
}

# Only these Odoo platform modules are exempt from the business-adapter
# requirement. Any other installed non-AI module is treated as an
# operational business surface and blocks promotion until it has an explicit
# reviewed adapter, capability, handler and native-ACL probe.
PLATFORM_MODULES = {
    "base", "web", "web_editor", "web_tour", "bus", "mail", "mail_bot",
    "http_routing", "auth_signup", "auth_totp", "portal", "resource", "uom",
    "product", "contacts", "fetchmail", "iap", "link_tracker", "onboarding",
    "phone_validation", "digest", "utm", "spreadsheet", "spreadsheet_oca",
    "company_ai_demo",
}


def main(env, output=None):
    output = Path(output or os.getenv("AI_MODULE_MATRIX_OUTPUT", "/tmp/ai-v58-module-matrix.json"))
    env["ai.control.module"].sudo().sync_installed_modules()
    installed = env["ir.module.module"].sudo().search([("state", "=", "installed")])
    registry = env["ai.control.module"].sudo()
    adapters = env["ai.integration.adapter"].sudo()
    operations = env["ai.integration.operation"].sudo().search([("active", "=", True)])
    capabilities = env["ai.control.capability"].sudo().search([("active", "=", True)])
    subscriptions = env["ai.integration.subscription"].sudo().search([("active", "=", True)])
    rows = []
    blocked = []

    for module in installed.sorted(key=lambda rec: rec.name):
        name = module.name
        item = registry.search([("technical_name", "=", name)], limit=1)
        adapter = adapters.search([("module_name", "=", name), ("active", "=", True)], limit=1)
        module_ops = operations.filtered(lambda op: op.module_name == name)
        module_caps = capabilities.filtered(lambda cap: cap.module_name == name)
        reviewed = bool(adapter and adapter.state == "ready")
        reviewed_operations = module_ops.filtered(
            lambda op: op.source == "reviewed" and op.coverage == "reviewed_operational"
        )
        discovered_operations = module_ops.filtered(lambda op: op.coverage == "discovered_read")
        contracts = []
        for op in module_ops:
            try:
                contract = env["ai.integration.unified.registry"].sudo().execution_contract(op.tool_name)
                handler = getattr(env["ai.integration.adapter.service"], "_handle_%s" % op.handler_key, None)
                contracts.append(bool(contract and handler))
            except Exception:  # noqa: BLE001
                contracts.append(False)
        business = name in BUSINESS_MODULES or (
            name not in PLATFORM_MODULES
            and not name.startswith("ai_")
            and name != "company_ai_demo"
        )
        if business and not (reviewed and reviewed_operations and contracts and all(contracts)):
            status = "blocked"
            blocked.append(name)
        elif reviewed and reviewed_operations and all(contracts):
            status = "reviewed_operational"
        else:
            status = "discovered_read_only"
        try:
            unavailable_mutations = json.loads(item.unavailable_mutations_json or "[]") if item else []
        except (TypeError, ValueError):
            unavailable_mutations = [{"status": "blocked", "reason": "invalid registry metadata"}]
        rows.append({
            "technical_name": name,
            "installed_version": module.installed_version or module.latest_version or "",
            "business_module": business,
            "registered": bool(item and item.state == "installed"),
            "discovered_models": item.discovered_models if item else 0,
            "discovered_groups": item.discovered_groups if item else 0,
            "capability_count": len(module_caps),
            "adapter": adapter.module_name if adapter else None,
            "adapter_state": adapter.state if adapter else "missing",
            "integration_level": item.integration_level if item else "blocked",
            "operation_count": len(module_ops),
            "discovered_read_operation_count": len(discovered_operations),
            "reviewed_operational_operation_count": len(reviewed_operations),
            "unavailable_mutations": unavailable_mutations,
            "operation_contracts_pass": bool(module_ops) and bool(contracts) and all(contracts),
            "active_event_targets": sorted(set(subscriptions.mapped("target"))),
            "status": status,
        })

    report = {
        "schema_version": 1,
        "source": "live Odoo registry",
        "fail_closed": True,
        "installed_module_count": len(rows),
        "business_modules_blocked": sorted(blocked),
        "production_eligible": not blocked and all(row["registered"] for row in rows),
        "rows": rows,
        "limitations": [
            "Discovery is not an operational adapter.",
            "Business certification still requires live non-destructive and end-to-end probes.",
            "This report does not prove capacity, latency, or cross-tenant isolation by itself.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "installed_module_count": report["installed_module_count"],
        "business_modules_blocked": report["business_modules_blocked"],
        "production_eligible": report["production_eligible"],
        "output": str(output),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if report["production_eligible"] else 1


if "env" in globals():
    raise SystemExit(main(env))
print("Run this script inside an Odoo shell so that `env` is available.")
raise SystemExit(2)
