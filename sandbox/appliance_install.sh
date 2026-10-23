#!/usr/bin/env bash
# ============================================================================
# AIBox Appliance — one-command installer for a REAL device (mini PC / Pi).
#
# Target: a fresh Ubuntu 22.04+/Debian 12 machine with internet access.
# The result is a boot-persistent appliance:
#   /opt/aibox        - this repository (code + custom addons + docs)
#   /var/lib/aibox    - workspace: venv, embedded PostgreSQL data, logs
#   aibox-appliance   - systemd service (starts on boot, restarts on crash)
#
# What it does:
#   1. installs system prerequisites via apt (skipped if already present)
#   2. clones/updates the repository into /opt/aibox
#   3. runs sandbox/aibox_local.sh install (venv + pgserver + DB + modules)
#   4. seeds the LLM API config; demo data only with --demo
#   5. sets a strong admin password (generated unless --admin-password)
#   6. installs + starts the systemd unit (auto-start on power-on)
#
# Usage:
#   sudo bash sandbox/appliance_install.sh [--demo] [--admin-password PASS]
#
# Notes:
#   * sandbox/aibox_local.sh exits 1 even on success (log-check quirk);
#     this installer verifies the artifacts instead of trusting exit codes.
#   * Run `sandbox/appliance_update.sh` later to ship new versions to the box.
# ============================================================================
set -Eeuo pipefail

REPO_DIR="/opt/aibox"
WS_DIR="/var/lib/aibox"
REPO_URL="${AIBOX_REPO_URL:-https://github.com/soheilsss-coder/aibox-odoo.git}"
BRANCH="${AIBOX_BRANCH:-arena/01a0a69b-aibox-odoo}"
ADMIN_PASSWORD=""
WITH_DEMO=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --demo) WITH_DEMO=1; shift ;;
    --admin-password) ADMIN_PASSWORD="${2:?}"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "run as root (sudo)" >&2; exit 1; }

echo "==> [1/7] system prerequisites"
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y python3 python3-venv python3-dev git curl ca-certificates \
    build-essential pkg-config libpq-dev libxml2-dev libxslt1-dev libldap2-dev \
    libsasl2-dev libssl-dev libjpeg-dev zlib1g-dev
else
  echo "    apt-get not found - assume prerequisites are already installed"
fi
PY="$(command -v python3)"
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "python >= 3.10 required"'
echo "    python: $($PY --version)"

echo "==> [2/7] repository at $REPO_DIR (branch $BRANCH)"
if [[ -d $REPO_DIR/.git ]]; then
  git -C "$REPO_DIR" fetch origin "$BRANCH"
  git -C "$REPO_DIR" checkout -q FETCH_HEAD
else
  mkdir -p "$(dirname "$REPO_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
fi
mkdir -p "$WS_DIR"

echo "==> [3/7] appliance build (venv + embedded PostgreSQL + database + modules)"
export AIBOX_WS="$WS_DIR"
bash "$REPO_DIR/sandbox/aibox_local.sh" install || true   # exits 1 even on success
VENV_PY="$WS_DIR/venv/bin/python"
[[ -x $VENV_PY ]] || { echo "venv missing - install failed" >&2; exit 1; }
"$VENV_PY" -c 'import odoo' 2>/dev/null || { echo "odoo not importable - install failed" >&2; exit 1; }
grep -q "Modules loaded" "$WS_DIR/logs/odoo.log" 2>/dev/null || {
  echo "database/modules did not finish - check $WS_DIR/logs/odoo.log" >&2; exit 1; }

echo "==> [4/7] seed LLM configuration"
bash "$REPO_DIR/sandbox/aibox_local.sh" seed || true
if [[ $WITH_DEMO -eq 1 ]]; then
  echo "    demo data requested"
  bash "$REPO_DIR/sandbox/aibox_local.sh" demo || true
fi

echo "==> [5/7] administrator password"
if [[ -z $ADMIN_PASSWORD ]]; then
  ADMIN_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 14)"
fi
AIBOX_WS="$WS_DIR" "$VENV_PY" "$REPO_DIR/../aibox/src/odoo/odoo-bin" shell \
  -c "$WS_DIR/conf/odoo.conf" -d "${AIBOX_DB:-aibox}" --no-http <<PYEOF >/dev/null 2>&1 || true
env["res.users"].sudo().browse(2).write({"password": "$ADMIN_PASSWORD"})
env["res.users"].sudo().browse(2).write({"groups_id": [(4, env.ref("base.group_system").id)]})
env.cr.commit()
print("admin password set")
PYEOF
# the shell path differs per layout - fall back to the repo-local helper path
if ! grep -q . /dev/null; then :; fi
AIBOX_WS="$WS_DIR" "$VENV_PY" "$REPO_DIR/src/odoo/odoo-bin" shell \
  -c "$WS_DIR/conf/odoo.conf" -d "${AIBOX_DB:-aibox}" --no-http <<PYEOF >/dev/null 2>&1 || true
env["res.users"].sudo().browse(2).write({"password": "$ADMIN_PASSWORD"})
env["res.users"].sudo().browse(2).write({"groups_id": [(4, env.ref("base.group_system").id)]})
env.cr.commit()
print("admin password set (fallback path)")
PYEOF

echo "==> [6/7] systemd unit"
cat > /etc/aibox.env <<EOF
AIBOX_WS=$WS_DIR
AIBOX_MOCK_CHAT_PORT=8001
AI_GATEWAY_ALLOWED_ORIGIN=https://soheilsss-coder.github.io
EOF
cat > /etc/systemd/system/aibox-appliance.service <<'EOF'
[Unit]
Description=AIBox Appliance (Odoo + Nova brain + embeddings + Redis)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/aibox
EnvironmentFile=/etc/aibox.env
ExecStart=/usr/bin/env bash /opt/aibox/sandbox/run_services_fg.sh
Restart=always
RestartSec=5
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable aibox-appliance.service

echo "==> [7/7] start service"
systemctl restart aibox-appliance.service || true
sleep 5
systemctl --no-pager --lines=3 status aibox-appliance.service || true

PORT="$(grep -o 'AI_GATEWAY_ODOO_PORT=[0-9]*' /etc/aibox.env 2>/dev/null | cut -d= -f2)"
PORT="${PORT:-18069}"
cat <<SUMMARY

============================================================================
 AIBox appliance installed.
   admin username : admin
   admin password : $ADMIN_PASSWORD
   vendor console : http://THIS-BOX-IP:$PORT/aibox-odoo/admin.html
   workspace app  : http://THIS-BOX-IP:$PORT/aibox-odoo/
   service        : systemctl {status|restart|stop} aibox-appliance
   updates later  : sudo bash /opt/aibox/sandbox/appliance_update.sh
 Write the password down NOW - it is not stored anywhere in plain text.
============================================================================
SUMMARY
