"""Admin Panel API — a separate world from the employee workspace.

Every route here authenticates ONLY via the isolated admin-panel session
cookie (aibox_admin_session), issued by /api/admin/panel/login after a
username/password check against a base.group_system user. Employee
workspace API keys / session cookies are deliberately NOT accepted.
"""
import logging
import os

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

_COOKIE = "aibox_admin_session"
_SECURE_COOKIE = os.environ.get("AI_GATEWAY_COOKIE_SECURE",
                                "1" if os.environ.get("AI_GATEWAY_ALLOWED_ORIGIN", "").startswith("https://") else "0") == "1"


def _json(data, status=200):
    return request.make_response(
        __import__("json").dumps(data, ensure_ascii=False, default=str),
        headers=[("Content-Type", "application/json; charset=utf-8")],
        status=status,
    )



def _panel_env():
    """Superuser env for panel operations.

    Under ``auth="none"`` ``request.env.user`` is an EMPTY recordset; module
    code touched by panel writes (e.g. ``hr`` res.users.write) calls
    ``self.env.user.has_group(...)`` which requires a singleton. Running
    under the superuser env keeps every downstream ``env.user`` valid.
    """
    import odoo

    return request.env(user=odoo.SUPERUSER_ID)["ai.gateway.admin.panel"]


def _require_admin():
    """Return (admin_user, None) or (None, error_response)."""
    token = request.httprequest.cookies.get(_COOKIE, "").strip()
    user = request.env["ai.gateway.admin.panel.session"].sudo().resolve(token) if token else None
    if not user:
        return None, _json({"error": "admin authentication required"}, status=401)
    return user, None


class AdminPanelController(http.Controller):

    @http.route("/api/admin/panel/login", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def login(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _json({"ok": True})
        try:
            body = __import__("json").loads(request.httprequest.data or b"{}")
        except Exception:  # noqa: BLE001
            return _json({"error": "invalid body"}, status=400)
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        if not username or not password:
            return _json({"error": "username and password are required"}, status=400)
        # Brute-force guard: same limiter as the gateway login.
        from odoo.addons.ai_gateway.controllers.gateway import (
            _auth_fail_blocked, _client_ip, _record_auth_failure,
        )
        ip = _client_ip()
        if _auth_fail_blocked(ip):
            return _json({"error": "too many failed attempts, try again shortly"}, status=429)
        user = request.env["res.users"].sudo().search([("login", "=", username)], limit=1)
        ok = False
        if user:
            # The password hash is only readable by the user's own env, so
            # verify inside a dedicated cursor as that user (request.env
            # may carry a different uid whose ACLs hide password).
            import odoo as _odoo

            registry = _odoo.registry(request.db)
            with registry.cursor() as cr:
                check_env = _odoo.api.Environment(cr, user.id, {})
                try:
                    check_env["res.users"].browse(user.id)._check_credentials(
                        {"type": "password", "password": password},
                        {"interactive": True})
                    ok = True
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("admin login check failed: %s: %s",
                                    type(exc).__name__, exc)
                    ok = False
        if not ok or not user.has_group("base.group_system"):
            _record_auth_failure(ip)
            return _json({"error": "invalid admin credentials"}, status=401)
        token = request.env["ai.gateway.admin.panel.session"].sudo().issue_for(user)
        if not token:
            return _json({"error": "not an administrator"}, status=403)
        resp = _json({"ok": True, "user": {"name": user.name, "login": user.login}})
        resp.set_cookie(_COOKIE, token, max_age=8 * 3600, httponly=True,
                        secure=_SECURE_COOKIE, samesite="Lax", path="/")
        return resp

    @http.route("/api/admin/panel/logout", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def logout(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _json({"ok": True})
        token = request.httprequest.cookies.get(_COOKIE, "").strip()
        if token:
            sess = request.env["ai.gateway.admin.panel.session"].sudo()
            rec = sess.search([("token_hash", "=", sess._hash(token))], limit=1)
            if rec:
                rec.revoke()
        resp = _json({"ok": True})
        resp.delete_cookie(_COOKIE, path="/")
        return resp

    @http.route("/api/admin/panel/session", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def session(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _json({"ok": True})
        user, err = _require_admin()
        if err:
            return err
        return _json({"ok": True, "user": {"name": user.name, "login": user.login}})

    # ---------------------------------------------------------- AI engine
    @http.route("/api/admin/panel/engine", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def engine_get(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _json({"ok": True})
        user, err = _require_admin()
        if err:
            return err
        return _json(_panel_env().engine_get())

    @http.route("/api/admin/panel/engine", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def engine_set(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _json({"ok": True})
        user, err = _require_admin()
        if err:
            return err
        try:
            body = __import__("json").loads(request.httprequest.data or b"{}")
        except Exception:  # noqa: BLE001
            return _json({"error": "invalid body"}, status=400)
        cfg = _panel_env().engine_set(
            provider=body.get("provider"), api_base=body.get("api_base"),
            chat_model=body.get("chat_model"), embedding_model=body.get("embedding_model"),
            api_key=body.get("api_key") or None)
        if body.get("apply"):
            applied = _panel_env().engine_apply()
            cfg = dict(cfg, apply_result=applied)
        return _json(cfg)

    @http.route("/api/admin/panel/engine/test", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def engine_test(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _json({"ok": True})
        user, err = _require_admin()
        if err:
            return err
        try:
            body = __import__("json").loads(request.httprequest.data or b"{}")
        except Exception:  # noqa: BLE001
            body = {}
        return _json(_panel_env().engine_test(
            api_base=body.get("api_base"), api_key=body.get("api_key") or None,
            chat_model=body.get("chat_model")))

    # ------------------------------------------------------------ modules
    @http.route("/api/admin/panel/modules", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def modules(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _json({"ok": True})
        user, err = _require_admin()
        if err:
            return err
        return _json({"modules": _panel_env().modules_list()})

    @http.route("/api/admin/panel/modules/act", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def modules_act(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _json({"ok": True})
        user, err = _require_admin()
        if err:
            return err
        try:
            body = __import__("json").loads(request.httprequest.data or b"{}")
        except Exception:  # noqa: BLE001
            return _json({"error": "invalid body"}, status=400)
        names = body.get("names") or []
        action = body.get("action") or ""
        if not names or not isinstance(names, list):
            return _json({"error": "names list required"}, status=400)
        out = _panel_env().modules_act(names, action)
        return _json(out, status=200 if "error" not in out else 400)

    # --------------------------------------------------------------- users
    @http.route("/api/admin/panel/users", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def users(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _json({"ok": True})
        user, err = _require_admin()
        if err:
            return err
        return _json({"users": _panel_env().users_list()})

    @http.route("/api/admin/panel/users/password", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def users_password(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _json({"ok": True})
        user, err = _require_admin()
        if err:
            return err
        try:
            body = __import__("json").loads(request.httprequest.data or b"{}")
        except Exception:  # noqa: BLE001
            return _json({"error": "invalid body"}, status=400)
        return _json(_panel_env().user_set_password(
            body.get("login") or "", body.get("password") or ""))

    # -------------------------------------------------------------- health
    @http.route("/api/admin/panel/health", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def health(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _json({"ok": True})
        user, err = _require_admin()
        if err:
            return err
        return _json(_panel_env().health())

    # ---------------------------------------------------------------- logs
    @http.route("/api/admin/panel/logs", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def logs(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return _json({"ok": True})
        user, err = _require_admin()
        if err:
            return err
        return _json({"logs": _panel_env().logs_tail()})
