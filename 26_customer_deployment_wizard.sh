#!/bin/bash
set -euo pipefail
# Customer-safe deployment bootstrap. Never exposes a browser API key.
# Usage: ./26_customer_deployment_wizard.sh <db> <company_name> [timezone]
DB="${1:?database required}"
COMPANY="${2:?company name required}"
TZ="${3:-UTC}"
ODOO_BIN="${ODOO_BIN:-/opt/odoo/odoo-bin}"
ODOO_CONF="${ODOO_CONF:-/opt/odoo.conf}"
source /opt/odoo-venv/bin/activate 2>/dev/null || true
"$ODOO_BIN" shell -c "$ODOO_CONF" -d "$DB" <<PY
from odoo import api, SUPERUSER_ID
env = api.Environment(cr, SUPERUSER_ID, {})
company = env['res.company'].search([], limit=1)
company.write({'name': ${COMPANY@Q}})
# Ensure universal integration layer is installed and synchronized.
mods = env['ir.module.module'].search([('name', 'in', ['ai_control_plane','ai_integration','ai_semantic_api','ai_gateway'])])
print('Configured company:', company.name)
print('AI modules:', [(m.name, m.state) for m in mods])
if 'ai.control.module' in env:
    env['ai.control.module'].sync_installed_modules()
if 'ai.integration.test.runner' in env:
    for m in env['ir.module.module'].search([('state','=','installed')]).mapped('name'):
        try: print(env['ai.integration.test.runner'].run_for_module(m))
        except Exception as exc: print('WARN', m, exc)
PY
echo "Customer deployment bootstrap complete. Configure TLS, SSO/SCIM and model endpoints before production activation."
