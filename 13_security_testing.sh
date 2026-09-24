#!/bin/bash
# Security Testing wrapper (roadmap #50) - same bridge pattern as
# 11_evaluation_suite.sh: 13_security_testing.py is a genuinely
# external HTTP client (an attacker never gets a shell on your Odoo
# box), so it must never import Odoo itself - but it still needs the
# demo users' real, randomly-generated API keys to run its scenarios,
# and nothing outside the database can know them in advance.
set -euo pipefail

ODOO_BIN="${ODOO_BIN:-/opt/odoo/odoo-bin}"
ODOO_CONF="${ODOO_CONF:-/opt/odoo.conf}"
ODOO_DB="${ODOO_DB:-company_ai}"
BASE_URL="${AI_GATEWAY_BASE_URL:-http://localhost:8069}"

TMP_RAW=$(mktemp)
TMP_KEYS=$(mktemp)
trap 'rm -f "$TMP_RAW" "$TMP_KEYS"' EXIT

echo "Fetching demo users' real API keys..."
"$ODOO_BIN" shell -c "$ODOO_CONF" -d "$ODOO_DB" > "$TMP_RAW" 2>&1 <<'PYEOF'
import json
Key = env["ai.gateway.api.key"].sudo()


def key_for(login):
    user = env["res.users"].search([("login", "=", login)], limit=1)
    if not user:
        return None
    rec = Key.search([("user_id", "=", user.id)], limit=1)
    return rec.key if rec else None


print("SECURITY_KEYS_JSON=" + json.dumps({
    "ceo": key_for("ceo@demo.local"),
    "accountant": key_for("accountant@demo.local"),
    "warehouse": key_for("warehouse@demo.local"),
}))
PYEOF

if ! grep -q "SECURITY_KEYS_JSON=" "$TMP_RAW"; then
    echo "Could not fetch API keys - is Odoo installed and running? Full output:"
    cat "$TMP_RAW"
    exit 1
fi
grep "SECURITY_KEYS_JSON=" "$TMP_RAW" | sed 's/^SECURITY_KEYS_JSON=//' > "$TMP_KEYS"

echo "Running the adversarial security test suite against $BASE_URL ..."
python3 "$(dirname "$0")/13_security_testing.py" --keys-file "$TMP_KEYS" --base-url "$BASE_URL" "$@"
