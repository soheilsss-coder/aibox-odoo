#!/usr/bin/env bash
set -euo pipefail
ODOO_BIN="${ODOO_BIN:-/opt/odoo/odoo-bin}"; ODOO_CONF="${ODOO_CONF:-/opt/odoo.conf}"; ODOO_DB="${ODOO_DB:-company_ai}"
exec "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$ODOO_DB" < "$(dirname "$0")/event_bus_worker.py"
