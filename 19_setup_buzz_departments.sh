#!/bin/bash
# =============================================================================
# Buzz, made pervasive: one bot identity + one channel + one systemd
# service PER REAL DEPARTMENT, instead of 10_setup_buzz.sh's original
# single-channel pilot. Run 10_setup_buzz.sh FIRST (builds buzz once) -
# this script only adds the multi-department provisioning on top.
#
# SECURITY DESIGN (read this before running):
#   - Every department bot's Odoo identity is scoped to 'Role: Employee'
#     only (see 20_provision_buzz_bot_users.py) - never a manager role.
#     Buzz routes every message through ONE FIXED Odoo API key per
#     bridge process (unlike the Telegram bridge, which maps each
#     sender to their OWN key) - so keeping the bot's own permissions
#     at the lowest level means a misdirected "approve my leave"
#     request through the bot gets an honest access_denied from Odoo's
#     own ACL, regardless of who asked. This is a UX limit, not a
#     security hole - do not raise the bot's role for convenience.
#   - Every bot is --respond-to owner-only, matching Hermes Agent's own
#     official guidance ("Keep Buzz agents owner-only"). The owner is
#     that department's manager's PERSONAL Nostr pubkey - which this
#     script cannot generate for them (it's their own identity) and
#     deliberately does not guess or fake. That is the one manual step
#     left per department, printed at the end.
#   - Heartbeat posting (roadmap: "دیده بشه و استفاده بشه") is what
#     makes this pervasive instead of passive: every hour, each bot
#     asks Odoo's own Company Assistant (via gateway_chat - the SAME
#     Risk Engine/Approval Object-aware assistant a human gets) for a
#     digest of ITS department's overdue tasks and pending approvals,
#     and posts it to that department's channel unprompted.
# =============================================================================
set -e

BUZZ_DIR="/opt/buzz"
BRIDGE_DIR="/opt/buzz-bridge"
CONFIG_DIR="/etc/buzz-department"
CSV_PATH="/opt/buzz_department_bots.csv"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUZZ_RELAY_URL="${BUZZ_RELAY_URL:-ws://localhost:8080}"

if [ ! -x "${BUZZ_DIR}/target/release/buzz-acp" ] && [ ! -x "${BUZZ_DIR}/target/debug/buzz-acp" ]; then
  echo "ERROR: buzz is not built yet - run ./10_setup_buzz.sh first."
  exit 1
fi
BUZZ_BIN_DIR="${BUZZ_DIR}/target/release"
[ -x "${BUZZ_BIN_DIR}/buzz-acp" ] || BUZZ_BIN_DIR="${BUZZ_DIR}/target/debug"

echo "=== [1/5] Provisioning one low-privilege bot identity per department in Odoo ==="
source /opt/odoo-venv/bin/activate 2>/dev/null || true
/opt/odoo/odoo-bin shell -c /opt/odoo.conf -d company_ai < "${SCRIPT_DIR}/20_provision_buzz_bot_users.py"

if [ ! -f "$CSV_PATH" ]; then
  echo "ERROR: ${CSV_PATH} was not created - check the output above for errors."
  exit 1
fi

echo ""
echo "=== [2/5] System user + config directory ==="
id -u buzz-bot &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin buzz-bot
mkdir -p "$CONFIG_DIR"
chown root:buzz-bot "$CONFIG_DIR"
chmod 750 "$CONFIG_DIR"

echo ""
echo "=== [3/5] Installing the systemd template unit ==="
cp "${SCRIPT_DIR}/buzz_bridge/buzz-department@.service" /etc/systemd/system/
systemctl daemon-reload

echo ""
echo "=== [4/5] Per-department: Nostr keypair, channel, env file, heartbeat prompt ==="
MANUAL_STEPS=""
{
  read  # skip CSV header
  while IFS=, read -r department slug bot_login api_key manager_login; do
    echo "--- ${department} (slug: ${slug}) ---"

    KEY_OUTPUT=$("${BUZZ_BIN_DIR}/buzz-admin" generate-key)
    NSEC=$(echo "$KEY_OUTPUT" | grep -oE 'nsec1[a-z0-9]+' | head -1)
    if [ -z "$NSEC" ]; then
      echo "  Could not parse a private key from buzz-admin generate-key output:"
      echo "  ${KEY_OUTPUT}"
      echo "  Skipping ${department} - generate its key manually and configure by hand."
      continue
    fi

    CHANNEL_OUTPUT=$(BUZZ_RELAY_URL="$BUZZ_RELAY_URL" BUZZ_PRIVATE_KEY="$NSEC" \
      "${BUZZ_BIN_DIR}/buzz-cli" channels create --name "${slug}" --type stream --visibility open 2>&1) \
      || echo "  (channel may already exist - continuing)"

    cat > "${CONFIG_DIR}/${slug}.env" << ENVEOF
BUZZ_ACP_PRIVATE_KEY=${NSEC}
BUZZ_ACP_AGENT_OWNER=REPLACE_WITH_${slug}_MANAGER_NOSTR_PUBKEY
BUZZ_RELAY_URL=${BUZZ_RELAY_URL}
ODOO_GATEWAY_URL=${ODOO_GATEWAY_URL:-https://REPLACE_WITH_YOUR_DOMAIN}
ODOO_GATEWAY_API_KEY=${api_key}
ENVEOF
    chmod 640 "${CONFIG_DIR}/${slug}.env"
    chown root:buzz-bot "${CONFIG_DIR}/${slug}.env"

    cat > "${CONFIG_DIR}/${slug}.heartbeat.txt" << HBEOF
با ابزار gateway_chat از دستیار Odoo بخواه یک خلاصه‌ی کوتاه از تسک‌های
عقب‌افتاده و مرخصی‌های در انتظار تایید بخش «${department}» بدهد. اگر
هیچ‌کدام وجود نداشت، هیچ پیامی پست نکن (فقط وقتی چیزی برای گزارش هست
پست کن، نه هر ساعت یک پیام تکراری «چیزی نیست»).
HBEOF
    chmod 640 "${CONFIG_DIR}/${slug}.heartbeat.txt"
    chown root:buzz-bot "${CONFIG_DIR}/${slug}.heartbeat.txt"

    echo "  Config written: ${CONFIG_DIR}/${slug}.env"
    MANUAL_STEPS="${MANUAL_STEPS}\n  [${department}] edit ${CONFIG_DIR}/${slug}.env - set ODOO_GATEWAY_URL and BUZZ_ACP_AGENT_OWNER (manager: ${manager_login:-NOT SET, no manager on this department in Odoo}), then: systemctl enable --now buzz-department@${slug}.service"
  done
} < "$CSV_PATH"

echo ""
echo "=== [5/5] Done provisioning - nothing was started ==="
echo "Exactly as with the single-channel pilot, starting a bot for real is"
echo "a deliberate manual step per department (never auto-started with a"
echo "placeholder owner - that would make the gate meaningless):"
echo -e "$MANUAL_STEPS"
echo ""
echo "After starting each one, confirm in Settings > Administration > AI"
echo "Gateway Audit Log that its gateway_chat calls are showing up tagged"
echo "with that department's bot user - same verification step as the"
echo "single-channel pilot (roadmap #59's step 5), just once per department."
