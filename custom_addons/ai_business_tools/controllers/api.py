import json

from odoo import http
from odoo.http import request

from odoo.addons.ai_gateway.controllers.gateway import (
    _authenticate,
    _check_rate_limit,
    _scoped_user_env,
    _cors_preflight_response,
    _json_response,
)


class AiBusinessToolsPublicApi(http.Controller):
    """Management surface for the Scheduled AI Commands (roadmap /
    phase 2.7). Exposes the same API-key authentication and rate-limit
    rules as the gateway - never arbitrary ORM access."""

    @http.route("/api/schedules", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def list_schedules(self, **kwargs):
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
        if "ai.schedule.rule" not in env:
            return _json_response({"error": "ai_business_tools is not installed"}, status=501)

        rules = env["ai.schedule.rule"].sudo().search([])
        visible = rules.filtered(
            lambda r: r.user_id.id == user.id or user.has_group("base.group_system"))
        return _json_response({"schedules": [
            {"id": r.id, "name": r.name, "repeat": "%s %s" % (r.interval_number, r.interval_type),
             "state": r.state, "last_run": r.last_run_datetime,
             "active": r.active, "owner": r.user_id.name}
            for r in visible
        ]})

    @http.route("/api/schedules/toggle", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def toggle_schedule(self, **params):
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
        if "ai.schedule.rule" not in env:
            return _json_response({"error": "ai_business_tools is not installed"}, status=501)

        try:
            body = json.loads(request.httprequest.data or "{}")
        except Exception:
            body = {}
        rule_id = body.get("id")
        active = bool(body.get("active"))
        if not rule_id or not str(rule_id).isdigit():
            return _json_response({"error": "'id' is required"}, status=400)
        rule = env["ai.schedule.rule"].sudo().browse(int(rule_id)).exists()
        if not rule:
            return _json_response({"error": "schedule not found"}, status=404)
        if rule.user_id.id != user.id and not user.has_group("base.group_system"):
            return _json_response({"error": "access denied: you are not the owner of this schedule"}, status=403)
        rule.write({"active": active})
        return _json_response({"status": "ok", "id": rule.id, "active": rule.active})