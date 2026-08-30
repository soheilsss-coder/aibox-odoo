"""
Hermes <-> Buzz bridge (roadmap #59) - a minimal MCP (stdio) server that
gives a Buzz-spawned agent exactly THREE tools, one per AI Gateway
endpoint (roadmap #13/#8), and nothing else.

WHY THIS FILE EXISTS: buzz-acp spawns an ACP-compliant agent process
(buzz-agent, or Claude Code / Codex / Goose if you choose one of
those) and can hand it one MCP server's worth of tools via
`--mcp-server` / `BUZZ_ACP_MCP_SERVER`. Buzz ships its own MCP server,
buzz-dev-mcp, which gives an agent raw shell + file-edit access - that
is fine for Buzz's own repo/dev-workflow use case, but it must NEVER
be the MCP server handed to a Hermes-identity agent, because it has no
concept of Odoo's Risk Engine (#20), Approval Object (#21), or gateway
allowlist (ai.gateway.model.policy) - it would let an agent reach the
Odoo host directly and bypass all of that.

This server is the alternative: it forwards to Odoo's real HTTP
endpoints (/api/bootstrap, /api/me/capabilities, /api/chat) using ONE fixed API
key loaded from the environment, and exposes no other capability -
no shell, no filesystem, no arbitrary URLs. Whatever the agent decides
to do, the worst it can do through this bridge is whatever that one
Odoo user's API key (and Odoo's own ACL + the gateway's own allowlist
and Risk Engine) already allows - exactly the same ceiling as the
React frontend has, nothing more.

ONE BRIDGE PROCESS = ONE HERMES IDENTITY. Run one instance of this
script per Odoo user/Nostr keypair pair - never share one API key
across multiple Buzz agent identities (roadmap #19, Agent Identity).

Requires: pip install mcp requests

Environment variables (all required except the timeout):
    ODOO_GATEWAY_URL       e.g. https://client.example.com (no trailing slash)
    ODOO_GATEWAY_API_KEY   this agent identity's ai.gateway.api.key value
                            (Settings > Technical > AI Gateway / the M2M secret store)
    ODOO_GATEWAY_TIMEOUT   optional, seconds, default 30

Wired into buzz-acp via BUZZ_ACP_MCP_SERVER pointing at this script
(see 10_setup_buzz.sh step 4 for the exact invocation).
"""
import os
import sys
from typing import Optional

import requests
from mcp.server.fastmcp import FastMCP

GATEWAY_URL = os.environ.get("ODOO_GATEWAY_URL", "").rstrip("/")
API_KEY = os.environ.get("ODOO_GATEWAY_API_KEY", "")
TIMEOUT = float(os.environ.get("ODOO_GATEWAY_TIMEOUT", "30"))

if not GATEWAY_URL or not API_KEY:
    print(
        "hermes_gateway_mcp_server: ODOO_GATEWAY_URL and ODOO_GATEWAY_API_KEY "
        "must both be set - refusing to start with no way to reach Odoo, or "
        "worse, no fixed identity to run as.",
        file=sys.stderr,
    )
    sys.exit(1)

_session = requests.Session()
_session.headers["X-API-Key"] = API_KEY

mcp = FastMCP("hermes-gateway-bridge")


@mcp.tool()
def gateway_bootstrap() -> dict:
    """Fetch this agent's Odoo identity, company, language, timezone,
    visible menu tree, and installed modules. Call this first in a new
    conversation to learn who you're acting as and what's installed -
    same as /api/bootstrap used by the React frontend."""
    resp = _session.get(f"{GATEWAY_URL}/api/bootstrap", timeout=TIMEOUT)
    return _as_result(resp)


@mcp.tool()
def gateway_capabilities() -> dict:
    """Return the capabilities of this fixed agent identity. The Odoo
    server performs the authorization decision; this is discovery only."""
    resp = _session.get(f"{GATEWAY_URL}/api/me/capabilities", timeout=TIMEOUT)
    return _as_result(resp)


@mcp.tool()
def gateway_chat(message: str, thread_id: Optional[int] = None) -> dict:
    """Send a natural-language request through the same Company Assistant
    and Tool Gateway used by the web frontend. No raw ORM/RPC is exposed
    to Hermes, so authorization, risk and approvals remain centralized."""
    body = {"message": message}
    if thread_id:
        body["thread_id"] = thread_id
    resp = _session.post(f"{GATEWAY_URL}/api/chat", json=body, timeout=TIMEOUT)
    return _as_result(resp)




def _as_result(resp):
    try:
        data = resp.json()
    except ValueError:
        return {"error": f"non-JSON response, status {resp.status_code}: {resp.text[:500]}"}
    if resp.status_code >= 400 and "error" not in data:
        data = {"error": f"HTTP {resp.status_code}: {data}"}
    return data


if __name__ == "__main__":
    mcp.run()
