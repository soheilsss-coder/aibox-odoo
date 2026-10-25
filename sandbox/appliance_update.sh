#!/usr/bin/env bash
# Ship a new version to an installed appliance: pull code, upgrade custom
# modules, restart the service. Safe to run repeatedly.
set -Eeuo pipefail

REPO_DIR="${AIBOX_REPO_DIR:-/opt/aibox}"
WS_DIR="${AIBOX_WS:-/var/lib/aibox}"
BRANCH="${AIBOX_BRANCH:-arena/01a0a69b-aibox-odoo}"

echo "==> pull latest code ($BRANCH)"
git -C "$REPO_DIR" fetch origin "$BRANCH"
git -C "$REPO_DIR" checkout -q FETCH_HEAD

echo "==> upgrade custom modules"
export AIBOX_WS="$WS_DIR"
VENV_PY="$WS_DIR/venv/bin/python"
ODOO_BIN="$REPO_DIR/src/odoo/odoo-bin"
[[ -x $VENV_PY ]] || { echo "appliance not installed at $WS_DIR" >&2; exit 1; }
"$VENV_PY" "$ODOO_BIN" -c "$WS_DIR/conf/odoo.conf" -d "${AIBOX_DB:-aibox}" \
  -u ai_gateway,ai_business_tools,ai_customer_plane,ai_semantic_api,ai_integration \
  --stop-after-init > "$WS_DIR/logs/upgrade.log" 2>&1 \
  || { echo "module upgrade failed - see $WS_DIR/logs/upgrade.log" >&2; exit 1; }

echo "==> restart service"
if systemctl is-active --quiet aibox-appliance 2>/dev/null; then
  systemctl restart aibox-appliance
else
  echo "    systemd unit not present - start manually (run_services_fg.sh)"
fi
echo "==> done. verify: systemctl status aibox-appliance"
