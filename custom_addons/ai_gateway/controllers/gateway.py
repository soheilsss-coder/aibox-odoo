import json
import logging
import os
import re
import time

from odoo import api, http
from odoo.http import request
from odoo.exceptions import AccessError, UserError
from odoo.sql_db import db_connect
from .rate_limit import check as _shared_rate_limit, blocked as _shared_rate_blocked
from .output_firewall import scrub_public_text, scrub_public_payload
from odoo.addons.ai_gateway.models.chat_queue import get_chat_pool, get_global_chat_gate
from odoo.addons.ai_gateway.models.inference_config import classify_request
from werkzeug.wrappers import Response

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# In production, set the AI_GATEWAY_ALLOWED_ORIGIN environment variable
# to your actual frontend's origin (e.g. https://app.yourcompany.com).
# Defaults to '*' (any origin) for local development/demo convenience -
# lock this down before selling/exposing this beyond your own testing.
_ALLOWED_ORIGIN = os.environ.get("AI_GATEWAY_ALLOWED_ORIGIN")
if not _ALLOWED_ORIGIN and os.environ.get("AI_GATEWAY_ENV", "development") == "production":
    raise RuntimeError("AI_GATEWAY_ALLOWED_ORIGIN is required in production")
_ALLOWED_ORIGIN = _ALLOWED_ORIGIN or ("http://localhost:5173" if os.environ.get("AI_GATEWAY_ENV", "development") != "production" else None)
if os.environ.get("AI_GATEWAY_ENV", "development") == "production" and (not _ALLOWED_ORIGIN or _ALLOWED_ORIGIN == "*"):
    raise RuntimeError("AI_GATEWAY_ALLOWED_ORIGIN must be a concrete HTTPS origin in production")
_ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in (os.environ.get("AI_GATEWAY_ALLOWED_ORIGINS") or _ALLOWED_ORIGIN or "").split(",")
    if origin.strip()
}
_ALLOW_TRYCLOUDFLARE = os.environ.get("AI_GATEWAY_ALLOW_TRYCLOUDFLARE", "0") == "1"
_TRYCLOUDFLARE_RE = re.compile(r"^https://[A-Za-z0-9-]+\.trycloudflare\.com$")


def _origin_allowed(origin):
    origin = (origin or "").rstrip("/")
    if not origin:
        return True
    if origin in _ALLOWED_ORIGINS:
        return True
    return bool(_ALLOW_TRYCLOUDFLARE and _TRYCLOUDFLARE_RE.match(origin))


def _cors_origin():
    origin = request.httprequest.headers.get("Origin", "") if request else ""
    origin = origin.rstrip("/")
    return origin if origin and _origin_allowed(origin) else _ALLOWED_ORIGIN


def _cors_headers():
    return [
        ("Access-Control-Allow-Origin", _cors_origin()),
        ("Access-Control-Allow-Credentials", "true"),
        ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
        ("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization, X-CSRF-Token"),
    ]


_CORS_HEADERS = [
    ("Access-Control-Allow-Origin", _ALLOWED_ORIGIN),
    ("Access-Control-Allow-Credentials", "true"),
    ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
    ("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization, X-CSRF-Token"),
]


def _scoped_user_env(user):
    """Build every customer request environment inside the user's tenant.

    Do not inherit an attacker-controlled ``allowed_company_ids`` context from
    the HTTP request. Multi-company users may switch explicitly in a separate
    audited flow; the API default is the credential owner's current company.
    """
    return request.env(
        user=user.id,
        context={
            "lang": user.lang,
            "allowed_company_ids": [user.company_id.id],
        },
    )


def _json_response(data, status=200):
    return request.make_response(
        json.dumps(data, ensure_ascii=False, default=str),
        headers=[("Content-Type", "application/json; charset=utf-8")] + _cors_headers(),
        status=status,
    )


def _cors_preflight_response():
    return request.make_response("", headers=_cors_headers())


# --- Shared rate limiting ---------------------------------------------
_RATE_LIMIT_PER_MIN = int(os.environ.get("AI_GATEWAY_RATE_LIMIT", "120"))

def _check_rate_limit(api_key):
    return _shared_rate_limit(api_key, _RATE_LIMIT_PER_MIN, prefix="ai:gateway:key")


# --- Failed-authentication flood protection --------------------------
_AUTH_FAIL_LIMIT_PER_MIN = int(os.environ.get("AI_GATEWAY_AUTH_FAIL_LIMIT", "30"))

