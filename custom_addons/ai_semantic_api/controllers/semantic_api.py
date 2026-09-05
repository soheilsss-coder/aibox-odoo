"""
Semantic API (roadmap #43-44, extended in phase 7 - #46/#47).

/api/bootstrap and /api/chat (ai_gateway) are the supported product API surfaces.
Generic `/api/rpc` is permanently disabled (HTTP 410) and is not a fallback
for semantic endpoints. This controller therefore exposes only named,
capability-aware business endpoints; anything new must be added as another
named endpoint or reviewed business-tool operation.

Auth, rate limiting, and audit logging are NOT reimplemented here -
they're imported straight from ai_gateway's controller, so there is
exactly one place in the whole project that decides "is this API key
valid" and "log this request", not two copies that could drift apart.

Phase 7 additions (roadmap #46 Admin Console, #47 Document Center):
- Document endpoints gained create/delete/options so the frontend's
  Document Center can do more than browse (item 47's actual scope -
  before this it was a first-pass read-only list, per the old
  frontend/README.md caveat).
- A new /api/admin/* namespace backs the Admin Console (item 46). Every
  route in it calls `_require_privileged()` FIRST, before touching any
  data - the same privileged set (base.group_system / Executive /
  System Admin / Security) that already sees the full audit log
  (ai_business_tools/security/audit_log_rules.xml) and /api/metrics
  (ai_gateway/controllers/gateway.py's `_is_privileged`). No new
  privilege concept was invented for this - it reuses the one that
  already existed, on purpose.
"""
import base64
import json as _json
import logging
import os
import re
from urllib.parse import urlparse

from odoo import fields as odoo_fields
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError, AccessDenied, UserError, ValidationError

from odoo.addons.ai_gateway.controllers.gateway import (
    _authenticate,
    _check_rate_limit,
    _scoped_user_env,
    _json_response,
    _cors_preflight_response,
    _audit,
    _is_privileged,
    _client_ip,
    _auth_fail_blocked,
    _record_auth_failure,
    _CORS_HEADERS,
)
from odoo.addons.ai_gateway.controllers.file_policy import validate_upload, MAX_UPLOAD_BYTES
from odoo.addons.ai_gateway.controllers.output_firewall import scrub_public_text
from werkzeug.wrappers import Response
from urllib.parse import quote as _quote_filename

_logger = logging.getLogger(__name__)


_BRAND_ASSET_MAX_BYTES = 4 * 1024 * 1024
_BRAND_IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
})
_BRAND_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_BRAND_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_BRAND_TEXT_FIELDS = {
    "brand_name", "legal_name", "tagline", "product_title", "brand_domain",
    "support_email", "support_url", "footer_text", "login_message",
    "primary_color", "secondary_color", "accent_color", "background_color",
    "surface_color", "surface_alt_color", "text_color", "text_muted_color",
    "danger_color", "warning_color", "font_family", "border_radius",
}
_BRAND_BOOL_FIELDS = {
    "show_ai_brand", "show_powered_by", "show_module_navigation",
    "support_contact_visible",
}
_BRAND_COLOR_FIELDS = {
    "primary_color", "secondary_color", "accent_color", "background_color",
    "surface_color", "surface_alt_color", "text_color", "text_muted_color",
    "danger_color", "warning_color",
}
_PROFILE_SECTIONS = (
    "role_policy", "capability_policy", "approval_matrix", "document_policy",
    "agent_config", "tool_config", "workflow_config", "feature_config",
)
_BRAND_DEFAULTS = {
    "primary_color": "#4f8cff",
    "secondary_color": "#8b5cf6",
    "accent_color": "#3dd68c",
    "background_color": "#0f1115",
    "surface_color": "#171a21",
    "surface_alt_color": "#1e222b",
    "text_color": "#e8eaed",
    "text_muted_color": "#9aa1ac",
    "danger_color": "#e5484d",
    "warning_color": "#caa23d",
    "font_family": "system",
    "border_radius": "comfortable",
}


def _strict_bool(value, field_name):
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    raise ValidationError("%s must be a boolean." % field_name)


def _decode_brand_asset(payload, base_field, filename_field):
    encoded = payload.get(base_field)
    filename = str(payload.get(filename_field) or "").strip()
    if not encoded or not filename:
        raise ValidationError("%s and %s are required together." % (base_field, filename_field))
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError) as exc:
        raise ValidationError("%s is not valid base64." % base_field) from exc
    upload = validate_upload(filename, raw, max_bytes=_BRAND_ASSET_MAX_BYTES)
    if upload["extension"] not in _BRAND_IMAGE_EXTENSIONS:
        raise ValidationError("Brand assets must be image files.")
    return base64.b64encode(raw).decode("ascii"), upload


def _profile_json_values(profile, include_sections=False):
    values = {
        "id": profile.id,
        "name": profile.name,
        "company_id": profile.company_id.id,
        "state": profile.state,
        "active": profile.active,
        "version": profile.version,
        "compiled_hash": profile.compiled_hash or "",
        "compiled_at": str(profile.compiled_at) if profile.compiled_at else None,
        "activated_by": profile.activated_by_id.name if profile.activated_by_id else None,
        "activated_at": str(profile.activated_at) if profile.activated_at else None,
        "previous_profile_id": profile.previous_profile_id.id if profile.previous_profile_id else None,
        "deployment_result": _json.loads(profile.deployment_result_json or "{}"),
    }
    if include_sections:
        sections = {}
        for section in _PROFILE_SECTIONS:
            field_name = "%s_json" % section
            try:
                parsed = _json.loads(getattr(profile, field_name) or "{}")
            except (TypeError, ValueError):
                parsed = {}
            sections[section] = parsed
        values["sections"] = sections
    return values


def _active_profile_section(env, section_name):
    if "ai.customer.configuration.profile" not in env:
        return {}
    profile = env["ai.customer.configuration.profile"].active_for_company(env.company)
    if not profile:
        return {}
    sections = profile.runtime_config().get("sections", {})
    value = sections.get(section_name, {})
    return value if isinstance(value, dict) else {}


def _profile_values_from_payload(payload, require_name=False):
    allowed = {"name"} | set(_PROFILE_SECTIONS)
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValidationError("unsupported configuration profile fields")
    values = {}
    if require_name and not str(payload.get("name") or "").strip():
        raise ValidationError("profile name is required")
    if "name" in payload:
        name = str(payload["name"] or "").strip()
        if not name or len(name) > 200:
            raise ValidationError("profile name is invalid")
        values["name"] = name
    for section in _PROFILE_SECTIONS:
        if section not in payload:
            continue
        value = payload[section]
        if not isinstance(value, dict):
            raise ValidationError("%s must be a JSON object" % section)
        values["%s_json" % section] = _json.dumps(
            value, sort_keys=True, ensure_ascii=False,
        )
    return values


def _require_auth():
    """Returns (env, error_response_or_None). Every route below starts
    with this - identical auth/rate-limit behavior as /api/rpc and
    /api/chat, just factored out so it isn't retyped per route.

    MERGE NOTE (v21): _authenticate() now returns a 3-tuple
    (user, api_key, ip_blocked) - the security-testing round (roadmap
    #50) added the ip_blocked flag for the failed-auth flood limiter
    in ai_gateway/controllers/gateway.py. This function is the one
    place in ai_semantic_api that calls it, so it's the only place
    that needed updating when the two branches were merged."""
    user, api_key, ip_blocked = _authenticate()
    if ip_blocked:
        return None, _json_response(
            {"error": "too many failed authentication attempts from this address, try again shortly"},
            status=429,
        )
    if not user:
        return None, _json_response({"error": "invalid or missing API key"}, status=401)
    if not _check_rate_limit(api_key):
        return None, _json_response({"error": "rate limit exceeded, try again shortly"}, status=429)
    return _scoped_user_env(user), None


def _require_privileged():
    """Same as _require_auth(), plus the Admin Console's one extra
    rule: only a privileged role may proceed. Returns (env,
    error_response_or_None) - identical calling convention to
    _require_auth() so every /api/admin/* route below reads exactly
    like a non-admin route with one extra check inserted."""
    env, err = _require_auth()
    if err:
        return None, err
    if not _is_privileged(env, env.user):
        return None, _json_response(
            {"error": "access denied: this endpoint is restricted to privileged roles "
                      "(System Admin, Executive, Security)"},
            status=403,
        )
    return env, None


