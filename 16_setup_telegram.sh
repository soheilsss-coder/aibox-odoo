#!/bin/bash
# =============================================================================
# Telegram Bridge - install the ai_telegram_bridge Odoo module, then print
# the exact manual steps to wire a real bot (never done automatically -
# same reasoning as 10_setup_buzz.sh: a real bot token is a client
# credential, it must never end up hardcoded in a script or shell history).
#
# ARCHITECTURE (see custom_addons/ai_telegram_bridge/controllers/telegram.py
# for the full reasoning): this is NOT a separate AI agent. Every Telegram
# message becomes one call to this project's OWN /api/chat endpoint, using
# the sending employee's OWN ai.gateway.api.key - same Risk Engine (#20),
# Approval Object (#21), gateway allowlist, and audit log as the React
# frontend. Built after researching github.com/arunrajiah/odoopilot (real,
# well-built, LGPL-3) and deliberately NOT installing it as-is, because it
# ships its own separate LLM/permission model - a second security surface
# parallel to this project's, the same concern already raised about Buzz's
# own buzz-dev-mcp (roadmap #59).
#
# Usage:
#   ./16_setup_telegram.sh
# =============================================================================
set -e

MODULE_SRC="custom_addons/ai_telegram_bridge"

echo "=== [1/2] Checking the module is in place ==="
if [ ! -d "${MODULE_SRC}" ]; then
  echo "custom_addons/ai_telegram_bridge not found - copy it in first, then re-run."
  exit 1
fi
echo "ok - found ${MODULE_SRC}"

echo ""
echo "=== [2/2] Install it like any other custom module ==="
echo "    (adjust -d to your actual database name)"
echo ""
echo "    /opt/odoo/odoo-bin -c /opt/odoo.conf -d company_ai -i ai_telegram_bridge --stop-after-init"
echo ""
echo "Module install command printed, nothing executed automatically."
echo ""
echo "Manual steps before piloting for real (do NOT skip):"
echo ""
echo "  1. Talk to @BotFather on Telegram, /newbot, get a bot token"
echo "     (looks like 123456789:AAF...). This is a real credential -"
echo "     do not paste it into any script file, only into the shell"
echo "     command below or Odoo's own config parameters."
echo ""
echo "  2. Set the three config parameters this module reads"
echo "     (ir.config_parameter, via the Odoo shell - source"
echo "     /opt/odoo-venv/bin/activate first):"
echo ""
echo "         /opt/odoo/odoo-bin shell -c /opt/odoo.conf -d company_ai <<'EOF'"
echo "         env['ir.config_parameter'].sudo().set_param('ai_telegram_bridge.bot_token', '<token from step 1>')"
echo "         env['ir.config_parameter'].sudo().set_param('ai_telegram_bridge.bot_username', '<your_bot_username>')"
echo "         env['ir.config_parameter'].sudo().set_param('ai_telegram_bridge.webhook_secret', __import__('secrets').token_urlsafe(32))"
echo "         env['ir.config_parameter'].sudo().set_param('ai_telegram_bridge.gateway_base_url', 'http://127.0.0.1:8069')"
echo "         env.cr.commit()"
echo "         EOF"
echo ""
echo "  3. Register the webhook with Telegram, using the SAME secret you"
echo "     just stored (Telegram sends it back on every call as the"
echo "     X-Telegram-Bot-Api-Secret-Token header - this module refuses"
echo "     any webhook call where it doesn't match, see controllers/"
echo "     telegram.py). Requires your server's real public HTTPS URL"
echo "     (roadmap #6/TLS) - Telegram will not call plain HTTP:"
echo ""
echo "         curl -s \"https://api.telegram.org/bot<TOKEN>/setWebhook\" \\"
echo "             -d \"url=https://<your-real-domain>/telegram/webhook\" \\"
echo "             -d \"secret_token=<same secret from step 2>\""
echo ""
echo "  4. Each employee who wants Telegram access links their OWN chat"
echo "     (never share one chat/bot across multiple employees - same"
echo "     one-identity-per-agent rule as roadmap #19):"
echo "       a) inside Odoo: top menu 'AI Telegram' > 'Generate Link"
echo "          Code' - shows an 8-character code, valid 10 minutes"
echo "       b) in Telegram, open a chat with the bot and send:"
echo "          /link THECODE"
echo "       c) the bot confirms; from then on, messages in that chat"
echo "          go to /api/chat as that employee, through the same"
echo "          Risk Engine/Approval Object checks as the web frontend"
echo ""
echo "  5. Before trusting this beyond one pilot employee, confirm every"
echo "     message shows up in Settings > Administration > AI Audit Log"
echo "     exactly like a React-frontend call would - same verification"
echo "     step already recommended for Buzz (roadmap #59)."
echo ""
echo "  6. To revoke Telegram access for one employee without touching"
echo "     their web/API access: Settings > Administration > Telegram"
echo "     Links, deactivate their row. Their ai.gateway.api.key stays"
echo "     valid for the web frontend - this only cuts the Telegram path."