def _auth_fail_blocked(ip):
    return _shared_rate_blocked(ip, _AUTH_FAIL_LIMIT_PER_MIN, prefix="ai:gateway:authfail")

def _record_auth_failure(ip):
    _shared_rate_limit(ip, _AUTH_FAIL_LIMIT_PER_MIN, prefix="ai:gateway:authfail")


def _client_ip():
    """Best-effort client address for failed-auth flood protection.

    odoo.conf sets proxy_mode=True, so Odoo itself resolves the real
    client IP from X-Forwarded-For (ignoring spoofable incoming XFF
    values) and request.httprequest.remote_addr is already the correct
    address.
    """
    return request.httprequest.remote_addr or ""


def _authenticate():
    """Look up the API key and return the real Odoo user it belongs to.

    Accepts the key from either of two places, since some frontend
    builders/proxies (Lovable, Emergent, etc.) strip custom headers:
      1. X-API-Key header (preferred)
      2. Authorization: Bearer <key> header

    NOTE: query-string credentials are permanently disabled; use authentication headers only.

    Every endpoint then executes AS that user, so Odoo's own
    permissions/record rules apply exactly as they do in the normal web
    client - no separate permission system to maintain in the gateway.

    Returns (user_or_None, api_key_or_None, ip_blocked). Callers must
    check ip_blocked (v19, roadmap #50) before treating a plain "no
    user" as an ordinary invalid key - see the note above.
    """
    method = request.httprequest.method.upper()
    origin = request.httprequest.headers.get("Origin", "")
    if method not in ("GET", "HEAD", "OPTIONS") and origin and not _origin_allowed(origin):
        return None, None, False

    ip = _client_ip()
    if _auth_fail_blocked(ip):
        return None, None, True

    session_token = request.httprequest.cookies.get("ai_session", "").strip()
    if session_token and "ai.gateway.session" in request.env:
        # API routes deliberately disable the framework CSRF mechanism because
        # they also support header-authenticated clients.  A cookie-authenticated
        # browser request therefore uses a session-bound double-submit token.
        # Do not accept a mutation with only the HttpOnly session cookie.
        csrf_token = request.httprequest.headers.get("X-CSRF-Token", "")
        require_csrf = method not in ("GET", "HEAD", "OPTIONS")
        session = request.env["ai.gateway.session"].sudo().authenticate_token(
            session_token, csrf_token=csrf_token, require_csrf=require_csrf,
        )
        if session:
            return session.user_id, session_token, False

    api_key = request.httprequest.headers.get("X-API-Key", "")
    if not api_key:
        auth_header = request.httprequest.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:]
    api_key = api_key.strip()
    if not api_key:
        _record_auth_failure(ip)
        return None, None, False

    key_rec = request.env["ai.gateway.api.key"].sudo().authenticate_secret(api_key)
    if not key_rec:
        _record_auth_failure(ip)
        return None, None, False
    return key_rec.user_id, api_key, False


_ALLOWED_OPERATIONS = {
    "fields",
    "search_read",
    "read",
    "create",
    "write",
    "unlink",
    "search_count",
    "get_views",
}

# Metadata-only operations never touch business data, so they don't
# need a policy-table entry - gating them adds friction with no real
# security benefit.
_POLICY_EXEMPT_OPERATIONS = {"fields", "get_views"}


def _check_policy(env, model, operation):
    """Deny-by-default allowlist, active only if the optional
    ai_business_tools module is installed (soft dependency - ai_gateway
    still works standalone without it). Checked BEFORE Odoo's own ACL,
    so a model/operation missing from the allowlist is refused even if
    Odoo's ACL would otherwise have permitted it - this is a second,
    independent gate, not a replacement for Odoo's own permissions."""
    if operation in _POLICY_EXEMPT_OPERATIONS:
        return None
    if "ai.gateway.model.policy" not in env:
        return {"error": "gateway policy module is not installed; generic RPC is disabled"}
    if not env["ai.gateway.model.policy"].is_allowed(model, operation):
        return {"error": f"'{model}.{operation}' is not on the gateway allowlist"}
    return None


def _audit(env, user_id, source, action, payload=None, success=True, error_message=None, duration_ms=None, token_count=None):
    if "ai.gateway.audit.log" not in env:
        return
    env["ai.gateway.audit.log"].log(
        user_id=user_id, source=source, action=action,
        payload=payload, success=success, error_message=error_message,
        duration_ms=duration_ms, token_count=token_count,
    )


