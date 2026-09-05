#!/usr/bin/env bash
set -euo pipefail
ODOO_PYTHON="${ODOO_PYTHON:-/opt/odoo/venv/bin/python}"
ODOO_BIN="${ODOO_BIN:-/opt/odoo/src/odoo/odoo-bin}"
ODOO_CONF="${ODOO_CONF:-/etc/odoo/odoo.conf}"
ODOO_DB="${ODOO_DB:-company_ai}"
[[ -x "$ODOO_PYTHON" ]] || { echo "Missing Odoo virtualenv Python: $ODOO_PYTHON" >&2; exit 1; }
[[ -x "$ODOO_BIN" ]] || { echo "Missing Odoo binary: $ODOO_BIN" >&2; exit 1; }
exec "$ODOO_PYTHON" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$ODOO_DB" < "$(dirname "$0")/event_bus_worker.py"
