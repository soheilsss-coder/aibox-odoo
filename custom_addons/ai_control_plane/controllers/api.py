from odoo import http
from odoo.http import request

from odoo.addons.ai_gateway.controllers.gateway import _authenticate, _check_rate_limit


class AiControlPlaneController(http.Controller):
    @http.route("/api/capabilities", type="http", auth="none", csrf=False, methods=["GET"])
    def capabilities(self, **kwargs):
        user, key, blocked = _authenticate()
        if blocked:
            return request.make_json_response({"error": "rate limited"}, status=429)
        if not user or not _check_rate_limit(key):
            return request.make_json_response({"error": "unauthorized"}, status=401)
        env = request.env(user=user.id)
        caps = env["ai.control.capability.resolver"].effective_capabilities(user)
        return request.make_json_response({"capabilities": caps.mapped(lambda c: c.name)})

    # Namespaced under /api/control-plane to avoid colliding with the
    # semantic_api admin surface that also exposes /api/integrations
    # (which additionally gates on base.group_system). The module
    # discovery contract is owned by this addon, so its route carries
    # the control-plane prefix.
    @http.route("/api/control-plane/integrations", type="http", auth="none", csrf=False, methods=["GET"])
    def integrations(self, **kwargs):
        user, key, blocked = _authenticate()
        if blocked:
            return request.make_json_response({"error": "rate limited"}, status=429)
        if not user or not _check_rate_limit(key):
            return request.make_json_response({"error": "unauthorized"}, status=401)
        env = request.env(user=user.id)
        modules = env["ai.control.module"].search([("state", "=", "installed")])
        return request.make_json_response({"modules": [{
            "name": m.name, "technical_name": m.technical_name, "version": m.version,
            "adapter": m.adapter_key, "models": m.discovered_models,
            "groups": m.discovered_groups, "last_sync": str(m.last_sync) if m.last_sync else None,
            "error": m.last_error,
        } for m in modules]})

    @http.route("/api/control-plane/integrations/sync", type="json", auth="none", csrf=False, methods=["POST"])
    def sync(self, **params):
        user, key, blocked = _authenticate()
        if blocked or not user or not _check_rate_limit(key):
            return {"error": "unauthorized"}
        if not user.has_group("base.group_system"):
            return {"error": "access_denied"}
        env = request.env(user=user.id)
        env["ai.control.module"].sync_installed_modules()
        return {"status": "ok"}
