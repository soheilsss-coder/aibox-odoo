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
import json as _json
import logging
import os

from odoo import fields as odoo_fields
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError, AccessDenied, UserError

from odoo.addons.ai_gateway.controllers.gateway import (
    _authenticate,
    _check_rate_limit,
    _json_response,
    _cors_preflight_response,
    _audit,
    _is_privileged,
    _client_ip,
    _auth_fail_blocked,
    _record_auth_failure,
    _CORS_HEADERS,
)
from werkzeug.wrappers import Response
from urllib.parse import quote as _quote_filename

_logger = logging.getLogger(__name__)


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
    return request.env(user=user.id), None


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
        return _json.loads(request.httprequest.data or b"{}"), None
    except ValueError:
        return None, _json_response({"error": "invalid JSON body"}, status=400)


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
        login_id = (body.get("login") or "").strip()
        password = body.get("password") or ""
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
        token, expires = env["ai.gateway.session"].sudo().issue(user)
        response = _json_response({
            "authenticated": True,
            "user": {"id": user.id, "name": user.name, "login": user.login},
            "expires_at": expires,
        })
        response.set_cookie("ai_session", token, max_age=8 * 3600, httponly=True, secure=os.environ.get("AI_GATEWAY_COOKIE_SECURE", "1" if os.environ.get("AI_GATEWAY_ALLOWED_ORIGIN", "").startswith("https://") else "0") == "1", samesite=os.environ.get("AI_GATEWAY_COOKIE_SAMESITE", "None" if os.environ.get("AI_GATEWAY_ALLOWED_ORIGIN", "").startswith("https://") else "Lax"), path="/")
        return response

    @http.route("/api/logout", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def logout(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        token = request.httprequest.cookies.get("ai_session", "").strip()
        if token and "ai.gateway.session" in request.env:
            rec = request.env["ai.gateway.session"].sudo().authenticate_token(token)
            if rec:
                rec.revoke()
        response = _json_response({"authenticated": False})
        response.delete_cookie("ai_session", path="/")
        return response

    @http.route("/api/session/rotate", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def rotate_session(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        token = request.httprequest.cookies.get("ai_session", "").strip()
        if not token or "ai.gateway.session" not in request.env:
            return _json_response({"error": "not_authenticated"}, status=401)
        _, new_token, expires = request.env["ai.gateway.session"].sudo().rotate(
            token, user_agent=request.httprequest.headers.get("User-Agent"), ttl_hours=8
        )
        if not new_token:
            return _json_response({"error": "invalid_or_expired_session"}, status=401)
        response = _json_response({"authenticated": True, "expires_at": expires})
        response.set_cookie(
            "ai_session", new_token, max_age=8 * 3600, httponly=True,
            secure=os.environ.get("AI_GATEWAY_COOKIE_SECURE", "1") == "1",
            samesite=os.environ.get("AI_GATEWAY_COOKIE_SAMESITE", "Lax"), path="/"
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
        employee = env["hr.employee"].search([("user_id", "=", user.id)], limit=1)
        capabilities = env["ai.control.authorization"].effective_capabilities(user=user) if "ai.control.authorization" in env else self.env["ai.control.capability"].browse()
        capability_names = sorted(capabilities.mapped("name"))
        return _json_response({
            "id": user.id,
            "name": user.name,
            "login": user.login,
            "company": env.company.name,
            "is_manager": bool(employee.child_ids) if employee else False,
            # Phase 7: lets the frontend decide whether to show the
            # "Admin Console" nav item at all - the backend still
            # re-checks this on every /api/admin/* call regardless,
            # this is only for not showing a link that would 403.
            "is_admin": _is_privileged(env, user),  # legacy informational field; never use for authorization
            "capabilities": capability_names,
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
        employee = env["hr.employee"].search([("user_id", "=", env.user.id)], limit=1)
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

        employee = env["hr.employee"].search([("user_id", "=", env.user.id)], limit=1)
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
        access_level = payload.get("access_level", "personal")
        if not name:
            return _json_response({"error": "'name' is required"}, status=400)
        if access_level not in ("company", "group", "department", "personal"):
            return _json_response({"error": "invalid access_level"}, status=400)

        values = {
            "name": name,
            "description": payload.get("description", ""),
            "access_level": access_level,
            "owner_id": env.user.id,
        }
        if payload.get("file_base64"):
            values["file"] = payload["file_base64"]
            values["file_name"] = payload.get("file_name", name)

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
                employee = env["hr.employee"].search([("user_id", "=", env.user.id)], limit=1)
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
        employee = env["hr.employee"].search([("user_id", "=", env.user.id)], limit=1)
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
        raw = content
        if isinstance(raw, bytes):
            pass
        elif hasattr(raw, "encode"):
            raw = raw.encode("latin1", errors="surrogateescape")
        else:
            raw = bytes(raw)
        import os as _os
        filename = doc.file_name or (doc.name or "document")
        _, ext = _os.path.splitext(filename)
        mimetype = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "txt": "text/plain", "csv": "text/csv", "md": "text/markdown"}.get(
            (ext or "").lstrip(".").lower(), "application/octet-stream")
        return Response(
            raw,
            headers=[
                ("Content-Type", mimetype),
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

    @http.route("/api/documents/search", type="json", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def documents_search(self, **params):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return {"error": "invalid or missing API key"}

        query = params.get("query", "")
        top_k = params.get("top_k", 5)
        if not query:
            return {"error": "'query' is required"}

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
            return {"results": results}
        except UserError as exc:
            _audit(env, env.user.id, "semantic_api", "documents.search",
                   {"query": query}, success=False, error_message=str(exc))
            return {"error": "semantic search failed"}

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
        }

    # ------------------------------------------------------------------
    # Admin Console (roadmap #46). Every route below is gated by
    # _require_privileged() - see that function's docstring. This is
    # deliberately a THIN read/write layer over models that already
    # exist (res.groups, ai.gateway.access.grant, ai.gateway.tool.risk,
    # res.company/ir.config_parameter) - no new admin-only model was
    # created, matching how #4/#6's Role Permissions Overview already
    # reused res.groups directly instead of inventing one.
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
                "members": [{"id": u.id, "name": u.name, "login": u.login} for u in r.users],
                "member_count": len(r.users),
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
        users = env["res.users"].sudo().search([("share", "=", False)], order="name")
        result = []
        for u in users:
            employee = env["hr.employee"].sudo().search([("user_id", "=", u.id)], limit=1)
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

        grants = env["ai.gateway.access.grant"].sudo().search([], order="create_date desc")
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

        to_user = env["res.users"].sudo().browse(to_user_id)
        group = env["res.groups"].sudo().browse(group_id)
        if not to_user.exists() or not group.exists():
            return _json_response({"error": "invalid to_user_id or group_id"}, status=400)

        delegated_from_id = payload.get("delegated_from_id") or False
        grant = env["ai.gateway.access.grant"].sudo().create({
            "to_user_id": to_user.id,
            "group_id": group.id,
            "delegated_from_id": delegated_from_id,
            "start_date": payload.get("start_date") or str(odoo_fields.Date.context_today(env.user)),
            "expires_on": expires_on,
            "reason": payload.get("reason", ""),
            "granted_by_id": env.user.id,
        })
        _audit(env, env.user.id, "semantic_api", "admin.access_grants.create",
               {"to_user": to_user.name, "group": group.name, "expires_on": expires_on}, success=True)
        return _json_response(self._serialize_grant(grant), status=201)

    @http.route("/api/admin/access-grants/<int:grant_id>/revoke", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_access_grant_revoke(self, grant_id, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        grant = env["ai.gateway.access.grant"].sudo().browse(grant_id)
        if not grant.exists():
            return _json_response({"error": "not found"}, status=404)
        grant.action_revoke_now()
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
        docs = env["company.document"].sudo().search([], order="create_date desc")
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
                "name": r.tool_name,
                "risk_level": r.risk_level,
                "requires_approval_from": r.approver_group_id.name if r.approver_group_id else None,
                "description": r.description or "",
            }
            for r in risks
        ]

        assistants = []
        if "llm.assistant" in env:
            for a in env["llm.assistant"].sudo().search([]):
                assistants.append({
                    "name": a.name,
                    "model": a.model_id.name if getattr(a, "model_id", False) else None,
                    "provider": a.model_id.provider_id.name
                                if getattr(a, "model_id", False) and a.model_id.provider_id else None,
                    "tool_count": len(a.tool_ids) if hasattr(a, "tool_ids") else None,
                    "active": a.active,
                })

        vision_api_base = env["ir.config_parameter"].sudo().get_param(
            "company_ai_demo.vision_api_base", None)

        return _json_response({
            "tools": tools,
            "assistants": assistants,
            "vision_api_base": vision_api_base,
        })

    @http.route("/api/admin/branding", type="http", auth="none", csrf=False, methods=["GET", "POST", "OPTIONS"])
    def admin_branding(self, **kwargs):
        """White-label settings (#55) - reads/writes exactly the two
        things ai_debrand's data file sets as placeholders
        (res.company.report_footer, the ai.brand.name/ai.brand.domain config
        parameters), nothing more. HONEST NOTE: this does not touch the
        actual logo image or the login-page template text (those stay
        a manual step for now, same as item #55 already said) - only
        the two text values that are otherwise easy to forget to
        change per customer."""
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_privileged()
        if err:
            return err
        if request.httprequest.method == "GET":
            company = env.company.sudo()
            report_url = env["ir.config_parameter"].sudo().get_param("ai.brand.domain", "")
            brand_name = env["ir.config_parameter"].sudo().get_param("ai.brand.name", "") or company.report_footer or ""
            return _json_response({
                "brand_name": brand_name,
                "company_name": company.name or "",
                "brand_domain": report_url,
                "has_logo": bool(company.logo),
            })

        payload, body_err = _read_json_body()
        if body_err:
            return body_err
        company = env.company.sudo()
        values = {}
        if "brand_name" in payload:
            values["report_footer"] = payload["brand_name"]
            env["ir.config_parameter"].sudo().set_param("ai.brand.name", payload["brand_name"])
        if values:
            company.write(values)
        if "brand_domain" in payload:
            env["ir.config_parameter"].sudo().set_param("ai.brand.domain", payload["brand_domain"])
        _audit(env, env.user.id, "semantic_api", "admin.branding.update", payload, success=True)
        return _json_response({"status": "updated"})

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


class AiControlPlaneSemanticController(_http.Controller):
    @http.route("/api/me/capabilities", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def my_capabilities(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        caps = env["ai.control.authorization"].effective_capabilities(user=env.user)
        return _json_response({"capabilities": [{
            "name": c.name, "module": c.module_name, "operation": c.operation,
            "risk_level": c.risk_level, "model": c.model_name,
        } for c in caps]})

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
        return _json_response({"integrations": [{
            "name": m.name, "technical_name": m.technical_name, "version": m.version,
            "state": m.state, "models": m.discovered_models, "groups": m.discovered_groups,
            "capabilities": m.capability_count, "last_sync": m.last_sync,
            "status": getattr(m, "integration_status", "ready"),
        } for m in modules]})

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
