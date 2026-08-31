import json
import os
import re
import time

from odoo import api, http
from odoo.http import request
from odoo.exceptions import AccessError, UserError
from odoo.sql_db import db_connect
from .rate_limit import check as _shared_rate_limit, blocked as _shared_rate_blocked
from .chat_queue import get_chat_pool
from .output_firewall import scrub_public_text
from werkzeug.wrappers import Response


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

_CORS_HEADERS = [
    ("Access-Control-Allow-Origin", _ALLOWED_ORIGIN),
    ("Access-Control-Allow-Credentials", "true"),
    ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
    ("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization"),
]


def _json_response(data, status=200):
    return request.make_response(
        json.dumps(data, ensure_ascii=False, default=str),
        headers=[("Content-Type", "application/json; charset=utf-8")] + _CORS_HEADERS,
        status=status,
    )


def _cors_preflight_response():
    return request.make_response("", headers=_CORS_HEADERS)


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
    if method not in ("GET", "HEAD", "OPTIONS") and origin and origin != _ALLOWED_ORIGIN:
        return None, None, False

    ip = _client_ip()
    if _auth_fail_blocked(ip):
        return None, None, True

    session_token = request.httprequest.cookies.get("ai_session", "").strip()
    if session_token and "ai.gateway.session" in request.env:
        session = request.env["ai.gateway.session"].sudo().authenticate_token(session_token)
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
    assistant = env["llm.assistant"].search(
        [("name", "=", "Company Assistant")], limit=1
    )
    if not assistant:
        return {"error": "Company Assistant not found - check AI module install"}

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
    if not thread:
        allowed_tools = assistant.tool_ids
        if "ai.gateway.tool.risk" in env:
            allowed_ids = env["ai.gateway.tool.risk"].allowed_tool_ids_for_user(env.user)
            allowed_tools = assistant.tool_ids.filtered(lambda t: t.id in allowed_ids)
        thread = env["llm.thread"].create({
            "assistant_id": assistant.id,
            "tool_ids": [(6, 0, allowed_tools.ids)],
        })

    # Defense-in-depth: every thread gets a user-specific allowlist.
    # Generic framework CRUD tools are never exposed through chat.
    if "ai.gateway.tool.risk" in env:
        allowed_ids = env["ai.gateway.tool.risk"].allowed_tool_ids_for_user(env.user)
        thread.write({"tool_ids": [(6, 0, [i for i in thread.tool_ids.ids if i in allowed_ids])]})

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

    try:
        list(thread.generate(user_message_body=message or "لطفاً فایل ضمیمه را بررسی کن."))
    except Exception as exc:  # noqa: BLE001
        _audit(env, user_id, "chat", "chat", {"message": message},
               success=False, error_message=str(exc),
               duration_ms=int((time.time() - t0) * 1000),
               token_count=_estimate_tokens(message))
        return {"error": "generation failed, check server logs for details"}

    last_message = env["mail.message"].search(
        [("model", "=", "llm.thread"), ("res_id", "=", thread.id)],
        order="create_date desc",
        limit=1,
    )
    _audit(env, user_id, "chat", "chat", {"message": message}, success=True,
           duration_ms=int((time.time() - t0) * 1000),
           token_count=_estimate_tokens(message, last_message.body))
    reply_html = last_message.body or ""
    reply_text = scrub_public_text(re.sub(r"<[^>]+>", "", reply_html).strip())

    return {
        "thread_id": thread.id,
        "reply": reply_text,
    }


def _run_chat(user, message, thread_id=None, attachment_ids=None):
    """Wrapper for the synchronous (request-env) path - kept so the
    Telegram bridge keeps calling exactly the same signature as before.
    Queued execution uses _run_chat_detached below instead."""
    env = request.env(user=user.id)
    return _run_chat_env(env, message, thread_id, attachment_ids)


def _run_chat_detached(dbname, user_id, message, thread_id=None, attachment_ids=None):
    """Run one assistant turn on its OWN database cursor, so the turn
    can be executed by a pool worker thread without touching the
    request thread's transaction (which belongs to a different,
    possibly idle query). Used only when the chat pool queues the job;
    the idle fast path keeps running inline with the request env."""
    cr = db_connect(dbname).cursor()
    try:
        with api.Environment(cr, user_id, {}) as env:
            result = _run_chat_env(env, message, thread_id, attachment_ids)
        return result
    except Exception:  # noqa: BLE001
        try:
            cr.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {"error": "generation failed, check server logs for details"}


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
        env = request.env(user=user.id)
        try:
            result = env["ai.gateway.execution.gate"].execute(tool_name, args)
            return {"status": "done", "tool": tool_name, "result": result}
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

        env = request.env(user=user.id)

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

        env = request.env(user=user.id)
        if not _is_privileged(env, user):
            return _json_response({"error": "access denied: metrics are restricted to privileged roles"}, status=403)
        if "ai.gateway.audit.log" not in env:
            return _json_response({"error": "ai_business_tools is not installed"}, status=501)

        return _json_response(env["ai.gateway.audit.log"].sudo().observability_snapshot())

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

        env = request.env(user=user.id)
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

        def generate():
            yield _sse("thinking", {})
            try:
                data = json.loads(request.httprequest.data or b"{}")
            except Exception:  # noqa: BLE001
                yield _sse("error", {"error": "invalid request"})
                return
            message = data.get("message")
            thread_id = data.get("thread_id")
            attachment_ids = data.get("attachment_ids") or []
            if not isinstance(attachment_ids, list):
                attachment_ids = []
            attachment_ids = [int(x) for x in attachment_ids if str(x).isdigit()]
            if not message and not attachment_ids:
                yield _sse("error", {"error": "'message' or attachment_ids is required"})
                return
            # Same bounded worker pool as /api/chat - the heavy turn is
            # queued when the engine is saturated, overflowing requests
            # get the busy error instead of piling up, and the SSE stream
            # still delivers the final reply progressively.
            dbname = request.env.cr.dbname
            ok, result = get_chat_pool().submit(
                lambda: _run_chat_detached(dbname, user.id, message, thread_id, attachment_ids)
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
            yield _sse("done", {"thread_id": result.get("thread_id")})

        headers = [
            ("Content-Type", "text/event-stream; charset=utf-8"),
            ("Cache-Control", "no-cache"),
            ("X-Accel-Buffering", "no"),
            ("Access-Control-Allow-Origin", _ALLOWED_ORIGIN),
            ("Access-Control-Allow-Credentials", "true"),
        ]
        return Response(generate(), headers=headers)
