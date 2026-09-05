#!/bin/bash
# =============================================================================
# Buzz (roadmap #59) - clone + build locally, install the Hermes<->Buzz
# bridge, and print the exact commands to pilot ONE agent in ONE channel.
# https://github.com/block/buzz - Apache-2.0, self-hostable human+agent
# workspace built on Nostr, by Block (Square/Cash App).
#
# WHAT THIS SCRIPT DOES:
#   1. Clones + builds buzz (relay + buzz-acp + buzz-agent binaries)
#   2. Installs hermes_gateway_mcp_server.py (this repo, buzz_bridge/) and
#      its two Python deps (mcp, requests) into a dedicated venv
#   3. Prints the exact env vars + commands to start a local relay and
#      point buzz-acp at ONE Odoo user's gateway API key
# It does NOT start the relay, does NOT create Nostr keys, and does NOT
# point anything at a real client Odoo box - those are deliberate manual
# steps (see step 4 below and roadmap #59), so a client's real API key
# never ends up baked into a script or shell history by accident.
#
# WHY THE BRIDGE EXISTS INSTEAD OF WIRING BUZZ'S OWN buzz-dev-mcp:
# buzz-acp hands whichever MCP server you configure to the agent process
# it spawns. Buzz's own buzz-dev-mcp gives that agent raw shell + file
# access - exactly the kind of tool that would let an agent reach the
# Odoo host directly and skip the Risk Engine / Approval Object / gateway
# allowlist entirely (roadmap #20, #21, #13/#8). hermes_gateway_mcp_server.py
# gives the agent exactly THREE tools instead - one per gateway endpoint
# (/api/bootstrap, /api/me/capabilities, /api/chat) - and nothing else. See that
# file's own docstring for the full reasoning.
#
# ALSO WORTH KNOWING (found while wiring this up, not in the original
# pitch): the choice of AGENT BIN matters just as much as the choice of
# MCP server. If you point BUZZ_ACP_AGENT_BIN at Claude Code, Codex, or
# Goose instead of buzz-agent, those agent CLIs bring their OWN built-in
# shell/file tools regardless of what you pass via BUZZ_ACP_MCP_SERVER -
# so avoiding buzz-dev-mcp alone is not enough, the agent binary itself
# has to be one with no built-in tools of its own. That's why step 4
# below uses buzz-agent (Block's own "minimal ACP-compliant agent... MCP
# servers (your tools)" per its docs) - it only gets capabilities you
# explicitly hand it via --mcp-server, nothing baked in.
#
# Also still true as of this writing: Buzz's desktop client is v0.4.x,
# there's no mobile app yet, and Block's own docs say git hosting /
# workflow approval gates are unfinished. Treat this as a single-channel
# pilot, not delivery infrastructure, until that changes.
#
# Usage:
#   ./10_setup_buzz.sh
# =============================================================================
set -e

INSTALL_DIR="/opt/buzz"
BRIDGE_DIR="/opt/buzz-bridge"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== [1/4] Cloning block/buzz ==="
if [ ! -d "${INSTALL_DIR}" ]; then
  git clone https://github.com/block/buzz.git "${INSTALL_DIR}"
fi
cd "${INSTALL_DIR}"

echo "=== [2/4] Building (hermit toolchain + just) ==="
. ./bin/activate-hermit
just setup
just build

echo "=== [3/4] Locating buzz-relay / buzz-acp / buzz-agent binaries ==="
BUZZ_BIN_DIR=""
for candidate in target/release target/debug; do
  if [ -x "${candidate}/buzz-relay" ]; then
    BUZZ_BIN_DIR="${candidate}"
    break
  fi
done
if [ -z "${BUZZ_BIN_DIR}" ]; then
  echo "Could not find a built buzz-relay binary under target/release or"
  echo "target/debug - check the 'just build' output above for errors."
  exit 1
fi
echo "Found binaries in ${INSTALL_DIR}/${BUZZ_BIN_DIR}"
for bin in buzz-relay buzz-acp buzz-agent buzz-cli buzz-admin; do
  if [ -x "${BUZZ_BIN_DIR}/${bin}" ]; then
    echo "  ok  ${bin}"
  else
    echo "  MISSING  ${bin} (not built - some steps below may not apply)"
  fi
done

echo "=== [4/4] Installing the Hermes<->Buzz bridge (hermes_gateway_mcp_server.py) ==="
mkdir -p "${BRIDGE_DIR}"
cp "${SCRIPT_DIR}/buzz_bridge/hermes_gateway_mcp_server.py" "${BRIDGE_DIR}/"
if [ ! -d "${BRIDGE_DIR}/venv" ]; then
  python3 -m venv "${BRIDGE_DIR}/venv"
fi
"${BRIDGE_DIR}/venv/bin/pip" install --quiet --upgrade pip
"${BRIDGE_DIR}/venv/bin/pip" install --quiet mcp requests

echo ""
echo "Build + bridge install done. Nothing was started and no Odoo"
echo "credential was touched. Manual steps before piloting for real"
echo "(do NOT skip - see header of this script and roadmap #59):"
echo ""
echo "  1. Create ONE Odoo API key for the specific user this agent"
echo "     identity will act as (Settings > Technical > AI Gateway API"
echo "     Keys, or reuse a key from onboarding/onboard_from_excel.py -"
echo "     #36/#37). Never share one key across multiple agent identities."
echo ""
echo "  2. Create ONE Nostr keypair for this agent identity - never one"
echo "     shared keypair for every employee/agent. This mirrors roadmap"
echo "     #19 (Agent Identity): one Hermes-identity <-> one Odoo API key"
echo "     <-> one Nostr key, always."
echo "         ${INSTALL_DIR}/${BUZZ_BIN_DIR}/buzz-admin generate-key"
echo ""
echo "  3. Start a local relay for the pilot (separate terminal):"
echo "         cd ${INSTALL_DIR} && just dev"
echo ""
echo "  4. Start buzz-acp pointed at the bridge and buzz-agent - NOT at"
echo "     buzz-dev-mcp and NOT at Claude Code/Codex/Goose (see header"
echo "     above for why the agent binary choice matters too):"
echo ""
echo "         export ODOO_GATEWAY_URL=https://<this-client's-odoo-host>"
echo "         export ODOO_GATEWAY_API_KEY=<the key from step 1>"
echo ""
echo "         ${INSTALL_DIR}/${BUZZ_BIN_DIR}/buzz-acp \\"
echo "             --private-key <nsec from step 2> \\"
echo "             --relay-url ws://localhost:8080 \\"
echo "             --agent-bin ${INSTALL_DIR}/${BUZZ_BIN_DIR}/buzz-agent \\"
echo "             --mcp-server ${BRIDGE_DIR}/venv/bin/python,${BRIDGE_DIR}/hermes_gateway_mcp_server.py"
echo ""
echo "     (buzz-agent itself also needs its own small-model LLM"
echo "     credential, e.g. ANTHROPIC_API_KEY for a cheap/fast model - "
echo "     that key only drives the tiny 'which of my 3 tools do I call'"
echo "     loop inside buzz-agent, it is a SEPARATE credential from the"
echo "     Odoo gateway key above and never touches Odoo directly.)"
echo ""
echo "  5. Invite this agent identity to exactly ONE private channel and"
echo "     confirm every gateway_bootstrap/gateway_capabilities/gateway_chat call"
echo "     shows up in Settings > Administration > AI Gateway Audit Log,"
echo "     same as any other gateway caller, before considering this for"
echo "     anything beyond a single pilot channel."