def _estimate_tokens(*texts):
    """Honest token estimate for audit/reporting. The underlying
    odoo-llm framework never surfaces real provider usage through
    thread.generate(), so until that changes this is a documented
    estimate (~4 chars/token, in line with the provider/BP encoder)
    - the label is explicit in the report, never presented as exact."""
    total = 0
    for text in texts:
        if text:
            total += max(1, len(str(text)) // 4)
    return total


def _is_privileged(env, user):
    """Same privileged set as the audit log's own full-access record
    rule (security/audit_log_rules.xml) - kept in sync deliberately:
    whoever can see everyone's audit trail is also who should see the
    aggregate metrics derived from it."""
    if user.has_group("base.group_system"):
        return True
    for xmlid in ("ai_business_tools.role_executive", "ai_business_tools.role_system_admin",
                  "ai_business_tools.role_security"):
        group = env.ref(xmlid, raise_if_not_found=False)
        if group and group in user.groups_id:
            return True
    return False


def _active_profile_section(env, section_name):
    if "ai.customer.configuration.profile" not in env:
        return {}
    try:
        profile = env["ai.customer.configuration.profile"].active_for_company(env.company)
        sections = profile.runtime_config().get("sections", {}) if profile else {}
        value = sections.get(section_name, {})
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001
        _logger.exception("Could not read active customer profile section")
        return {}


def _select_assistant(env, message, has_attachment=False):
    """Select a certified assistant for the workload without exposing routing data.

    The third-party thread API binds generation to an ``llm.assistant`` record,
    so routing is implemented by choosing the assistant/model record before a
    thread is created. If no certified profile is available, production
    fails closed; only development/legacy mode may use the configured
    compatibility assistant. No unreviewed model is auto-created or
    silently promoted.
    """
    budget = classify_request(message, has_attachment=has_attachment)
    Assistant = env["llm.assistant"]
    agent_policy = _active_profile_section(env, "agent")
    assistant_name = str(agent_policy.get("assistant_name") or agent_policy.get("agent_name") or "Company Assistant").strip()
    base_domain = [("name", "=", assistant_name), ("active", "=", True)]
    preferred_model = str(agent_policy.get("model") or "").strip()
    if preferred_model:
        preferred = Assistant.search(base_domain + [("model_id.name", "=", preferred_model)], limit=1)
        if preferred:
            return preferred, budget
    if "ai.model.router" in env:
        try:
            profile = env["ai.model.router"].route(
                purpose=budget.purpose,
                requires_vision=budget.requires_vision,
                latency_budget_ms=budget.latency_budget_ms,
                requires_tools=budget.requires_tools,
            )
            candidate = Assistant.search(
                base_domain + [("model_id.name", "=", profile.model_id)], limit=1
            )
            if candidate:
                return candidate, budget
            if os.environ.get("AI_GATEWAY_ENV", "development") == "production":
                return Assistant.browse(), budget
        except Exception:
            # Production must not silently downgrade to an unbenchmarked
            # assistant. Development/legacy databases retain an explicit
            # compatibility path so upgrades remain usable before promotion.
            if os.environ.get("AI_GATEWAY_ENV", "development") == "production":
                return Assistant.browse(), budget
    assistant = Assistant.search(base_domain, limit=1)
    if not assistant:
        # Upgrade compatibility for databases created before the assistant
        # activation data fix. Do not create or select an arbitrary assistant.
        assistant = Assistant.search([("name", "=", "Company Assistant")], limit=1)
    return assistant, budget


def _agent_tools(env, assistant):
    """Return tools attached to the installed-module Company Assistant.

    The assistant record is deliberately the source of the third-party
    framework's tool catalog, while the binding model is the source of truth
    for which installed modules currently own that catalog. A binding does
    not grant permissions; the caller-specific risk/capability intersection
    happens immediately after this helper returns.
    """
    if "ai.integration.agent.module" not in env:
        return assistant.tool_ids
    try:
        Binding = env["ai.integration.agent.module"].sudo()
        # The cron is the normal path. This idempotent refresh closes the
        # small install-to-cron window without asking an administrator to
        # press a second sync button.
        Binding.refresh_if_stale()
        return Binding.tool_ids_for_agent(assistant)
    except Exception:  # noqa: BLE001
        # Fail closed: stale assistant tools must not survive a broken module
        # connection and become an accidental capability path.
        _logger.exception("Could not resolve installed-module tools for the agent")
        return None


def _run_chat_env(env, message, thread_id=None, attachment_ids=None):
    """Business logic for one assistant turn, executed wholly as the
    environment's user (env.uid).

    Shared by the /api/chat route, /api/chat/stream and the Telegram
    bridge. All auth/rate-limit gating stays in the callers; this is
    the single place that decides how a turn is generated, secured and
    audited. Kept env-parameterized so it can run either in the request
    transaction or (when queued) on a worker thread with its own cursor.

    Returns {"thread_id": ..., "reply": ...} on success or an
    {"error": <generic message>} dict on failure - internal exception
    detail is kept in the audit log/server log, never returned raw to
    the client.
    """
    t0 = time.time()
    user_id = env.uid
    assistant, budget = _select_assistant(
        env, message, has_attachment=bool(attachment_ids)
    )
    if not assistant:
        return {"error": "assistant is not configured"}

    # A personal identity gives each user a durable workspace/profile without
    # creating a second unrestricted agent. Authorization, tools and model
    # selection remain bound to the shared Company Assistant and this user.
    personal_identity = False
    if "ai.gateway.agent.identity" in env:
        personal_identity = env["ai.gateway.agent.identity"].sudo().ensure_personal(env.user)

    # v19 (roadmap #50) - CLOSED GAP: this used to accept ANY
    # thread_id the client sent and just check .exists(), with no
    # ownership check. llm.thread is not in this project's own
    # custom_addons (it comes from the third-party odoo-llm
    # framework, source not available to audit here), so whether it
    # ships a "users only see their own threads" ir.rule by default
    # could not be confirmed either way - and getting this wrong
    # would let any authenticated gateway user read/continue a
    # DIFFERENT user's private conversation with the assistant
    # simply by guessing/incrementing an integer id. create_uid is
    # a standard field on every Odoo model (not specific to
    # llm.thread), so this check does not depend on that unaudited
    # framework having implemented row-level security itself.
    thread = False
    if thread_id:
        candidate = env["llm.thread"].browse(int(thread_id))
        if candidate.exists() and candidate.create_uid.id == user_id:
            thread = candidate
        elif candidate.exists():
            _audit(env, user_id, "chat", "chat_thread_ownership_denied",
                   {"requested_thread_id": thread_id}, success=False,
                   error_message="thread belongs to a different user")

    # Create a new thread only when the caller did not supply an
    # existing thread owned by them. The previous implementation had
    # the create block outside this branch, silently replacing every
    # continuation with a new thread and breaking conversation memory.
    # Resolve the installed-module catalog once per turn. The returned tools
    # are the agent connection, not user authorization; the latter is applied
    # below for both new and existing threads.
    agent_tools = _agent_tools(env, assistant)
    if agent_tools is None:
        _audit(env, user_id, "chat", "chat_agent_module_connection_failed", {
            "assistant_id": assistant.id,
        }, success=False, error_message="installed-module agent catalog unavailable")
        return {"error": "assistant module connections are unavailable"}
    thread_values = {}
    if personal_identity and "personal_agent_identity_id" in env["llm.thread"]._fields:
        thread_values["personal_agent_identity_id"] = personal_identity.id
    if not thread:
        provider = assistant.provider_id or assistant.model_id.provider_id
        if not provider or not assistant.model_id:
            _audit(env, user_id, "chat", "chat_provider_not_configured", {
                "assistant_id": assistant.id,
            }, success=False, error_message="assistant has no provider/model")
            return {"error": "assistant is not configured with a provider/model"}
        allowed_tools = agent_tools
        if "ai.gateway.tool.risk" in env:
            allowed_ids = set(env["ai.gateway.tool.risk"].allowed_tool_ids_for_user(env.user))
            allowed_tools = agent_tools.filtered(lambda tool: tool.id in allowed_ids)
        thread_values.update({
            "assistant_id": assistant.id,
            "provider_id": provider.id,
            "model_id": assistant.model_id.id,
            "tool_ids": [(6, 0, allowed_tools.ids)],
        })
        thread = env["llm.thread"].create(thread_values)
    elif thread_values and thread.personal_agent_identity_id != personal_identity:
        # Existing threads are already ownership-checked above. Refresh only
        # the profile link; never replace the shared assistant or its tools.
        thread.write(thread_values)

    # Defense-in-depth: every thread gets the intersection of the installed
    # module-agent connection and this user's risk/capability allowlist.
    # Generic framework CRUD tools are never exposed through chat.
    if "ai.gateway.tool.risk" in env:
        allowed_ids = set(env["ai.gateway.tool.risk"].allowed_tool_ids_for_user(env.user))
        allowed_ids.intersection_update(agent_tools.ids)
        allowed_tools = thread.tool_ids.filtered(lambda t: t.id in allowed_ids)
        allowed_tools |= env["llm.tool"].browse(sorted(allowed_ids))
        thread.write({"tool_ids": [(6, 0, allowed_tools.ids)]})

    # Attachments are persisted on a mail.message belonging to this exact
    # user-owned thread. The file-reader/vision tools discover attachments
    # from the thread's mail messages, so every ingress (web, Telegram,
    # future channels) shares the same attachment security boundary.
    if attachment_ids:
        attachments = env["ir.attachment"].sudo().browse(attachment_ids).exists()
        if len(attachments) != len(set(attachment_ids)):
            return {"error": "one or more attachments do not exist"}
        # Never let a caller attach an object belonging to another user
        # merely by guessing its integer id. Existing thread attachments
        # are acceptable only when that thread is owned by the same user;
        # newly ingested channel attachments are owned by create_uid.
        for attachment in attachments:
            owned = attachment.create_uid.id == user_id
            linked_thread = attachment.res_model == "llm.thread" and attachment.res_id == thread.id
            if not (owned or linked_thread):
                _audit(env, user_id, "chat", "attachment_ownership_denied", {"attachment_id": attachment.id}, success=False)
                return {"error": "access denied: attachment does not belong to this user/thread"}
        attachments.write({"res_model": "llm.thread", "res_id": thread.id})
        thread.message_post(body=message or "[attachment]", attachment_ids=attachments.ids)

    # Propagate the owning thread into tool execution so explicit memory
    # writes can bind their source quote to the current user message.
    thread = thread.with_context(memory_source_thread_id=thread.id)
    try:
        list(thread.generate(user_message_body=message or "لطفاً فایل ضمیمه را بررسی کن."))
    except Exception as exc:  # noqa: BLE001
        _audit(env, user_id, "chat", "chat", {"message": message, "purpose": budget.purpose},
               success=False, error_message=str(exc),
               duration_ms=int((time.time() - t0) * 1000),
               token_count=_estimate_tokens(message))
        return {"error": "generation failed, check server logs for details"}

    # Candidate memory extraction is asynchronous and source-linked. It is
    # deliberately enqueued only after the user turn has been accepted and
    # generated; the worker never changes the assistant response or blocks
    # this request. Candidates remain unconfirmed until the user explicitly
    # saves/approves a fact.
    if message and "ai.agent.memory.fact.job" in env:
        user_messages = env["mail.message"].sudo().search(
            [
                ("model", "=", "llm.thread"),
                ("res_id", "=", thread.id),
                ("author_id", "=", env.user.partner_id.id),
            ],
            order="id desc",
            limit=5,
        )
        if user_messages:
            env["ai.agent.memory.fact.job"].sudo().enqueue(
                user_messages[0], user=env.user, thread_id=thread.id,
            )

    last_message = env["mail.message"].search(
        [("model", "=", "llm.thread"), ("res_id", "=", thread.id)],
        order="id desc",
        limit=1,
    )
    _audit(env, user_id, "chat", "chat", {"message": message, "purpose": budget.purpose}, success=True,
           duration_ms=int((time.time() - t0) * 1000),
           token_count=_estimate_tokens(message, last_message.body))
    reply_html = last_message.body or ""
    reply_text = scrub_public_text(re.sub(r"<[^>]+>", "", reply_html).strip())

    return {
        "thread_id": thread.id,
        "reply": reply_text,
        "personal_agent": {
            "label": "دستیار شخصی شما",
            "shared_core": True,
        },
    }


def _run_chat(user, message, thread_id=None, attachment_ids=None):
    """Compatibility wrapper for integrations that call the shared chat core.

    Use the same detached cursor and global capacity lease as HTTP chat so
    Telegram cannot bypass concurrency protection by entering the old direct
    helper.
    """
    return _run_chat_detached(request.env.cr.dbname, user.id, message, thread_id, attachment_ids)


def _run_chat_detached(dbname, user_id, message, thread_id=None, attachment_ids=None):
    """Run one assistant turn on its OWN database cursor, so the turn
    can be executed by a pool worker thread without touching the
    request thread's transaction (which belongs to a different,
    possibly idle query). Used only when the chat pool queues the job;
    the idle fast path keeps running inline with the request env."""
    lease = get_global_chat_gate().acquire()
    if lease is False:
        return {"error": "assistant capacity is currently full, try again shortly"}
    cr = None
    try:
        cr = db_connect(dbname).cursor()
        env = api.Environment(cr, user_id, {})
        result = _run_chat_env(env, message, thread_id, attachment_ids)
        cr.commit()
        return result
    except Exception:  # noqa: BLE001
        try:
            if cr is not None:
                cr.rollback()
        except Exception:  # noqa: BLE001
            pass
        _logger.exception("Detached chat turn failed")
        return {"error": "generation failed, check server logs for details"}
    finally:
        try:
            if cr is not None:
                cr.close()
        finally:
            get_global_chat_gate().release(lease)


def _run_chat_bounded(env, message, thread_id=None, attachment_ids=None):
    """Run non-HTTP callers through the same cross-process capacity lease."""
    lease = get_global_chat_gate().acquire()
    if lease is False:
        return {"error": "assistant capacity is currently full, try again shortly"}
    try:
        return _run_chat_env(env, message, thread_id, attachment_ids)
    except Exception:  # noqa: BLE001 - callers receive the public-safe error
        return {"error": "generation failed, check server logs for details"}
    finally:
        get_global_chat_gate().release(lease)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class AiGatewayController(http.Controller):

    @http.route("/api/tool/execute", type="json", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def execute_tool(self, **params):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        user, api_key, ip_blocked = _authenticate()
        if ip_blocked:
            return {"error": "too many failed authentication attempts from this address, try again shortly"}
        if not user:
            return {"error": "invalid or missing API key"}
        if not _check_rate_limit(api_key):
            return {"error": "rate limit exceeded, try again shortly"}
        tool_name = (params.get("tool_name") or "").strip()
        args = params.get("args") or {}
        if not tool_name:
            return {"error": "'tool_name' is required"}
        env = _scoped_user_env(user)
        try:
            result = env["ai.gateway.execution.gate"].execute(tool_name, args)
            return {"status": "done", "result": scrub_public_payload(result)}
        except Exception as exc:  # noqa: BLE001
            _audit(env, user.id, "tool", tool_name, {"args": args}, success=False, error_message=str(exc))
            return {"error": "operation failed, check server logs for details"}


    @http.route("/api/bootstrap", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def bootstrap(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()

        user, api_key, ip_blocked = _authenticate()
        if ip_blocked:
            return _json_response({"error": "too many failed authentication attempts from this address, try again shortly"}, status=429)
        if not user:
            return _json_response({"error": "invalid or missing API key"}, status=401)
        if not _check_rate_limit(api_key):
            return _json_response({"error": "rate limit exceeded, try again shortly"}, status=429)

        env = _scoped_user_env(user)

        top_menus = env["ir.ui.menu"].search(
            [("parent_id", "=", False)], order="sequence"
        )

        def serialize_menu(menu):
            action = None
            if menu.action:
                # Bootstrap is a customer-facing contract. Do not expose ORM
                # model names or internal action types to the browser; the
                # frontend receives only a navigable/visible marker.
                action = {"available": True}
            children = env["ir.ui.menu"].search(
                [("parent_id", "=", menu.id)], order="sequence"
            )
            return {
                "id": menu.id,
                "name": menu.name,
                "action": action,
                "children": [serialize_menu(c) for c in children],
            }

        menus = [serialize_menu(m) for m in top_menus]

        def has_content(m):
            return bool(m["action"]) or any(has_content(c) for c in m["children"])
        menus = [m for m in menus if has_content(m)]

        # Expose only product labels from the central integration registry.
        # The technical module inventory is an admin/control-plane concern and
        # must not leak through the customer bootstrap response.
        available_domains = []
        if "ai.control.module" in env:
            available_domains = env["ai.control.module"].sudo().search(
                [("state", "=", "installed"), ("active", "=", True)],
                order="name",
            ).mapped("name")

        return _json_response({
            "user": {"id": user.id, "name": user.name, "login": user.login},
            "company": {"id": env.company.id, "name": env.company.name},
            "lang": env.user.lang or "en_US",
            "timezone": env.user.tz or "UTC",
            "menus": menus,
            "available_domains": available_domains,
        })

    @http.route("/api/health", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def health(self, **kwargs):
        """Unauthenticated liveness check (roadmap #48) - deliberately
        leaks NO business data, just "is this box up and can it talk
        to Postgres", so it's safe to point an external uptime monitor
        (UptimeRobot, a load-balancer health check, etc.) at this with
        no API key at all."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        try:
            request.env.cr.execute("SELECT 1")
            db_ok = request.env.cr.fetchone() == (1,)
        except Exception:  # noqa: BLE001
            db_ok = False
        return _json_response({"status": "ok" if db_ok else "degraded", "database": db_ok},
                               status=200 if db_ok else 503)

    @http.route("/api/metrics", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def metrics(self, **kwargs):
        """Aggregate request-volume/error-rate metrics derived from
        the audit log (roadmap #48). Requires a real API key belonging
        to a privileged role - unlike /api/health, this DOES reveal
        something about usage patterns (which action names are called
        most), so it is not left open."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()

        user, api_key, ip_blocked = _authenticate()
        if ip_blocked:
            return _json_response({"error": "too many failed authentication attempts from this address, try again shortly"}, status=429)
        if not user:
            return _json_response({"error": "invalid or missing API key"}, status=401)
        if not _check_rate_limit(api_key):
            return _json_response({"error": "rate limit exceeded, try again shortly"}, status=429)

        env = _scoped_user_env(user)
        if not _is_privileged(env, user):
            return _json_response({"error": "access denied: metrics are restricted to privileged roles"}, status=403)
        if "ai.gateway.audit.log" not in env:
            return _json_response({"error": "ai_business_tools is not installed"}, status=501)

        snapshot = env["ai.gateway.audit.log"].sudo().observability_snapshot()
        snapshot["chat_queue"] = get_chat_pool().snapshot()
        snapshot["global_concurrency_lease"] = {
            "enabled": get_global_chat_gate().enabled,
            "capacity": get_global_chat_gate().capacity,
        }
        return _json_response(snapshot)

    @http.route("/api/reports/tokens", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def token_report(self, **kwargs):
        """Token usage report (daily / user / company) derived from the
        audit log - privileged like /api/metrics. The numbers are the
        gateway's explicit ESTIMATE (chars/4), not provider-reported
        usage, so they must never be presented as exact billing data."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()

        user, api_key, ip_blocked = _authenticate()
        if ip_blocked:
            return _json_response({"error": "too many failed authentication attempts from this address, try again shortly"}, status=429)
        if not user:
            return _json_response({"error": "invalid or missing API key"}, status=401)
        if not _check_rate_limit(api_key):
            return _json_response({"error": "rate limit exceeded, try again shortly"}, status=429)

        env = _scoped_user_env(user)
        if not _is_privileged(env, user):
            return _json_response({"error": "access denied: token usage is restricted to privileged roles"}, status=403)
        if "ai.gateway.audit.log" not in env:
            return _json_response({"error": "ai_business_tools is not installed"}, status=501)
        try:
            days = int(kwargs.get("days") or 30)
        except (TypeError, ValueError):
            days = 30
        days = max(1, min(days, 365))
        return _json_response(env["ai.gateway.audit.log"].sudo().token_usage_report(days))

    @http.route("/api/rpc", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def rpc(self, **params):
        """Permanent tombstone for the legacy generic ORM/RPC surface.

        There is deliberately no feature flag, environment override, model
        lookup, or fallback implementation behind this route.
        """
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        return _json_response({
            "error": "generic /api/rpc is permanently disabled; use named capabilities"
        }, status=410)

    @http.route("/api/chat", type="json", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def chat(self, **params):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()

        # Chat is a semantic capability. It must remain available when
        # Generic ORM/RPC is permanently disabled; chat uses named tools only.
        user, api_key, ip_blocked = _authenticate()
        if ip_blocked:
            return {"error": "too many failed authentication attempts from this address, try again shortly"}
        if not user:
            return {"error": "invalid or missing API key"}
        if not _check_rate_limit(api_key):
            return {"error": "rate limit exceeded, try again shortly"}

        message = params.get("message")
        thread_id = params.get("thread_id")
        attachment_ids = params.get("attachment_ids") or []
        if isinstance(attachment_ids, str):
            try:
                attachment_ids = json.loads(attachment_ids)
            except Exception:
                attachment_ids = []
        if not isinstance(attachment_ids, list) or any(not str(x).isdigit() for x in attachment_ids):
            return {"error": "attachment_ids must be a list of attachment ids"}
        attachment_ids = [int(x) for x in attachment_ids]
        if not message and not attachment_ids:
            return {"error": "'message' or attachment_ids is required"}

        # Turn execution lives in the module-level _run_chat_env() core
        # so the Telegram bridge reuses the exact same business logic
        # (thread ownership, tool allowlist, attachment ownership, audit
        # trail) without an HTTP loopback or an API-key round-trip.
        # Concurrency is bounded by the chat worker pool: while a heavy
        # turn is running, the next request queues in FIFO (or fails
        # fast with a busy error when the queue is full) instead of
        # every parallel request hitting the single GPU at once.
        dbname = request.env.cr.dbname
        # Always use the detached cursor path, including the idle fast path.
        # That makes the Redis lease cover every request across all Odoo
        # worker processes instead of only requests that entered the queue.
        ok, result = get_chat_pool().submit(
            lambda: _run_chat_detached(dbname, user.id, message, thread_id, attachment_ids)
        )
        if not ok:
            return {"error": result}
        return result

    @http.route("/api/chat/stream", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def chat_stream(self, **params):
        """Progressive (SSE) delivery of one assistant turn.

        IMPORTANT, honest scope: the odoo-llm framework's thread.generate()
        is blocking and exposes no token/usage streaming, so the server
        emits a 'thinking' event while the turn is generated, then streams
        the final reply in word-sized 'delta' chunks and closes with 'done'.
        The response text is real and complete; only the delivery is
        progressive. True token-level streaming requires replacing
        thread.generate() at runtime certification, not faked here.
        """
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        user, api_key, ip_blocked = _authenticate()
        if ip_blocked:
            return _json_response({"error": "too many failed authentication attempts from this address, try again shortly"}, status=429)
        if not user:
            return _json_response({"error": "invalid or missing API key"}, status=401)
        if not _check_rate_limit(api_key):
            return _json_response({"error": "rate limit exceeded, try again shortly"}, status=429)

        def _sse(event, payload):
            return "event: %s\ndata: %s\n\n" % (event, json.dumps(payload, ensure_ascii=False))

        # Everything this stream needs must be read out of the request BEFORE
        # the generator is handed back to the WSGI server. The generator body
        # is consumed after the request context has been unbound, so touching
        # `request` in there raises RuntimeError('object is not bound') - which
        # used to surface as a bare "invalid request", because the body parse
        # sat inside a catch-all except and swallowed the real error.
        #
        # Reading once, here, while the request is live, also fixes the second
        # half of that bug: for a form-encoded POST the dispatcher has already
        # consumed the body building `request.params`, so `httprequest.data`
        # is empty by the time we get to it. Both sources are accepted now.
        raw = request.httprequest.get_data(as_text=True)
        data = {}
        if raw:
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
        if not data:
            # Form-encoded POST: the body was already consumed building
            # request.params, so the raw bytes are gone. Take them from there.
            data = dict(request.params or {})
        if not isinstance(data, dict):
            return _json_response({"error": "invalid request"}, status=400)

        message = data.get("message")
        thread_id = data.get("thread_id")
        attachment_ids = data.get("attachment_ids") or []
        if not isinstance(attachment_ids, list):
            attachment_ids = []
        attachment_ids = [int(x) for x in attachment_ids if str(x).isdigit()]
        if not message and not attachment_ids:
            return _json_response(
                {"error": "'message' or attachment_ids is required"}, status=400
            )

        # Same bounded worker pool as /api/chat - the heavy turn is
        # queued when the engine is saturated, overflowing requests
        # get the busy error instead of piling up, and the SSE stream
        # still delivers the final reply progressively.
        # Captured as plain values: the worker thread has no request context.
        dbname = request.env.cr.dbname
        user_id = user.id

        def generate():
            yield _sse("thinking", {})
            ok, result = get_chat_pool().submit(
                lambda: _run_chat_detached(dbname, user_id, message, thread_id, attachment_ids)
            )
            if not ok:
                yield _sse("busy", {"error": result})
                return
            if "error" in result:
                yield _sse("error", result)
                return
            for word in re.split(r"(\s+)", result.get("reply") or ""):
                if word:
                    yield _sse("delta", {"text": word})
            yield _sse("done", {
                "thread_id": result.get("thread_id"),
                "personal_agent": result.get("personal_agent"),
            })

        headers = [
            ("Content-Type", "text/event-stream; charset=utf-8"),
            ("Cache-Control", "no-cache"),
            ("X-Accel-Buffering", "no"),
        ] + _cors_headers()
        return Response(generate(), headers=headers)
