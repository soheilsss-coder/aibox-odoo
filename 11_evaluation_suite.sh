#!/bin/bash
# Evaluation Suite wrapper (roadmap #49).
#
# 11_evaluation_suite.py is a genuinely external HTTP client - it must
# never import Odoo itself, or it would stop being a faithful stand-in
# for the real frontend. But it still needs the demo users' real API
# keys to authenticate, and those are randomly generated per
# install (ai.gateway.api.key.key defaults to secrets.token_hex(24)),
# so nothing outside the database can know them in advance.
#
# This wrapper is the bridge: fetch the keys the ONLY way that's
# possible (an odoo-bin shell one-liner, same mechanism
# 05_acceptance_tests.py already uses), write them to a temp file,
# then hand off to the pure-HTTP script and clean up.
set -euo pipefail

ODOO_BIN="${ODOO_BIN:-/opt/odoo/src/odoo/odoo-bin}"
ODOO_PYTHON="${ODOO_PYTHON:-/opt/odoo/venv/bin/python}"
ODOO_CONF="${ODOO_CONF:-/etc/odoo/odoo.conf}"
ODOO_DB="${ODOO_DB:-company_ai}"
BASE_URL="${AI_GATEWAY_BASE_URL:-http://localhost:8069}"

TMP_RAW=$(mktemp)
TMP_KEYS=$(mktemp)
trap 'rm -f "$TMP_RAW" "$TMP_KEYS"' EXIT

echo "Fetching demo users' real API keys..."
"$ODOO_PYTHON" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$ODOO_DB" > "$TMP_RAW" 2>&1 <<'PYEOF'
import json
Key = env["ai.gateway.api.key"].sudo()


def key_for(login):
    user = env["res.users"].search([("login", "=", login)], limit=1)
    if not user:
        return None
    # Plaintext keys are intentionally never stored.  The test harness gets
    # one short-lived rotated secret directly from create_key(), then removes
    # it with the temporary file trap after the HTTP run.
    return Key.create_key(user, scope="evaluation")


print("EVAL_KEYS_JSON=" + json.dumps({
    "ceo": key_for("ceo@demo.local"),
    "accountant": key_for("accountant@demo.local"),
    "warehouse": key_for("warehouse@demo.local"),
}))
PYEOF

if ! grep -q "EVAL_KEYS_JSON=" "$TMP_RAW"; then
    echo "Could not fetch API keys - is Odoo installed and running? Full output:"
    cat "$TMP_RAW"
    exit 1
fi
grep "EVAL_KEYS_JSON=" "$TMP_RAW" | sed 's/^EVAL_KEYS_JSON=//' > "$TMP_KEYS"

echo "Running the evaluation suite against $BASE_URL ..."
python3 "$(dirname "$0")/11_evaluation_suite.py" --keys-file "$TMP_KEYS" --base-url "$BASE_URL" "$@"