def _read_json_body():
    try:
        body = _json.loads(request.httprequest.data or b"{}")
    except ValueError:
        return None, _json_response({"error": "invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return None, _json_response({"error": "JSON body must be an object"}, status=400)
    return body, None


def _public_capabilities(capabilities):
    """Expose product-level facts, never internal capability/model names."""
    return [{
        "operation": capability.operation,
        "risk_level": capability.risk_level,
    } for capability in capabilities]


class AiSemanticApiController(http.Controller):

    # ------------------------------------------------------------
    # Login with username/password (v24, requested directly - the
    # frontend used to only accept a pre-issued API key pasted in by
    # hand, which is fine for an admin but not for an ordinary
    # employee's day-to-day login screen). This does NOT introduce a
    # second, parallel auth system: it verifies the SAME Odoo
    # login/password every user already has (onboarding sets one -
    # see onboarding/onboard_from_excel.py's `_change_password` call),
    # then hands back that same user's EXISTING ai.gateway.api.key
    # (never creates one here - if a user has none, onboarding was
    # skipped for them, and that's a real setup problem to fix, not
    # something to silently paper over by minting a key from a login
    # route). Every request after this still flows through the one
    # X-API-Key path _authenticate() already handles - this route's
    # only job is trading a password for the key, once.
    #
    # Reuses the SAME IP-keyed failed-auth limiter that already
    # protects the gateway's API-key path (roadmap #50, v19) - a
    # password field is exactly the kind of thing worth guarding
    # against brute-forcing, more so than the 192-bit API keys that
    # limiter was originally built for.
    # ------------------------------------------------------------
    @http.route("/api/login", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def login(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()

        ip = _client_ip()
        if _auth_fail_blocked(ip):
            return _json_response(
                {"error": "too many failed login attempts from this address, try again shortly"},
                status=429,
            )

        body, err = _read_json_body()
        if err:
            return err
        login_id = str(body.get("login") or "").strip()
        password = str(body.get("password") or "")
        if not login_id or not password:
            return _json_response({"error": "login and password are both required"}, status=400)

        try:
            uid = request.session.authenticate(request.db, login_id, password)
        except AccessDenied:
            uid = False

        if not uid:
            _record_auth_failure(ip)
            return _json_response({"error": "invalid email or password"}, status=401)

        # This route is meant to hand back a stateless API key, not a
        # cookie session - drop the Odoo backend session immediately
        # so a login through this API-only screen doesn't also leave a
        # live, full-privilege Odoo backend cookie sitting in the same
        # browser. keep_db=True: don't also clear which database this
        # browser talks to on a single-DB deployment.
        request.session.logout(keep_db=True)

        env = request.env(user=uid)
        if "ai.gateway.session" not in env:
            return _json_response({"error": "secure session service is not installed"}, status=503)
        user = env["res.users"].sudo().browse(uid)
        if not user or not user.active:
            return _json_response({"error": "account is inactive"}, status=401)
        env = _scoped_user_env(user)
        token, expires, csrf_token = env["ai.gateway.session"].sudo().issue(user)
        response = _json_response({
            "authenticated": True,
            "user": {"id": user.id, "name": user.name, "login": user.login},
            "expires_at": expires,
            # This is a non-secret double-submit value.  The session cookie
            # remains HttpOnly; returning the CSRF value also supports a
            # separately hosted frontend that cannot read the API cookie.
            "csrf_token": csrf_token,
        })
        secure = os.environ.get("AI_GATEWAY_COOKIE_SECURE", "1" if os.environ.get("AI_GATEWAY_ALLOWED_ORIGIN", "").startswith("https://") else "0") == "1"
        samesite = os.environ.get("AI_GATEWAY_COOKIE_SAMESITE", "None" if os.environ.get("AI_GATEWAY_ALLOWED_ORIGIN", "").startswith("https://") else "Lax")
        response.set_cookie("ai_session", token, max_age=8 * 3600, httponly=True, secure=secure, samesite=samesite, path="/")
        response.set_cookie("ai_csrf", csrf_token, max_age=8 * 3600, httponly=False, secure=secure, samesite=samesite, path="/")
        return response

    @http.route("/api/logout", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def logout(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        # Logout is also a state-changing cookie operation.  Requiring the
        # same CSRF proof prevents a third-party page from silently logging a
        # user out and keeps all session mutations on one contract.
        env, err = _require_auth()
        if err:
            return err
        token = request.httprequest.cookies.get("ai_session", "").strip()
        if token and "ai.gateway.session" in env:
            rec = env["ai.gateway.session"].sudo().authenticate_token(token)
            if rec:
                rec.revoke()
        response = _json_response({"authenticated": False})
        response.delete_cookie("ai_session", path="/")
        response.delete_cookie("ai_csrf", path="/")
        return response

    @http.route("/api/session/rotate", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def rotate_session(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        token = request.httprequest.cookies.get("ai_session", "").strip()
        if not token or "ai.gateway.session" not in request.env:
            return _json_response({"error": "not_authenticated"}, status=401)
        # Rotation is a mutation and therefore must prove the current
        # session's CSRF token before the old token is replaced.
        csrf_token = request.httprequest.headers.get("X-CSRF-Token", "")
        current = request.env["ai.gateway.session"].sudo().authenticate_token(
            token, csrf_token=csrf_token, require_csrf=True,
        )
        if not current:
            return _json_response({"error": "invalid_or_expired_session"}, status=401)
        _, new_token, expires, new_csrf_token = request.env["ai.gateway.session"].sudo().rotate(
            token, user_agent=request.httprequest.headers.get("User-Agent"), ttl_hours=8
        )
        if not new_token:
            return _json_response({"error": "invalid_or_expired_session"}, status=401)
        response = _json_response({
            "authenticated": True, "expires_at": expires,
            "csrf_token": new_csrf_token,
        })
        secure = os.environ.get("AI_GATEWAY_COOKIE_SECURE", "1") == "1"
        samesite = os.environ.get("AI_GATEWAY_COOKIE_SAMESITE", "Lax")
        response.set_cookie(
            "ai_session", new_token, max_age=8 * 3600, httponly=True,
            secure=secure, samesite=samesite, path="/"
        )
        response.set_cookie(
            "ai_csrf", new_csrf_token, max_age=8 * 3600, httponly=False,
            secure=secure, samesite=samesite, path="/"
        )
        return response

    # ------------------------------------------------------------
    # Current user - a frontend's login/session screen needs this,
    # not the raw res.users model.
    # ------------------------------------------------------------
    @http.route("/api/me", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def me(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        user = env.user
        employee = env["hr.employee"].search([
            ("user_id", "=", user.id), ("company_id", "=", env.company.id),
        ], limit=1)
        capabilities = env["ai.control.authorization"].effective_capabilities(user=user) if "ai.control.authorization" in env else self.env["ai.control.capability"].browse()
        can_manage_documents = bool(user.has_group("base.group_system"))
        return _json_response({
            "id": user.id,
            "name": user.name,
            "login": user.login,
            "company": env.company.name,
            "is_manager": bool(employee.child_ids) if employee else False,
            # The frontend may use these feature flags for navigation. The
            # backend still re-checks every admin/document action server-side.
            "is_admin": _is_privileged(env, user),
            "can_manage_documents": can_manage_documents,
            "capabilities": _public_capabilities(capabilities),
        })

    # ------------------------------------------------------------
    # Leave requests - wraps hr.leave. Frontend never sees
    # "hr.leave", "holiday_status_id", or Odoo's state codes
    # ("confirm", "validate1") - those are translated here, once.
    # ------------------------------------------------------------
    @http.route("/api/hr/leaves", type="http", auth="none", csrf=False, methods=["GET", "POST", "OPTIONS"])
    def hr_leaves(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err

        if request.httprequest.method == "GET":
            return self._hr_leaves_list(env)
        return self._hr_leaves_create(env)

    def _hr_leaves_list(self, env):
        employee = env["hr.employee"].search([
            ("user_id", "=", env.user.id), ("company_id", "=", env.company.id),
        ], limit=1)
        if not employee:
            return _json_response({"leaves": []})
        leaves = env["hr.leave"].search([("employee_id", "=", employee.id)], order="date_from desc")
        return _json_response({"leaves": [self._serialize_leave(leave) for leave in leaves]})

    def _hr_leaves_create(self, env):
        payload, err = _read_json_body()
        if err:
            return err
        date_from = payload.get("date_from")
        date_to = payload.get("date_to")
        reason = payload.get("reason", "")
        if not date_from or not date_to:
            return _json_response({"error": "date_from and date_to are required"}, status=400)

        employee = env["hr.employee"].search([
            ("user_id", "=", env.user.id), ("company_id", "=", env.company.id),
        ], limit=1)
        if not employee:
            return _json_response({"error": "no employee record linked to this user"}, status=400)

        leave_type = env["hr.leave.type"].search([("requires_allocation", "=", "no")], limit=1)
        if not leave_type:
            leave_type = env["hr.leave.type"].search([], limit=1)
        if not leave_type:
            return _json_response({"error": "no leave type configured"}, status=400)

        try:
            leave = env["hr.leave"].create({
                "employee_id": employee.id,
                "holiday_status_id": leave_type.id,
                "date_from": f"{date_from} 08:00:00",
                "date_to": f"{date_to} 18:00:00",
                "name": reason or "درخواست مرخصی",
            })
            _audit(env, env.user.id, "semantic_api", "hr_leaves.create", payload, success=True)
            return _json_response(self._serialize_leave(leave), status=201)
        except (AccessError, UserError) as exc:
            _audit(env, env.user.id, "semantic_api", "hr_leaves.create", payload,
                   success=False, error_message=str(exc))
            return _json_response({"error": "leave request could not be created"}, status=403)

    @http.route("/api/hr/leaves/<int:leave_id>/cancel", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def hr_leave_cancel(self, leave_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err

        leave = env["hr.leave"].browse(leave_id)
        try:
            leave.check_access("read")
            if leave.state in ("draft", "confirm"):
                leave.unlink()
            elif hasattr(leave, "action_cancel"):
                leave.action_cancel()
            else:
                return _json_response(
                    {"error": f"cannot cancel a leave in state '{leave.state}' - ask your manager"},
                    status=409,
                )
            _audit(env, env.user.id, "semantic_api", "hr_leaves.cancel", {"leave_id": leave_id}, success=True)
            return _json_response({"status": "cancelled"})
        except AccessError as exc:
            _audit(env, env.user.id, "semantic_api", "hr_leaves.cancel", {"leave_id": leave_id},
                   success=False, error_message=str(exc))
            return _json_response({"error": "access denied: insufficient permission"}, status=403)

    @staticmethod
    def _serialize_leave(leave):
        # This is the ONE place in the entire project that translates
        # Odoo's internal state codes to something a frontend should
        # actually branch its UI on - if Odoo's state machine ever
        # changes, only this function needs updating.
        state_map = {
            "draft": "draft",
            "confirm": "pending_approval",
            "validate1": "pending_approval",
            "validate": "approved",
            "refuse": "rejected",
            "cancel": "cancelled",
        }
        return {
            "id": leave.id,
            "date_from": str(leave.date_from) if leave.date_from else None,
            "date_to": str(leave.date_to) if leave.date_to else None,
            "reason": leave.name or "",
            "status": state_map.get(leave.state, leave.state),
            "leave_type": leave.holiday_status_id.name or "",
        }

    @http.route("/api/approvals", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def approvals(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        if "ai.gateway.approval" not in env:
            return _json_response({"approvals": []})
        model = env["ai.gateway.approval"]
        records = model.search([], order="requested_at desc, id desc", limit=100)
        risk_model = env["ai.gateway.tool.risk"].sudo() if "ai.gateway.tool.risk" in env else None
        result = []
        for approval in records:
            risk = risk_model.search([("tool_name", "=", approval.tool_name)], limit=1) if risk_model is not None and approval.tool_name else None
            result.append({
                "id": approval.id,
                "name": approval.name,
                "state": approval.state,
                "requested_by": approval.requested_by_id.name,
                "approver_group": approval.approver_group_id.name,
                "risk_level": risk.risk_level if risk else None,
                "expires_at": str(approval.expires_at) if approval.expires_at else None,
                "can_decide": approval.state == "pending" and approval.requested_by_id != env.user and approval.approver_group_id in env.user.groups_id,
            })
        return _json_response({"approvals": result})

    @http.route("/api/approvals/<int:approval_id>/approve", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def approve(self, approval_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        approval = env["ai.gateway.approval"].browse(approval_id).exists() if "ai.gateway.approval" in env else None
        if not approval:
            return _json_response({"error": "approval not found or access denied"}, status=404)
        try:
            approval.action_approve()
        except Exception:  # noqa: BLE001 - do not expose internal target details
            return _json_response({"error": "approval could not be completed"}, status=409)
        return _json_response({"status": "approved", "approval_id": approval.id})

    @http.route("/api/approvals/<int:approval_id>/reject", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def reject(self, approval_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        body, body_err = _read_json_body()
        if body_err:
            return body_err
        approval = env["ai.gateway.approval"].browse(approval_id).exists() if "ai.gateway.approval" in env else None
        if not approval:
            return _json_response({"error": "approval not found or access denied"}, status=404)
        try:
            approval.action_reject(str(body.get("note") or "")[:1000])
        except Exception:  # noqa: BLE001
            return _json_response({"error": "approval could not be rejected"}, status=409)
        return _json_response({"status": "rejected", "approval_id": approval.id})

    # ------------------------------------------------------------
    # Documents - wraps company.document + ai.document.chunk
    # (roadmap #27). Same access rule as the AI tools use, so a
    # user sees exactly the same document list here as the
    # assistant would show them via list_documents.
    #
    # Phase 7 (#47 Document Center): this used to be GET-only (browse
    # + semantic search). It now also supports upload (POST) and
    # delete (DELETE), which is what actually makes this a "Document
    # Center" and not just a read-only viewer of company.document -
    # the gap the old frontend/README.md called out explicitly.
    # ------------------------------------------------------------
    @http.route("/api/documents", type="http", auth="none", csrf=False, methods=["GET", "POST", "OPTIONS"])
    def documents_list(self, query="", **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        if request.httprequest.method == "POST":
            return self._documents_create(env)

        access_level = kwargs.get("access_level", "")
        domain = []
        if query:
            domain.append(("name", "ilike", query))
        if access_level:
            domain.append(("access_level", "=", access_level))
        docs = env["company.document"].search(domain, order="create_date desc")
        return _json_response({"documents": [self._serialize_document(env, d) for d in docs]})

    def _documents_create(self, env):
        payload, err = _read_json_body()
        if err:
            return err
        name = (payload.get("name") or "").strip()
        document_policy = _active_profile_section(env, "document_policy")
        access_level = payload.get(
            "access_level", document_policy.get("default_access_level", "personal")
        )
        allowed_levels = document_policy.get("allowed_access_levels", [])
        if not name:
            return _json_response({"error": "'name' is required"}, status=400)
        if access_level not in ("company", "group", "department", "personal"):
            return _json_response({"error": "invalid access_level"}, status=400)
        if allowed_levels and (
            not isinstance(allowed_levels, list) or access_level not in {str(item) for item in allowed_levels}
        ):
            return _json_response({"error": "access_level is disabled by the active customer profile"}, status=403)

        values = {
            "name": name,
            "description": payload.get("description", ""),
            "access_level": access_level,
            "owner_id": env.user.id,
        }
        if payload.get("file_base64"):
            try:
                raw = base64.b64decode(payload["file_base64"], validate=True)
                upload = validate_upload(
                    payload.get("file_name") or name,
                    raw,
                    max_bytes=MAX_UPLOAD_BYTES,
                )
            except (TypeError, ValueError):
                return _json_response({"error": "invalid or unsupported file upload"}, status=400)
            values["file"] = payload["file_base64"]
            values["file_name"] = upload["filename"]

        # A user may only restrict a document to a group they are
        # themselves a member of, or a department they can name -
        # this mirrors the same self-service-only rule
        # grant_temporary_access uses for roles (access_review_tools.py):
        # you can't hand out scope you don't have.
        if access_level == "group":
            group_id = payload.get("group_id")
            group = env["res.groups"].browse(group_id) if group_id else env["res.groups"]
            if not group or group not in env.user.groups_id:
                return _json_response(
                    {"error": "you may only restrict a document to a group you belong to"}, status=403)
            values["group_id"] = group.id
        elif access_level == "department":
            # BUG FOUND during a later audit pass: this used to accept
            # ANY existing department_id with no ownership check at
            # all - unlike the group branch above. In practice Odoo's
            # own ir.rule on company.document (document_rules.xml)
            # would still have blocked a mismatched department at the
            # database layer (create-time rule checks apply the same
            # domain as read), so this was never an actual access-
            # control hole - but it meant a non-privileged user got a
            # generic "access denied" from deep inside the ORM instead
            # of a clear reason, and (worse) documents_options() below
            # was offering every department in the company as if any
            # of them would work. Fixed to match the group branch's
            # pattern exactly: self-service only, checked explicitly,
            # before create() is ever called - admins/privileged roles
            # are exempt, same as company.document's own admin rule.
            department_id = payload.get("department_id")
            department = env["hr.department"].browse(department_id) if department_id else env["hr.department"]
            if not department.exists():
                return _json_response({"error": "invalid department_id"}, status=400)
            if not _is_privileged(env, env.user):
                employee = env["hr.employee"].search([
                    ("user_id", "=", env.user.id), ("company_id", "=", env.company.id),
                ], limit=1)
                if not employee.department_id or department.id != employee.department_id.id:
                    return _json_response(
                        {"error": "you may only restrict a document to your own department"}, status=403)
            values["department_id"] = department.id

        try:
            doc = env["company.document"].create(values)
            _audit(env, env.user.id, "semantic_api", "documents.create",
                   {"name": name, "access_level": access_level}, success=True)
            return _json_response(self._serialize_document(env, doc), status=201)
        except (AccessError, UserError) as exc:
            _audit(env, env.user.id, "semantic_api", "documents.create",
                   {"name": name, "access_level": access_level}, success=False, error_message=str(exc))
            return _json_response({"error": "document could not be created"}, status=403)

    @http.route("/api/documents/options", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def documents_options(self, **kwargs):
        """Feeds the Document Center's upload form (roadmap #47): the
        departments and groups this particular user is actually
        allowed to pick when restricting a new document, not every
        department/group that exists in the whole company.

        BUG FOUND during a later audit pass: the docstring above
        always said this, but the code below returned EVERY
        department in the company, not just the caller's own - the
        picker in DocumentCenterPage.jsx would happily show a dropdown
        of departments where only one choice would actually be
        accepted by _documents_create (see that method's own note).
        Fixed to match what the docstring - and the `groups` list two
        lines below it - already correctly did. Privileged roles
        still get the full list, since they're also exempt from the
        ownership check in _documents_create."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        employee = env["hr.employee"].search([
            ("user_id", "=", env.user.id), ("company_id", "=", env.company.id),
        ], limit=1)
        if _is_privileged(env, env.user):
            departments = env["hr.department"].search([])
        else:
            departments = employee.department_id
        # Only Role Template groups (data/role_templates_data.xml, #5) -
        # not every technical res.groups record Odoo ships with, which
        # would be meaningless noise in a document-restriction picker.
        role_category = env.ref("ai_business_tools.role_category", raise_if_not_found=False)
        own_groups = env.user.groups_id.filtered(
            lambda g: role_category and g.category_id == role_category
        )
        return _json_response({
            "departments": [{"id": d.id, "name": d.name} for d in departments],
            "own_department_id": employee.department_id.id if employee.department_id else None,
            "groups": [{"id": g.id, "name": g.name} for g in own_groups],
        })

    @http.route("/api/documents/<int:document_id>", type="http", auth="none", csrf=False,
                methods=["GET", "DELETE", "OPTIONS"])
    def document_get(self, document_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        if request.httprequest.method == "DELETE":
            return self._document_delete(env, document_id)

        doc = env["company.document"].browse(document_id)
        try:
            doc.check_access("read")
        except AccessError:
            return _json_response({"error": "access denied: insufficient permission"}, status=403)
        return _json_response(self._serialize_document(env, doc))

    @http.route("/api/documents/<int:document_id>/file", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def document_file(self, document_id, **kwargs):
        """Streams the stored file of one document for download or
        preview. The payload lives in Odoo's native ir.attachment layer
        (company.document.file is a Binary(attachment=True) column), so
        the same record rule that protects the metadata protects these
        bytes - browsing the document passes (env user can read),
        browsing it in a scope you are not in returns 403, exactly like
        document_get."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        doc = env["company.document"].browse(document_id)
        try:
            doc.check_access("read")
        except AccessError:
            return _json_response({"error": "access denied: insufficient permission"}, status=403)
        if not doc.exists():
            return _json_response({"error": "not found"}, status=404)
        content = doc.file
        if not content:
            return _json_response({"error": "document has no file"}, status=404)
        try:
            # Odoo Binary fields are base64 encoded at the ORM boundary. Do
            # not stream the encoded representation as if it were the file.
            raw = base64.b64decode(content, validate=True)
            filename = doc.file_name or (doc.name or "document")
            upload = validate_upload(filename, raw, max_bytes=MAX_UPLOAD_BYTES)
        except (TypeError, ValueError):
            return _json_response({"error": "stored document content is invalid"}, status=415)
        return Response(
            raw,
            headers=[
                ("Content-Type", upload["mimetype"]),
                ("Content-Disposition", "inline; filename*=UTF-8''%s" % _quote_filename(filename)),
            ] + _CORS_HEADERS,
            status=200,
        )

    def _document_delete(self, env, document_id):
        doc = env["company.document"].browse(document_id)
        try:
            doc.check_access("read")
        except AccessError:
            return _json_response({"error": "access denied: insufficient permission"}, status=403)
        if not doc.exists():
            return _json_response({"error": "not found"}, status=404)

        # HONEST NOTE (mirrors item #22's own carve-out policy):
        # ir.model.access.csv intentionally gives base.group_user NO
        # unlink on company.document at all (see the ACL row's
        # trailing 0) - a document is meant to be revoked by scope
        # (access_level), not casually deleted by anyone who can read
        # it. The two cases that SHOULD be able to delete - the
        # document's own owner removing their own personal upload,
        # and a privileged admin cleaning up any document - are
        # checked explicitly right here, in plain Python, before the
        # sudo() below, not left to the ACL to decide.
        is_owner = doc.access_level == "personal" and doc.owner_id.id == env.user.id
        if not (is_owner or _is_privileged(env, env.user)):
            _audit(env, env.user.id, "semantic_api", "documents.delete", {"document_id": document_id},
                   success=False, error_message="denied_not_owner_or_admin")
            return _json_response(
                {"error": "access denied: only the document's owner or an admin can delete it"}, status=403)

        name = doc.name
        doc.sudo().unlink()
        _audit(env, env.user.id, "semantic_api", "documents.delete",
               {"document_id": document_id, "name": name}, success=True)
        return _json_response({"status": "deleted"})

    @http.route("/api/documents/<int:document_id>/reindex", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def document_reindex(self, document_id, **kwargs):
        """Queue a bounded, durable retry without embedding in the HTTP request."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        document = env["company.document"].browse(document_id)
        try:
            document.check_access("read")
        except AccessError:
            return _json_response({"error": "access denied: insufficient permission"}, status=403)
        if not document.exists():
            return _json_response({"error": "not found"}, status=404)
        is_owner = document.owner_id.id == env.user.id
        if not (is_owner or _is_privileged(env, env.user)):
            return _json_response({"error": "access denied: only the owner or an admin can retry indexing"}, status=403)
        if not document.file:
            return _json_response({"error": "document has no file"}, status=400)
        if "ai.document.index.job" not in env:
            return _json_response({"error": "document indexing is unavailable"}, status=503)
        job = env["ai.document.index.job"].sudo().enqueue(document)
        _audit(
            env, env.user.id, "semantic_api", "documents.reindex",
            {"document_id": document.id, "job_id": job.id}, success=True,
        )
        return _json_response({
            "status": "queued",
            "job_state": job.state,
            "document": self._serialize_document(env, document),
        }, status=202)

    @http.route("/api/documents/search", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def documents_search(self, **params):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        try:
            body = json.loads(request.httprequest.data or b"{}")
        except (TypeError, ValueError):
            return _json_response({"error": "invalid JSON body"}, status=400)
        if not isinstance(body, dict):
            return _json_response({"error": "JSON body must be an object"}, status=400)
        query = body.get("query", "")
        top_k = body.get("top_k", 5)
        if not query:
            return _json_response({"error": "'query' is required"}, status=400)

        try:
            # Same underlying method the AI tool uses
            # (search_documents_semantic) - a human typing in the
            # frontend's search box and the assistant answering a
            # question both go through the exact same access-filtered
            # vector search, not two different code paths that could
            # drift apart.
            results = env["ai.document.chunk"].search_similar(query, top_k=int(top_k))
            _audit(env, env.user.id, "semantic_api", "documents.search",
                   {"query": query}, success=True)
            return _json_response({"results": results})
        except UserError as exc:
            _audit(env, env.user.id, "semantic_api", "documents.search",
                   {"query": query}, success=False, error_message=str(exc))
            return _json_response({"error": "semantic search failed"}, status=503)

    @staticmethod
    def _serialize_document(env, doc):
        return {
            "id": doc.id,
            "name": doc.name,
            "access_level": doc.access_level,
            "description": doc.description or "",
            "file_name": doc.file_name or "",
            "has_file": bool(doc.file),
            "url": "/api/documents/%s/file" % doc.id if bool(doc.file) else None,
            "department": doc.department_id.name if doc.department_id else None,
            "group": doc.group_id.name if doc.group_id else None,
            "owner": doc.owner_id.name if doc.owner_id else None,
            "is_mine": doc.owner_id.id == env.user.id if doc.owner_id else False,
            "create_date": str(doc.create_date) if doc.create_date else None,
            "chunk_count": doc.chunk_count if "chunk_count" in doc._fields else None,
            "ingestion_status": (
                doc.rag_ingestion_state
                if "rag_ingestion_state" in doc._fields and doc.file
                else ("no_file" if not doc.file else "pending")
            ),
            "ingestion_pages": doc.rag_ingestion_page_count if "rag_ingestion_page_count" in doc._fields else 0,
            "ingestion_parser": doc.rag_ingestion_parser if "rag_ingestion_parser" in doc._fields else "",
            "ingestion_warnings": doc.rag_ingestion_warnings if "rag_ingestion_warnings" in doc._fields else "",
            "ingestion_error": (
                "document could not be indexed"
                if "rag_ingestion_state" in doc._fields and doc.rag_ingestion_state == "failed"
                else ""
            ),
        }

    # ------------------------------------------------------------------
    # Admin Console (roadmap #46) and Customer Setup Center. Every
    # route below is gated by _require_privileged() - see that function's
    # docstring. Product settings use explicit company-scoped models;
    # only legacy compatibility values remain in ir.config_parameter.
    # The browser never receives a generic ORM/RPC door.
    # ------------------------------------------------------------------

    @http.route("/api/admin/roles", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def admin_roles(self, **kwargs):
        """Same data as the Role Permissions Overview backend view
        (ai_business_tools/views/role_permissions_views.xml, #4/#6),
        exposed to the frontend so the Admin Console doesn't need to
        send a privileged user into the Odoo backend just to answer
        'what does this Role grant, and who has it'."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        role_category = env.ref("ai_business_tools.role_category", raise_if_not_found=False)
        domain = [("category_id", "=", role_category.id)] if role_category else []
        roles = env["res.groups"].sudo().search(domain, order="name")
        return _json_response({"roles": [
            {
                "id": r.id,
                "name": r.name,
                "comment": r.comment or "",
                "implied_roles": [g.name for g in r.implied_ids],
                "members": [{"id": u.id, "name": u.name, "login": u.login} for u in r.users.filtered(lambda u: env.company in u.company_ids)],
                "member_count": len(r.users.filtered(lambda u: env.company in u.company_ids)),
            }
            for r in roles
        ]})

    @http.route("/api/admin/users", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def admin_users(self, **kwargs):
        """Feeds the Admin Console's Access Grants tab (a picker for
        'grant this role to this user') - name/login/department/roles
        only, nothing more sensitive than what's already visible on
        every user's own profile."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        role_category = env.ref("ai_business_tools.role_category", raise_if_not_found=False)
        users = env["res.users"].sudo().search([
            ("share", "=", False), ("company_ids", "in", env.company.id),
        ], order="name")
        result = []
        for u in users:
            employee = env["hr.employee"].sudo().search([
                ("user_id", "=", u.id), ("company_id", "=", env.company.id),
            ], limit=1)
            roles = u.groups_id.filtered(lambda g: role_category and g.category_id == role_category) \
                if role_category else env["res.groups"]
            result.append({
                "id": u.id, "name": u.name, "login": u.login,
                "department": employee.department_id.name if employee.department_id else None,
                "roles": [g.name for g in roles],
            })
        return _json_response({"users": result})

    @http.route("/api/admin/access-grants", type="http", auth="none", csrf=False,
                methods=["GET", "POST", "OPTIONS"])
    def admin_access_grants(self, **kwargs):
        """Admin-Console front door onto ai.gateway.access.grant
        (#41 Delegation / #42 Temporary Access) - the same model the
        grant_temporary_access AI tool uses (access_review_tools.py),
        so a grant created by an admin here and one an employee asked
        the assistant for show up in exactly the same list, with the
        same daily cron (cron_apply_and_expire_grants) activating and
        expiring both identically."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        if request.httprequest.method == "POST":
            return self._admin_access_grant_create(env)

        grants = env["ai.gateway.access.grant"].sudo().search([
            ("company_id", "=", env.company.id),
        ], order="create_date desc")
        return _json_response({"grants": [self._serialize_grant(g) for g in grants]})

    def _admin_access_grant_create(self, env):
        payload, err = _read_json_body()
        if err:
            return err
        to_user_id = payload.get("to_user_id")
        group_id = payload.get("group_id")
        expires_on = payload.get("expires_on")
        missing = [n for n, v in (("to_user_id", to_user_id), ("group_id", group_id),
                                   ("expires_on", expires_on)) if not v]
        if missing:
            return _json_response({"error": f"missing required fields: {', '.join(missing)}"}, status=400)

        try:
            to_user = env["res.users"].sudo().browse(int(to_user_id)).exists()
            group = env["res.groups"].sudo().browse(int(group_id)).exists()
        except (TypeError, ValueError):
            return _json_response({"error": "invalid to_user_id or group_id"}, status=400)
        if not to_user or not group or env.company not in to_user.company_ids:
            return _json_response({"error": "target user is not in the current company"}, status=403)
        group_xmlid = group.get_external_id().get(group.id, "") or ""
        if not group_xmlid.startswith("ai_business_tools.role_"):
            return _json_response({"error": "only product roles may be granted"}, status=403)

        delegated_from_id = payload.get("delegated_from_id") or False
        if delegated_from_id:
            try:
                delegated_from = env["res.users"].sudo().browse(int(delegated_from_id)).exists()
            except (TypeError, ValueError):
                delegated_from = env["res.users"]
            if not delegated_from or env.company not in delegated_from.company_ids:
                return _json_response({"error": "delegator is not in the current company"}, status=403)
            delegated_from_id = delegated_from.id
        try:
            start_date = odoo_fields.Date.from_string(
                payload.get("start_date") or str(odoo_fields.Date.context_today(env.user))
            )
            expiry_date = odoo_fields.Date.from_string(str(expires_on))
        except (TypeError, ValueError):
            return _json_response({"error": "dates must use YYYY-MM-DD"}, status=400)
        today = odoo_fields.Date.context_today(env.user)
        if not expiry_date or expiry_date < today or expiry_date < start_date:
            return _json_response({"error": "expires_on must be today or later and not before start_date"}, status=400)
        reason = str(payload.get("reason") or "Admin console access grant").strip()[:1000]
        try:
            grant = env["ai.gateway.access.grant"].sudo().create({
                "company_id": env.company.id,
                "to_user_id": to_user.id,
                "group_id": group.id,
                "delegated_from_id": delegated_from_id,
                "start_date": start_date,
                "expires_on": expiry_date,
                "reason": reason,
                "granted_by_id": env.user.id,
            })
        except (AccessError, UserError, ValidationError):
            return _json_response({"error": "access grant could not be created"}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.access_grants.create",
               {"to_user": to_user.name, "group": group.name, "expires_on": str(expiry_date)}, success=True)
        return _json_response(self._serialize_grant(grant), status=201)

    @http.route("/api/admin/access-grants/<int:grant_id>/revoke", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_access_grant_revoke(self, grant_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        grant = env["ai.gateway.access.grant"].sudo().search([
            ("id", "=", grant_id), ("company_id", "=", env.company.id),
        ], limit=1)
        if not grant:
            return _json_response({"error": "not found"}, status=404)
        grant.with_context(authorization_actor_id=env.user.id).action_revoke_now()
        _audit(env, env.user.id, "semantic_api", "admin.access_grants.revoke",
               {"grant_id": grant_id}, success=True)
        return _json_response({"status": "revoked"})

    @staticmethod
    def _serialize_grant(g):
        return {
            "id": g.id,
            "to_user": g.to_user_id.name,
            "role": g.group_id.name,
            "delegated_from": g.delegated_from_id.name if g.delegated_from_id else None,
            "start_date": str(g.start_date) if g.start_date else None,
            "expires_on": str(g.expires_on) if g.expires_on else None,
            "state": g.state,
            "reason": g.reason or "",
            "granted_by": g.granted_by_id.name if g.granted_by_id else None,
        }

    @http.route("/api/admin/documents", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def admin_documents(self, **kwargs):
        """Org-wide document overview - deliberately separate from
        GET /api/documents, which only ever shows what the CALLING
        user themselves can see (#2/#25's scoping). This one
        intentionally bypasses that scoping (sudo(), after the
        privileged check above) because an admin reviewing document
        sprawl needs to see personal/department/group documents that
        aren't theirs - the whole point of the screen."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        docs = env["company.document"].sudo().search([
            ("company_id", "=", env.company.id),
        ], order="create_date desc")
        return _json_response({"documents": [self._serialize_document(env, d) for d in docs]})

    @http.route("/api/admin/agents", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def admin_agents(self, **kwargs):
        """Combines the Tool Registry (#15) and Risk Engine (#20)
        with a peek at the Model Registry (#17) - what the AI layer
        (#13/#14) is actually capable of and how each capability is
        risk-gated, in one screen. Same tool_risk data the
        list_available_tools AI tool itself reads (tool_registry.py) -
        an admin and the assistant see the same registry."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err

        risks = env["ai.gateway.tool.risk"].sudo().search([], order="risk_level desc, tool_name")
        tools = [
            {
                "name": scrub_public_text(r.tool_name),
                "risk_level": r.risk_level,
                "requires_approval_from": scrub_public_text(r.approver_group_id.name) if r.approver_group_id else None,
                "description": scrub_public_text(r.description or ""),
            }
            for r in risks
        ]

        if "ai.integration.agent.module" in env:
            try:
                env["ai.integration.agent.module"].sudo().refresh_if_stale()
            except Exception:  # noqa: BLE001
                _logger.exception("Could not refresh module-agent connections for admin view")

        assistants = []
        if "llm.assistant" in env:
            for a in env["llm.assistant"].sudo().search([]):
                bindings = env["ai.integration.agent.module"].sudo().search([
                    ("agent_id", "=", a.id), ("company_id", "=", env.company.id),
                    ("active", "=", True),
                ]) if "ai.integration.agent.module" in env else []
                assistants.append({
                    "name": a.name,
                    # Infrastructure identifiers are intentionally not part of
                    # the product/admin API; only capability and health state
                    # are customer-visible.
                    "tool_count": len(a.tool_ids) if hasattr(a, "tool_ids") else None,
                    "connected_module_count": len(bindings),
                    "connected_modules": [{
                        "label": b.module_label,
                        "state": b.state,
                        "tool_count": b.tool_count,
                    } for b in bindings],
                    "active": a.active,
                })

        vision_configured = bool(env["ir.config_parameter"].sudo().get_param(
            "company_ai_demo.vision_api_base", None))

        return _json_response({
            "tools": tools,
            "assistants": assistants,
            "vision_configured": vision_configured,
        })

    # ------------------------------------------------------------
    # Customer configuration profiles. These routes expose the existing
    # versioned/compiled profile model through a structured contract; the
    # browser cannot write arbitrary ORM fields or activate an uncompiled
    # snapshot.
    # ------------------------------------------------------------
    @http.route("/api/admin/configuration-profiles", type="http", auth="none", csrf=False,
                methods=["GET", "POST", "OPTIONS"])
    def admin_configuration_profiles(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        Profile = env["ai.customer.configuration.profile"]
        if request.httprequest.method == "GET":
            profiles = Profile.search([], order="state, name, id")
            return _json_response({
                "profiles": [_profile_json_values(profile) for profile in profiles],
            })
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        try:
            values = _profile_values_from_payload(payload, require_name=True)
            profile = Profile.create(values)
        except (ValidationError, AccessError) as exc:
            return _json_response({"error": str(exc)}, status=400)
        _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.create", {
            "profile_id": profile.id,
            "name": profile.name,
        }, success=True)
        return _json_response({"profile": _profile_json_values(profile, include_sections=True)}, status=201)

    @staticmethod
    def _configuration_profile(env, profile_id):
        return env["ai.customer.configuration.profile"].search([
            ("id", "=", profile_id), ("company_id", "=", env.company.id),
        ], limit=1)

    @http.route("/api/admin/configuration-profiles/<int:profile_id>", type="http", auth="none", csrf=False,
                methods=["GET", "PATCH", "OPTIONS"])
    def admin_configuration_profile(self, profile_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        profile = self._configuration_profile(env, profile_id)
        if not profile:
            return _json_response({"error": "configuration profile not found"}, status=404)
        if request.httprequest.method == "GET":
            return _json_response({"profile": _profile_json_values(profile, include_sections=True)})
        if profile.state == "active":
            return _json_response({"error": "active profile must be cloned before editing"}, status=409)
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        try:
            values = _profile_values_from_payload(payload)
            if not values:
                return _json_response({"error": "no profile changes supplied"}, status=400)
            profile.write(values)
        except (ValidationError, AccessError) as exc:
            return _json_response({"error": str(exc)}, status=400)
        _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.update", {
            "profile_id": profile.id,
            "fields": sorted(values),
        }, success=True)
        return _json_response({"profile": _profile_json_values(profile, include_sections=True)})

    @http.route("/api/admin/configuration-profiles/<int:profile_id>/validate", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_configuration_profile_validate(self, profile_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        profile = self._configuration_profile(env, profile_id)
        if not profile:
            return _json_response({"error": "configuration profile not found"}, status=404)
        try:
            sections = {
                section: profile._parse_section(
                    getattr(profile, "%s_json" % section), section,
                )
                for section in _PROFILE_SECTIONS
            }
            tools = sections["tool_config"].get(
                "allowed_tools", sections["tool_config"].get("tools", []),
            )
            if tools and not isinstance(tools, list):
                raise ValidationError("tool_config.allowed_tools must be a list")
            result = {
                "valid": True,
                "sections": sorted(sections),
                "configured_tool_count": len(tools or []),
                "requires_compile": not bool(profile.compiled_hash),
            }
        except (TypeError, ValueError, ValidationError) as exc:
            result = {"valid": False, "error": str(exc)}
        _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.validate", {
            "profile_id": profile.id,
            "valid": result["valid"],
        }, success=result["valid"], error_message=result.get("error"))
        return _json_response({"profile": _profile_json_values(profile), "validation": result},
                              status=200 if result["valid"] else 409)

    @http.route("/api/admin/configuration-profiles/<int:profile_id>/compile", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_configuration_profile_compile(self, profile_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        profile = self._configuration_profile(env, profile_id)
        if not profile:
            return _json_response({"error": "configuration profile not found"}, status=404)
        try:
            snapshot = profile.compile_runtime()
        except (ValidationError, AccessError, UserError) as exc:
            _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.compile", {
                "profile_id": profile.id,
            }, success=False, error_message=str(exc))
            return _json_response({"error": str(exc)}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.compile", {
            "profile_id": profile.id,
            "compiled_hash": profile.compiled_hash,
        }, success=True)
        return _json_response({
            "profile": _profile_json_values(profile),
            "compile": {
                "valid": True,
                "compiled_hash": profile.compiled_hash,
                "tool_contract_count": len(snapshot.get("tool_contracts", [])),
            },
        })

    @http.route("/api/admin/configuration-profiles/<int:profile_id>/activate", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_configuration_profile_activate(self, profile_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        profile = self._configuration_profile(env, profile_id)
        if not profile:
            return _json_response({"error": "configuration profile not found"}, status=404)
        try:
            profile.activate()
        except (ValidationError, AccessError, UserError) as exc:
            _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.activate", {
                "profile_id": profile.id,
            }, success=False, error_message=str(exc))
            return _json_response({"error": str(exc)}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.activate", {
            "profile_id": profile.id,
            "compiled_hash": profile.compiled_hash,
        }, success=True)
        return _json_response({"profile": _profile_json_values(profile, include_sections=True)})

    @http.route("/api/admin/configuration-profiles/<int:profile_id>/archive", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_configuration_profile_archive(self, profile_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        profile = self._configuration_profile(env, profile_id)
        if not profile:
            return _json_response({"error": "configuration profile not found"}, status=404)
        if profile.state == "active":
            return _json_response({"error": "active profile cannot be archived"}, status=409)
        profile.write({"state": "archived", "active": False})
        _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.archive", {
            "profile_id": profile.id,
        }, success=True)
        return _json_response({"profile": _profile_json_values(profile)})

    @http.route("/api/admin/configuration-profiles/<int:profile_id>/dry-run", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_configuration_profile_dry_run(self, profile_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        profile = self._configuration_profile(env, profile_id)
        if not profile:
            return _json_response({"error": "configuration profile not found"}, status=404)
        try:
            wizard = env["ai.customer.deployment.wizard"].create({
                "profile_id": profile.id,
                "dry_run": True,
            })
            wizard.run()
            result = _json.loads(wizard.result_json or "{}")
            wizard.unlink()
        except (ValidationError, AccessError, UserError, ValueError) as exc:
            return _json_response({"error": str(exc)}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.dry_run", {
            "profile_id": profile.id,
            "ready": bool(result.get("ready")),
        }, success=True)
        return _json_response({"profile": _profile_json_values(profile), "dry_run": result})

    @http.route("/api/admin/configuration-profiles/<int:profile_id>/clone", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_configuration_profile_clone(self, profile_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        profile = self._configuration_profile(env, profile_id)
        if not profile:
            return _json_response({"error": "configuration profile not found"}, status=404)
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_response({"error": "clone name is required"}, status=400)
        if env["ai.customer.configuration.profile"].search_count([
            ("company_id", "=", env.company.id), ("name", "=", name),
        ]):
            return _json_response({"error": "a profile with this name already exists"}, status=409)
        try:
            clone = profile.clone(name)
        except (ValidationError, AccessError) as exc:
            return _json_response({"error": str(exc)}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.clone", {
            "source_profile_id": profile.id,
            "profile_id": clone.id,
        }, success=True)
        return _json_response({"profile": _profile_json_values(clone, include_sections=True)}, status=201)

    @http.route("/api/admin/configuration-profiles/<int:profile_id>/history", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def admin_configuration_profile_history(self, profile_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        profile = self._configuration_profile(env, profile_id)
        if not profile:
            return _json_response({"error": "configuration profile not found"}, status=404)
        history = env["ai.customer.configuration.profile.history"].search([
            ("company_id", "=", env.company.id), ("profile_id", "=", profile.id),
        ], order="changed_at desc,id desc", limit=100)
        rows = []
        for item in history:
            try:
                snapshot = _json.loads(item.snapshot_json or "{}")
            except (TypeError, ValueError):
                snapshot = {}
            rows.append({
                "id": item.id,
                "version": item.profile_version,
                "state": item.state,
                "compiled_hash": item.compiled_hash or "",
                "changed_by": item.changed_by_id.name,
                "changed_at": str(item.changed_at) if item.changed_at else None,
                "snapshot": snapshot,
            })
        return _json_response({"profile_id": profile.id, "history": rows})

    @http.route("/api/admin/configuration-profiles/<int:profile_id>/export", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def admin_configuration_profile_export(self, profile_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        profile = self._configuration_profile(env, profile_id)
        if not profile:
            return _json_response({"error": "configuration profile not found"}, status=404)
        snapshot = profile.export_snapshot()
        _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.export", {
            "profile_id": profile.id, "version": profile.version,
        }, success=True)
        return _json_response({"profile": _profile_json_values(profile, include_sections=True), "snapshot": snapshot})

    @http.route("/api/admin/configuration-profiles/import", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_configuration_profile_import(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            return _json_response({"error": "snapshot object is required"}, status=400)
        name = str(payload.get("name") or snapshot.get("name") or "").strip()
        if not name:
            return _json_response({"error": "imported profile name is required"}, status=400)
        if env["ai.customer.configuration.profile"].search_count([
            ("company_id", "=", env.company.id), ("name", "=", name),
        ]):
            return _json_response({"error": "a profile with this name already exists"}, status=409)
        try:
            profile = env["ai.customer.configuration.profile"].create_from_snapshot(
                snapshot, name=name, company=env.company,
            )
        except (ValidationError, AccessError) as exc:
            return _json_response({"error": str(exc)}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.import", {
            "profile_id": profile.id, "name": profile.name,
        }, success=True)
        return _json_response({"profile": _profile_json_values(profile, include_sections=True)}, status=201)

    @http.route("/api/admin/configuration-profiles/<int:profile_id>/rollback", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_configuration_profile_rollback(self, profile_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        profile = self._configuration_profile(env, profile_id)
        if not profile:
            return _json_response({"error": "configuration profile not found"}, status=404)
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        try:
            history_id = int(payload.get("history_id"))
        except (TypeError, ValueError):
            return _json_response({"error": "history_id is required"}, status=400)
        history = env["ai.customer.configuration.profile.history"].search([
            ("id", "=", history_id), ("company_id", "=", env.company.id),
            ("profile_id", "=", profile.id),
        ], limit=1)
        if not history:
            return _json_response({"error": "history snapshot not found"}, status=404)
        name = str(payload.get("name") or "%s rollback v%s" % (profile.name, history.profile_version)).strip()
        if env["ai.customer.configuration.profile"].search_count([
            ("company_id", "=", env.company.id), ("name", "=", name),
        ]):
            return _json_response({"error": "a profile with this name already exists"}, status=409)
        try:
            rollback = profile.rollback_from_history(history, name=name)
        except (ValidationError, AccessError) as exc:
            return _json_response({"error": str(exc)}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.configuration_profile.rollback", {
            "source_profile_id": profile.id, "history_id": history.id, "profile_id": rollback.id,
        }, success=True)
        return _json_response({"profile": _profile_json_values(rollback, include_sections=True), "source_history_id": history.id}, status=201)

    @staticmethod
    def _setup_checklist(env):
        company = env.company.sudo()
        checks = []

        def add(key, label, state, severity, message, remediation=None):
            checks.append({
                "key": key,
                "label": label,
                "state": state,
                "severity": severity,
                "message": message,
                "remediation": remediation,
            })

        add(
            "company.identity", "مشخصات شرکت", "pass" if company.name else "fail",
            "blocking", "نام شرکت ثبت شده است." if company.name else "نام شرکت لازم است.",
            None if company.name else "/admin?tab=setup",
        )
        branding = env["ai.customer.branding"].search([
            ("company_id", "=", company.id), ("active", "=", True),
        ], limit=1)
        add(
            "branding.record", "پروفایل برند", "pass" if branding else "fail",
            "blocking", "پروفایل برند موجود است." if branding else "پروفایل برند ایجاد نشده است.",
            None if branding else "/admin?tab=branding",
        )
        add(
            "branding.logo", "لوگو", "pass" if branding and branding.logo else "fail",
            "blocking", "لوگو ثبت شده است." if branding and branding.logo else "لوگو ثبت نشده است.",
            None if branding and branding.logo else "/admin?tab=branding",
        )
        add(
            "branding.favicon", "Favicon", "pass" if branding and branding.favicon else "fail",
            "blocking", "Favicon ثبت شده است." if branding and branding.favicon else "Favicon ثبت نشده است.",
            None if branding and branding.favicon else "/admin?tab=branding",
        )
        theme_ok = bool(branding and branding.primary_color and branding.background_color)
        add(
            "branding.theme", "رنگ و ظاهر", "pass" if theme_ok else "fail",
            "blocking", "Theme معتبر است." if theme_ok else "Theme کامل نیست.",
            None if theme_ok else "/admin?tab=branding",
        )

        installed_apps = env["ir.module.module"].sudo().search([
            ("state", "=", "installed"), ("application", "=", True),
        ]) if "ir.module.module" in env else env["ir.module.module"].browse()
        registry = env["ai.control.module"].sudo() if "ai.control.module" in env else None
        module_rows = registry.search([
            ("technical_name", "in", installed_apps.mapped("name")),
            ("state", "=", "installed"),
        ]) if registry is not None and installed_apps else []
        all_registered = bool(installed_apps) and len(module_rows) == len(installed_apps)
        add(
            "modules.registry", "ثبت برنامه‌های نصب‌شده", "pass" if all_registered else "fail",
            "blocking" if installed_apps else "warning",
            "تمام Applicationهای نصب‌شده در registry ثبت شده‌اند." if all_registered else "برخی Applicationهای نصب‌شده هنوز sync نشده‌اند.",
            None if all_registered else "/admin?tab=modules",
        )
        agent_ok = bool(module_rows) and all(
            row.agent_connection_state in ("connected", "connected_no_tools") for row in module_rows
        ) if module_rows else False
        add(
            "modules.agent", "اتصال برنامه‌ها به Agent", "pass" if agent_ok else "fail",
            "blocking" if installed_apps else "warning",
            "Agent برای برنامه‌های نصب‌شده متصل است." if agent_ok else "اتصال Agent همه برنامه‌ها کامل نیست.",
            None if agent_ok else "/admin?tab=modules",
        )

        profiles = env["ai.customer.configuration.profile"].search([
            ("company_id", "=", company.id),
        ])
        active_profile = profiles.filtered(lambda profile: profile.state == "active")[:1]
        profile_ok = bool(active_profile and active_profile.compiled_hash and active_profile.compiled_at)
        add(
            "profile.active", "Configuration Profile فعال", "pass" if profile_ok else "fail",
            "blocking", "Profile فعال و compile شده است." if profile_ok else "Profile فعال و compile شده لازم است.",
            None if profile_ok else "/admin?tab=profiles",
        )

        deployment_ready = False
        deployment_message = "Deployment dry-run هنوز اجرا نشده است."
        if active_profile:
            try:
                wizard = env["ai.customer.deployment.wizard"].create({
                    "profile_id": active_profile.id, "dry_run": True,
                })
                wizard.run()
                result = _json.loads(wizard.result_json or "{}")
                deployment_ready = bool(result.get("ready"))
                deployment_message = "تمام prerequisiteهای profile PASS شد." if deployment_ready else "برخی prerequisiteهای profile fail شده است."
                wizard.unlink()
            except Exception as exc:  # noqa: BLE001
                deployment_message = "Deployment dry-run قابل اجرا نبود: %s" % str(exc)
        add(
            "profile.deployment", "Deployment dry-run", "pass" if deployment_ready else "fail",
            "blocking", deployment_message,
            None if deployment_ready else "/admin?tab=profiles",
        )
        rag_ready = "ai.document.index.job" in env and "ai.rag.index.snapshot" in env
        add(
            "rag.models", "RAG runtime models", "pass" if rag_ready else "required",
            "warning", "مدل‌های RAG در registry موجود هستند." if rag_ready else "Runtime RAG روی appliance باید certification شود.",
            None if rag_ready else "runtime certification",
        )
        latest_run = env["ai.customer.setup.run"].search([
            ("company_id", "=", company.id),
        ], order="started_at desc,id desc", limit=1)
        runtime_ok = bool(latest_run and latest_run.runtime_certification_state == "passed")
        add(
            "runtime.certification", "Runtime certification", "pass" if runtime_ok else "required",
            "blocking", "Runtime certification PASS است." if runtime_ok else "Runtime certification روی target واقعی لازم است.",
            None if runtime_ok else "48_auto_integration_certification.py و benchmark",
        )
        backup_ok = bool(latest_run and latest_run.backup_reference and latest_run.rollback_reference)
        add(
            "handoff.backup", "Backup و rollback evidence", "pass" if backup_ok else "required",
            "blocking", "Backup و rollback reference ثبت شده است." if backup_ok else "Backup و rollback evidence ثبت نشده است.",
            None if backup_ok else "appliance deployment runbook",
        )
        blocking = [check for check in checks if check["severity"] == "blocking"]
        ready = bool(blocking) and all(check["state"] == "pass" for check in blocking)
        return {
            "checks": checks,
            "summary": {
                "ready_for_customer_handoff": ready,
                "blocking_total": len(blocking),
                "blocking_passed": sum(check["state"] == "pass" for check in blocking),
                "warning_total": sum(check["severity"] == "warning" for check in checks),
            },
        }

    @staticmethod
    def _setup_run_values(run):
        return {
            "run_key": run.run_key,
            "company_id": run.company_id.id,
            "state": run.state,
            "current_stage": run.current_stage,
            "runtime_certification_state": run.runtime_certification_state,
            "requested_by": run.requested_by_id.name,
            "started_at": str(run.started_at) if run.started_at else None,
            "completed_at": str(run.completed_at) if run.completed_at else None,
            "error_summary": run.error_summary or "",
            "result": _json.loads(run.result_json or "{}"),
        }

    @http.route("/api/admin/setup/checklist", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def admin_setup_checklist(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        return _json_response(self._setup_checklist(env))

    @http.route("/api/admin/setup/checklist/run", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_setup_checklist_run(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        Run = env["ai.customer.setup.run"]
        run = Run.create({
            "company_id": env.company.id,
            "requested_by_id": env.user.id,
            "release_commit": os.environ.get("AI_RELEASE_COMMIT", "")[:64] or False,
        })
        run.action_start(stage="identity")
        result = self._setup_checklist(env)
        profile = env["ai.customer.configuration.profile"].search([
            ("company_id", "=", env.company.id), ("state", "=", "active"),
        ], limit=1)
        branding = env["ai.customer.branding"].search([
            ("company_id", "=", env.company.id), ("active", "=", True),
        ], limit=1)
        run.write({
            "configuration_profile_id": profile.id if profile else False,
            "branding_version": branding.version if branding else 0,
            "runtime_certification_state": "passed" if result["summary"]["ready_for_customer_handoff"] else "required",
        })
        if result["summary"]["ready_for_customer_handoff"]:
            run.action_pass(result=result)
        else:
            run.action_fail("customer handoff blockers remain", result=result)
        _audit(env, env.user.id, "semantic_api", "admin.setup.checklist.run", {
            "run_key": run.run_key,
            "ready_for_customer_handoff": result["summary"]["ready_for_customer_handoff"],
        }, success=True)
        return _json_response({"run": self._setup_run_values(run)}, status=201)

    @http.route("/api/admin/setup/runs", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def admin_setup_runs(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        runs = env["ai.customer.setup.run"].search([], limit=50)
        return _json_response({"runs": [self._setup_run_values(run) for run in runs]})

    @http.route("/api/admin/setup/runs/<string:run_key>", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def admin_setup_run_get(self, run_key, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        run = env["ai.customer.setup.run"].search([
            ("run_key", "=", run_key), ("company_id", "=", env.company.id),
        ], limit=1)
        if not run:
            return _json_response({"error": "setup run not found"}, status=404)
        return _json_response({"run": self._setup_run_values(run)})

    @http.route("/api/admin/setup/runs/<string:run_key>/evidence", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_setup_run_evidence(self, run_key, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        run = env["ai.customer.setup.run"].search([
            ("run_key", "=", run_key), ("company_id", "=", env.company.id),
        ], limit=1)
        if not run:
            return _json_response({"error": "setup run not found"}, status=404)
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        allowed = {"backup_reference", "rollback_reference", "runtime_certification_state"}
        if sorted(set(payload) - allowed):
            return _json_response({"error": "unsupported evidence fields"}, status=400)
        values = {}
        for key in ("backup_reference", "rollback_reference"):
            if key in payload:
                value = str(payload[key] or "").strip()
                if len(value) > 500:
                    return _json_response({"error": "%s is too long" % key}, status=400)
                values[key] = value or False
        if "runtime_certification_state" in payload:
            state = str(payload["runtime_certification_state"] or "")
            if state not in ("not_run", "required", "passed", "failed"):
                return _json_response({"error": "invalid runtime_certification_state"}, status=400)
            values["runtime_certification_state"] = state
        if not values:
            return _json_response({"error": "at least one evidence field is required"}, status=400)
        run.write(values)
        _audit(env, env.user.id, "semantic_api", "admin.setup.run.evidence", {
            "run_key": run.run_key, "fields": sorted(values),
        }, success=True)
        return _json_response({"run": self._setup_run_values(run)})

    @staticmethod
    def _serialize_sso_provider(provider):
        return {
            "id": provider.id, "name": provider.name, "protocol": provider.protocol,
            "issuer": provider.issuer or "", "client_id": provider.client_id or "",
            "client_secret_ref": provider.client_secret_ref or "",
            "authorization_url": provider.authorization_url or "",
            "token_url": provider.token_url or "", "jwks_url": provider.jwks_url or "",
            "audience": provider.audience or "", "claim_user_id": provider.claim_user_id or "sub",
            "claim_email": provider.claim_email or "email", "claim_groups": provider.claim_groups or "groups",
            "claim_group_mapping_json": provider.claim_group_mapping_json or "{}",
            "active": provider.active, "enforce_for_company": provider.enforce_for_company,
            "auto_provision": provider.auto_provision, "redirect_uri": provider.redirect_uri or "",
            "saml_metadata_url": provider.saml_metadata_url or "",
            "saml_entity_id": provider.saml_entity_id or "",
        }

    @http.route("/api/admin/sso/providers", type="http", auth="none", csrf=False,
                methods=["GET", "POST", "OPTIONS"])
    def admin_sso_providers(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        Provider = env["ai.customer.sso.provider"].sudo()
        if request.httprequest.method == "GET":
            providers = Provider.search([("company_id", "=", env.company.id)], order="name,id")
            return _json_response({"providers": [self._serialize_sso_provider(item) for item in providers]})
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        allowed = {
            "name", "protocol", "issuer", "client_id", "client_secret_ref", "authorization_url",
            "token_url", "jwks_url", "audience", "claim_user_id", "claim_email", "claim_groups",
            "claim_group_mapping_json", "active", "enforce_for_company", "auto_provision",
            "redirect_uri", "saml_metadata_url", "saml_entity_id",
        }
        if sorted(set(payload) - allowed):
            return _json_response({"error": "unsupported SSO provider fields"}, status=400)
        name = str(payload.get("name") or "").strip()
        protocol = str(payload.get("protocol") or "oidc")
        if not name or protocol not in ("oidc", "saml"):
            return _json_response({"error": "name and a valid protocol are required"}, status=400)
        values = {key: payload[key] for key in allowed if key in payload}
        values.update({"name": name, "protocol": protocol, "company_id": env.company.id})
        try:
            provider = Provider.create(values)
        except (ValidationError, AccessError, UserError) as exc:
            return _json_response({"error": str(exc)}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.sso_provider.create", {
            "provider_id": provider.id, "protocol": provider.protocol,
        }, success=True)
        return _json_response({"provider": self._serialize_sso_provider(provider)}, status=201)

    @http.route("/api/admin/sso/providers/<int:provider_id>", type="http", auth="none", csrf=False,
                methods=["PATCH", "DELETE", "OPTIONS"])
    def admin_sso_provider_update(self, provider_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        provider = env["ai.customer.sso.provider"].sudo().search([
            ("id", "=", provider_id), ("company_id", "=", env.company.id),
        ], limit=1)
        if not provider:
            return _json_response({"error": "SSO provider not found"}, status=404)
        if request.httprequest.method == "DELETE":
            provider.write({"active": False, "enforce_for_company": False})
            _audit(env, env.user.id, "semantic_api", "admin.sso_provider.disable", {"provider_id": provider.id}, success=True)
            return _json_response({"status": "disabled"})
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        allowed = {
            "name", "protocol", "issuer", "client_id", "client_secret_ref", "authorization_url",
            "token_url", "jwks_url", "audience", "claim_user_id", "claim_email", "claim_groups",
            "claim_group_mapping_json", "active", "enforce_for_company", "auto_provision",
            "redirect_uri", "saml_metadata_url", "saml_entity_id",
        }
        if sorted(set(payload) - allowed):
            return _json_response({"error": "unsupported SSO provider fields"}, status=400)
        values = {key: payload[key] for key in allowed if key in payload}
        if "protocol" in values and values["protocol"] not in ("oidc", "saml"):
            return _json_response({"error": "invalid protocol"}, status=400)
        try:
            provider.write(values)
        except (ValidationError, AccessError, UserError) as exc:
            return _json_response({"error": str(exc)}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.sso_provider.update", {"provider_id": provider.id}, success=True)
        return _json_response({"provider": self._serialize_sso_provider(provider)})

    @http.route("/api/admin/scim/tokens", type="http", auth="none", csrf=False,
                methods=["GET", "POST", "OPTIONS"])
    def admin_scim_tokens(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        Token = env["ai.customer.scim.token"].sudo()
        if request.httprequest.method == "GET":
            rows = Token.search([("company_id", "=", env.company.id)], order="id desc")
            return _json_response({"tokens": [{
                "id": row.id, "name": row.name, "active": row.active,
                "expires_at": str(row.expires_at) if row.expires_at else None,
                "last_used_at": str(row.last_used_at) if row.last_used_at else None,
            } for row in rows]})
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        name = str(payload.get("name") or "").strip()
        if not name or len(name) > 200:
            return _json_response({"error": "token name is required"}, status=400)
        expires_at = payload.get("expires_at") or False
        if expires_at:
            expires_at = str(expires_at).replace("T", " ")
            if len(expires_at) == 16:
                expires_at += ":00"
        try:
            token, raw = Token.issue(name, company=env.company, expires_at=expires_at)
        except (ValidationError, AccessError, UserError, ValueError) as exc:
            return _json_response({"error": str(exc)}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.scim_token.create", {"token_id": token.id}, success=True)
        return _json_response({
            "token": {"id": token.id, "name": token.name, "active": token.active,
                      "expires_at": str(token.expires_at) if token.expires_at else None},
            "token_value": raw,
            "warning": "The token value is shown once; store it in the IdP configuration.",
        }, status=201)

    @http.route("/api/admin/scim/tokens/<int:token_id>/revoke", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_scim_token_revoke(self, token_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        token = env["ai.customer.scim.token"].sudo().search([
            ("id", "=", token_id), ("company_id", "=", env.company.id),
        ], limit=1)
        if not token:
            return _json_response({"error": "SCIM token not found"}, status=404)
        token.write({"active": False})
        _audit(env, env.user.id, "semantic_api", "admin.scim_token.revoke", {"token_id": token.id}, success=True)
        return _json_response({"status": "revoked"})

    @http.route("/api/admin/scim/groups", type="http", auth="none", csrf=False,
                methods=["GET", "POST", "OPTIONS"])
    def admin_scim_groups(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        Mapping = env["ai.customer.scim.group"].sudo()
        if request.httprequest.method == "GET":
            rows = Mapping.search([("company_id", "=", env.company.id)], order="name,id")
            return _json_response({"groups": [{
                "id": row.id, "name": row.name, "group_id": row.group_id.id,
                "group_name": row.group_id.name, "active": row.active,
            } for row in rows]})
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        try:
            group = env["res.groups"].sudo().browse(int(payload.get("group_id"))).exists()
        except (TypeError, ValueError):
            group = False
        if not group:
            return _json_response({"error": "valid group_id is required"}, status=400)
        xmlids = set(group.get_external_id().values())
        if not any(value.startswith("ai_business_tools.role_") for value in xmlids):
            return _json_response({"error": "SCIM may manage only product roles"}, status=403)
        try:
            mapping = Mapping.create({
                "name": str(payload.get("name") or group.name).strip(),
                "company_id": env.company.id, "group_id": group.id,
            })
        except (ValidationError, AccessError, UserError) as exc:
            return _json_response({"error": str(exc)}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.scim_group.create", {"mapping_id": mapping.id}, success=True)
        return _json_response({"group": {
            "id": mapping.id, "name": mapping.name, "group_id": group.id,
            "group_name": group.name, "active": mapping.active,
        }}, status=201)

    @http.route("/api/admin/departments", type="http", auth="none", csrf=False,
                methods=["GET", "POST", "OPTIONS"])
    def admin_departments(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        if "hr.department" not in env:
            return _json_response({"error": "department model is not installed"}, status=503)
        Department = env["hr.department"].sudo()
        if request.httprequest.method == "GET":
            rows = Department.search([("company_id", "=", env.company.id)], order="complete_name,id")
            return _json_response({"departments": [{
                "id": row.id, "name": row.name, "complete_name": row.complete_name,
                "parent_id": row.parent_id.id if row.parent_id else None,
                "manager_id": row.manager_id.id if row.manager_id else None,
                "manager": row.manager_id.name if row.manager_id else None,
            } for row in rows]})
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        name = str(payload.get("name") or "").strip()
        if not name or len(name) > 200:
            return _json_response({"error": "department name is required"}, status=400)
        values = {"name": name, "company_id": env.company.id}
        if payload.get("parent_id"):
            try:
                parent = Department.search([("id", "=", int(payload["parent_id"])), ("company_id", "=", env.company.id)], limit=1)
            except (TypeError, ValueError):
                parent = False
            if not parent:
                return _json_response({"error": "invalid parent department"}, status=400)
            values["parent_id"] = parent.id
        if payload.get("manager_id"):
            try:
                manager = env["res.users"].sudo().search([
                    ("id", "=", int(payload["manager_id"])), ("company_ids", "in", env.company.id),
                ], limit=1)
            except (TypeError, ValueError):
                manager = False
            if not manager:
                return _json_response({"error": "invalid department manager"}, status=400)
            values["manager_id"] = manager.id
        try:
            row = Department.create(values)
        except (ValidationError, AccessError, UserError) as exc:
            return _json_response({"error": str(exc)}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.department.create", {"department_id": row.id}, success=True)
        return _json_response({"department": {"id": row.id, "name": row.name, "complete_name": row.complete_name}}, status=201)

    @http.route("/api/admin/role-assignments", type="http", auth="none", csrf=False,
                methods=["GET", "POST", "OPTIONS"])
    def admin_role_assignments(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        Assignment = env["ai.customer.role.assignment"].sudo()
        if request.httprequest.method == "GET":
            rows = Assignment.search([("company_id", "=", env.company.id)], order="active desc,id desc")
            return _json_response({"assignments": [{
                "id": row.id, "user_id": row.user_id.id if row.user_id else None,
                "user": row.user_id.name if row.user_id else None,
                "role_group_id": row.role_group_id.id, "role": row.role_group_id.name,
                "source": row.source, "department_id": row.department_id.id if row.department_id else None,
                "active": row.active, "expires_at": str(row.expires_at) if row.expires_at else None,
                "reason": row.reason or "",
            } for row in rows]})
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        try:
            user = env["res.users"].sudo().browse(int(payload.get("user_id"))).exists()
            group = env["res.groups"].sudo().browse(int(payload.get("role_group_id"))).exists()
        except (TypeError, ValueError):
            user = group = False
        if not user or not group or env.company not in user.company_ids:
            return _json_response({"error": "user and company role are required"}, status=400)
        xmlids = set(group.get_external_id().values())
        if not any(value.startswith("ai_business_tools.role_") for value in xmlids):
            return _json_response({"error": "only product roles may be assigned"}, status=403)
        values = {
            "user_id": user.id, "role_group_id": group.id, "source": "direct",
            "company_id": env.company.id, "managed_by": "admin",
            "reason": str(payload.get("reason") or "Admin console assignment")[:500],
            "expires_at": payload.get("expires_at") or False,
        }
        try:
            assignment = Assignment.create(values)
        except (ValidationError, AccessError, UserError) as exc:
            return _json_response({"error": str(exc)}, status=409)
        _audit(env, env.user.id, "semantic_api", "admin.role_assignment.create", {"assignment_id": assignment.id}, success=True)
        return _json_response({"assignment": {
            "id": assignment.id, "user_id": user.id, "user": user.name,
            "role_group_id": group.id, "role": group.name, "source": assignment.source,
            "active": assignment.active,
        }}, status=201)

    @http.route("/api/admin/role-assignments/<int:assignment_id>/revoke", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_role_assignment_revoke(self, assignment_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        assignment = env["ai.customer.role.assignment"].sudo().search([
            ("id", "=", assignment_id), ("company_id", "=", env.company.id),
        ], limit=1)
        if not assignment:
            return _json_response({"error": "role assignment not found"}, status=404)
        assignment.write({"active": False})
        _audit(env, env.user.id, "semantic_api", "admin.role_assignment.revoke", {"assignment_id": assignment.id}, success=True)
        return _json_response({"status": "revoked"})

    @staticmethod
    def _branding_record(env, create=False):
        Branding = env["ai.customer.branding"]
        record = Branding.search([
            ("company_id", "=", env.company.id),
            ("active", "=", True),
        ], limit=1)
        if not record and create:
            record = Branding.create({
                "company_id": env.company.id,
                "brand_name": env.company.name or "Company AI",
                "legal_name": env.company.name or False,
            })
        return record

    @staticmethod
    def _branding_values(env, admin=False):
        record = AiSemanticApiController._branding_record(env)
        if record:
            return record.admin_values() if admin else record.public_values()
        values = dict(_BRAND_DEFAULTS)
        values.update({
            "brand_name": env.company.name or "Company AI",
            "product_title": env.company.name or "Company AI",
            "tagline": "",
            "brand_domain": "",
            "footer_text": "",
            "login_message": "",
            "support_email": "",
            "support_url": "",
            "show_ai_brand": True,
            "show_powered_by": False,
            "show_module_navigation": True,
            "support_contact_visible": True,
            "version": 0,
            "logo_url": None,
            "favicon_url": None,
            "has_logo": False,
            "has_favicon": False,
        })
        if admin:
            values.update({
                "company_id": env.company.id,
                "company_name": env.company.name or "",
                "legal_name": env.company.name or "",
                "logo_filename": "",
                "favicon_filename": "",
                "updated_by": None,
                "updated_at": None,
            })
        return values

    @http.route("/api/branding", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def branding(self, **kwargs):
        """Return safe company-scoped branding to any authenticated user."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        return _json_response(self._branding_values(env))

    def _branding_asset(self, env, asset_name):
        record = self._branding_record(env)
        if not record:
            return _json_response({"error": "brand asset is not configured"}, status=404)
        content = getattr(record, asset_name, False)
        if not content:
            return _json_response({"error": "brand asset is not configured"}, status=404)
        try:
            raw = base64.b64decode(content, validate=True)
        except (TypeError, ValueError):
            return _json_response({"error": "stored brand asset is invalid"}, status=415)
        mimetype = getattr(record, "%s_mimetype" % asset_name, False) or "application/octet-stream"
        return Response(
            raw,
            headers=[
                ("Content-Type", mimetype),
                ("Content-Disposition", "inline"),
                ("Cache-Control", "private, max-age=0, must-revalidate"),
            ] + _CORS_HEADERS,
            status=200,
        )

    @http.route("/api/branding/logo", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def branding_logo(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        return self._branding_asset(env, "logo")

    @http.route("/api/branding/favicon", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def branding_favicon(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        return self._branding_asset(env, "favicon")

    @http.route("/api/admin/setup", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def admin_setup(self, **kwargs):
        """Return the company/setup identity needed by the first wizard step."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        company = env.company.sudo()
        return _json_response({
            "company": {
                "id": company.id,
                "name": company.name or "",
                "email": company.email or "",
                "phone": company.phone or "",
                "website": company.website or "",
                "street": company.street or "",
                "street2": company.street2 or "",
                "city": company.city or "",
                "zip": company.zip or "",
                "country_id": company.country_id.id if company.country_id else None,
                "country_name": company.country_id.name if company.country_id else "",
                "currency_id": company.currency_id.id if company.currency_id else None,
                "currency_name": company.currency_id.name if company.currency_id else "",
            },
            "branding": self._branding_values(env, admin=True),
        })

    @http.route("/api/admin/setup/company", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_setup_company(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        allowed = {
            "name", "email", "phone", "website", "street", "street2", "city", "zip",
            "country_id", "currency_id",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            return _json_response({"error": "unsupported company fields"}, status=400)
        values = {key: str(payload[key] or "").strip() for key in allowed if key in payload}
        if "name" in values and not values["name"]:
            return _json_response({"error": "company name is required"}, status=400)
        if "email" in values and values["email"] and not _BRAND_EMAIL_RE.fullmatch(values["email"]):
            return _json_response({"error": "company email is invalid"}, status=400)
        if "website" in values and values["website"]:
            parsed = urlparse(values["website"])
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return _json_response({"error": "website must be an http or https URL"}, status=400)
        for field_name in ("country_id", "currency_id"):
            if field_name not in payload:
                continue
            try:
                model_name = "res.country" if field_name == "country_id" else "res.currency"
                record = env[model_name].sudo().browse(int(payload[field_name])).exists()
            except (TypeError, ValueError):
                record = False
            if not record:
                return _json_response({"error": "%s is invalid" % field_name}, status=400)
            values[field_name] = record.id
        env.company.sudo().write(values)
        _audit(env, env.user.id, "semantic_api", "admin.company.update", {
            "fields": sorted(values),
        }, success=True)
        return self.admin_setup()

    @http.route("/api/admin/branding", type="http", auth="none", csrf=False,
                methods=["GET", "POST", "OPTIONS"])
    def admin_branding(self, **kwargs):
        """Manage explicit, versioned, company-scoped white-label settings."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        if request.httprequest.method == "GET":
            return _json_response(self._branding_values(env, admin=True))

        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        allowed = _BRAND_TEXT_FIELDS | _BRAND_BOOL_FIELDS | {
            "logo_base64", "logo_filename", "favicon_base64", "favicon_filename",
            "clear_logo", "clear_favicon",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            return _json_response({"error": "unsupported branding fields"}, status=400)

        values = {}
        for field_name in _BRAND_TEXT_FIELDS:
            if field_name not in payload:
                continue
            value = str(payload[field_name] or "").strip()
            if field_name in _BRAND_COLOR_FIELDS and not _BRAND_COLOR_RE.fullmatch(value):
                return _json_response({"error": "%s must be a six-digit hexadecimal color" % field_name}, status=400)
            values[field_name] = value
        for field_name in _BRAND_BOOL_FIELDS:
            if field_name in payload:
                try:
                    values[field_name] = _strict_bool(payload[field_name], field_name)
                except ValidationError as exc:
                    return _json_response({"error": str(exc)}, status=400)
        if "support_email" in values and values["support_email"] and not _BRAND_EMAIL_RE.fullmatch(values["support_email"]):
            return _json_response({"error": "support_email is invalid"}, status=400)
        for field_name in ("brand_domain", "support_url"):
            if field_name in values and values[field_name]:
                parsed = urlparse(values[field_name])
                if parsed.scheme not in ("http", "https") or not parsed.netloc:
                    return _json_response({"error": "%s must be an http or https URL" % field_name}, status=400)

        asset_audit = []
        for asset_name, base_field, filename_field in (
            ("logo", "logo_base64", "logo_filename"),
            ("favicon", "favicon_base64", "favicon_filename"),
        ):
            clear_field = "clear_%s" % asset_name
            if clear_field in payload:
                try:
                    clear = _strict_bool(payload[clear_field], clear_field)
                except ValidationError as exc:
                    return _json_response({"error": str(exc)}, status=400)
                if clear and (base_field in payload or filename_field in payload):
                    return _json_response({"error": "cannot upload and clear the same asset"}, status=400)
                if clear:
                    values[asset_name] = False
                    values["%s_filename" % asset_name] = False
                    values["%s_mimetype" % asset_name] = False
                    asset_audit.append("%s.cleared" % asset_name)
            if base_field in payload or filename_field in payload:
                try:
                    encoded, upload = _decode_brand_asset(payload, base_field, filename_field)
                except (TypeError, ValueError, ValidationError) as exc:
                    return _json_response({"error": str(exc)}, status=400)
                values[asset_name] = encoded
                values["%s_filename" % asset_name] = upload["filename"]
                values["%s_mimetype" % asset_name] = upload["mimetype"]
                asset_audit.append("%s.updated" % asset_name)

        try:
            branding = self._branding_record(env, create=True)
            branding.write(values)
        except (AccessError, UserError, ValidationError) as exc:
            return _json_response({"error": str(exc)}, status=400)
        _audit(env, env.user.id, "semantic_api", "admin.branding.update", {
            "fields": sorted(set(values) - {"logo", "favicon"}),
            "assets": asset_audit,
            "version": branding.version,
        }, success=True)
        return _json_response({"status": "updated", "branding": branding.admin_values()})

    # ------------------------------------------------------------
    # Integrations - Telegram. Until now, linking a Telegram chat to
    # an Odoo user only had ONE door: an Odoo backend wizard ("AI
    # Telegram" > "Generate Link Code", ai_telegram_bridge/wizard/
    # telegram_link_wizard.py). That meant an employee who only ever
    # uses the React portal still had to be walked into the Odoo
    # backend once, just to get a code - exactly the kind of thing
    # roadmap #43/44 (Semantic API / frontend) exists to avoid.
    #
    # This wraps the SAME two models the wizard and the webhook
    # controller (ai_telegram_bridge/controllers/telegram.py) already
    # use - ai.gateway.telegram.link[.code] - no new linking logic,
    # just a semantic HTTP door onto it, same pattern as every other
    # endpoint in this file. ai_telegram_bridge stays a SOFT
    # dependency here (like ai.gateway.model.policy/audit.log in
    # ai_gateway/controllers/gateway.py, and llm.assistant above) -
    # it is a deliberately-optional, manually-installed pilot module
    # (roadmap #60's own note: "نصب دستیه، نه بخشی از
    # 02_install_modules.sh"), so this endpoint must keep working
    # (by reporting "not available") on any install that hasn't
    # opted into it, not crash or 500.
    # ------------------------------------------------------------
    @http.route("/api/integrations/telegram", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def integrations_telegram_status(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        return _json_response(self._telegram_status(env))

    @http.route("/api/integrations/telegram/code", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def integrations_telegram_generate_code(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        if "ai.gateway.telegram.link" not in env:
            return _json_response({"error": "Telegram integration is not installed on this system"},
                                   status=404)

        existing = env["ai.gateway.telegram.link"].sudo().search(
            [("user_id", "=", env.user.id), ("active", "=", True)], limit=1
        )
        if existing:
            return _json_response({"error": "already linked - unlink first"}, status=409)

        code_rec = env["ai.gateway.telegram.link.code"].generate_for_current_user()
        _audit(env, env.user.id, "semantic_api", "integrations.telegram.code", {}, success=True)
        return _json_response({
            "code": code_rec.code,
            "bot_username": env["ir.config_parameter"].sudo().get_param(
                "ai_telegram_bridge.bot_username", ""
            ),
            # Kept in sync by hand with CODE_TTL_MINUTES in
            # ai_telegram_bridge/models/telegram_link_code.py (not
            # imported directly - ai_telegram_bridge is a soft
            # dependency, see class-level note above; a static import
            # of its python module would silently turn that back into
            # a hard one).
            "expires_in_minutes": 10,
        })

    @http.route("/api/integrations/telegram/unlink", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def integrations_telegram_unlink(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        if "ai.gateway.telegram.link" not in env:
            return _json_response({"error": "Telegram integration is not installed on this system"},
                                   status=404)

        link = env["ai.gateway.telegram.link"].sudo().search([("user_id", "=", env.user.id)], limit=1)
        if link:
            # Deactivate, don't unlink() - same as the admin-side
            # disconnect (Settings > Administration > Telegram Links)
            # already documented in roadmap #60, keeps history/audit
            # trail instead of erasing the row.
            link.write({"active": False})
        _audit(env, env.user.id, "semantic_api", "integrations.telegram.unlink", {}, success=True)
        return _json_response(self._telegram_status(env))

    @staticmethod
    def _telegram_status(env):
        if "ai.gateway.telegram.link" not in env:
            return {"available": False}
        bot_username = env["ir.config_parameter"].sudo().get_param("ai_telegram_bridge.bot_username", "")
        link = env["ai.gateway.telegram.link"].sudo().search(
            [("user_id", "=", env.user.id), ("active", "=", True)], limit=1
        )
        if not link:
            return {"available": True, "linked": False, "bot_username": bot_username}
        return {
            "available": True,
            "linked": True,
            "bot_username": bot_username,
            "linked_date": str(link.linked_date) if link.linked_date else None,
            "last_message_date": str(link.last_message_date) if link.last_message_date else None,
        }


# Universal capability/integration surfaces. These are intentionally semantic:
# the frontend never needs to know an internal ERP model name to render a UI.
from odoo import http as _http


def _module_registry_json(value, default):
    try:
        parsed = _json.loads(value or _json.dumps(default))
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, ValueError):
        return default


class AiControlPlaneSemanticController(_http.Controller):
    @http.route("/api/me/capabilities", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def my_capabilities(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        caps = env["ai.control.authorization"].effective_capabilities(user=env.user)
        return _json_response({
            "capabilities": _public_capabilities(caps),
            "is_admin": _is_privileged(env, env.user),
        })

    @http.route("/api/integrations", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def integrations(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        if not env.user.has_group("base.group_system"):
            return _json_response({"error": "access denied"}, status=403)
        modules = env["ai.control.module"].sudo().search([], order="name")
        rows = []
        for m in modules:
            adapter = env["ai.integration.adapter"].sudo().for_module(m.technical_name) if "ai.integration.adapter" in env else False
            mappings = env["ai.integration.event.mapping"].sudo().search([("module_name", "=", m.technical_name), ("active", "=", True)]) if "ai.integration.event.mapping" in env else []
            rows.append({
                "name": m.name, "technical_name": m.technical_name, "version": m.version,
                "state": m.state, "integration_level": m.integration_level,
                "certification_state": m.certification_state,
                "adapter_state": adapter.state if adapter else "missing",
                "models": _module_registry_json(getattr(m, "model_names_json", "[]"), []),
                "groups": _module_registry_json(getattr(m, "group_names_json", "[]"), []),
                "menus": _module_registry_json(getattr(m, "menu_names_json", "[]"), []),
                "views": _module_registry_json(getattr(m, "view_names_json", "[]"), []),
                "scope": _module_registry_json(getattr(m, "scope_json", "{}"), {}),
                "capabilities": m.capability_count,
                "discovered_operations": m.discovered_operation_count,
                "reviewed_operations": m.reviewed_operation_count,
                "event_mappings": [{"model": x.model_name, "operation": x.operation, "event_type": x.event_type, "source": x.source} for x in mappings],
                "unavailable_mutations": _module_registry_json(getattr(m, "unavailable_mutations_json", "[]"), []),
                "automatic_read": m.automatic_read,
                "automatic_events": m.automatic_events,
                "automatic_audit": m.automatic_audit,
                "agent_connection": {
                    "connected": bool(getattr(m, "agent_connected", False)),
                    "state": getattr(m, "agent_connection_state", "disconnected"),
                    "tool_count": getattr(m, "agent_tool_count", 0),
                    "operation_count": getattr(m, "agent_operation_count", 0),
                    "last_sync": str(getattr(m, "agent_last_sync", False)) if getattr(m, "agent_last_sync", False) else None,
                    "error": getattr(m, "agent_error", False),
                },
                "last_sync": m.last_sync,
                "status": getattr(m, "integration_status", "ready"),
                "error": m.last_error,
            })
        return _json_response({"integrations": rows})

class AiIntegrationRegistrySemanticController(http.Controller):
    """Read-only semantic surfaces for the Integration/Capability UI."""

    @http.route('/api/integrations/operations', type='http', auth='none', csrf=False, methods=['GET', 'OPTIONS'])
    def integration_operations(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        if not _is_privileged(env, env.user):
            return _json_response({'error': 'access denied'}, status=403)
        rows = env['ai.integration.operation'].sudo().search([('active', '=', True)], order='module_name,tool_name')
        return _json_response({'operations': [{
            'tool': r.tool_name, 'module': r.module_name, 'capability': r.capability_name,
            'operation': r.operation, 'risk_level': r.risk_level, 'handler': r.handler_key,
            'source': r.source, 'coverage': r.coverage,
        } for r in rows]})

    @http.route('/api/integrations/certification', type='http', auth='none', csrf=False, methods=['GET', 'OPTIONS'])
    def integration_certification(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        if not _is_privileged(env, env.user):
            return _json_response({'error': 'access denied'}, status=403)
        rows = env['ai.integration.certification'].sudo().search([], order='checked_at desc', limit=200)
        return _json_response({'certifications': [{
            'module': r.module_name, 'status': r.status,
            'checks': _json.loads(r.checks_json or '[]'), 'checked_at': str(r.checked_at),
            'error': r.error,
        } for r in rows]})
