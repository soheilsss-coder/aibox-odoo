import json

from odoo import http
from odoo.http import request

from odoo.addons.ai_gateway.controllers.gateway import _authenticate, _check_rate_limit, _scoped_user_env


class AiControlPlaneController(http.Controller):
    @http.route("/api/capabilities", type="http", auth="none", csrf=False, methods=["GET"])
    def capabilities(self, **kwargs):
        user, key, blocked = _authenticate()
        if blocked:
            return request.make_json_response({"error": "rate limited"}, status=429)
        if not user or not _check_rate_limit(key):
            return request.make_json_response({"error": "unauthorized"}, status=401)
        env = _scoped_user_env(user)
        caps = env["ai.control.capability.resolver"].effective_capabilities(user)
        return request.make_json_response({
            "capability_count": len(caps),
            "operations": sorted(set(c.operation for c in caps)),
        })

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
        env = _scoped_user_env(user)
        modules = env["ai.control.module"].search([("state", "=", "installed")])
        privileged = user.has_group("base.group_system")
        rows = []
        for m in modules:
            def parse(value, default):
                try:
                    return json.loads(value or json.dumps(default))
                except (TypeError, ValueError):
                    return default
            adapter = env["ai.integration.adapter"].sudo().for_module(m.technical_name) if "ai.integration.adapter" in env else False
            mappings = env["ai.integration.event.mapping"].sudo().search([("module_name", "=", m.technical_name), ("active", "=", True)]) if "ai.integration.event.mapping" in env else []
            rows.append({
                "name": m.name, "technical_name": m.technical_name, "version": m.version,
                "adapter": adapter.label if adapter else None, "adapter_state": adapter.state if adapter else "missing",
                "integration_level": m.integration_level, "certification_state": m.certification_state,
                "models": parse(getattr(m, "model_names_json", "[]"), []) if privileged else [],
                "groups": parse(getattr(m, "group_names_json", "[]"), []) if privileged else [],
                "menus": parse(getattr(m, "menu_names_json", "[]"), []) if privileged else [],
                "views": parse(getattr(m, "view_names_json", "[]"), []) if privileged else [],
                "scope": parse(getattr(m, "scope_json", "{}"), {}) if privileged else {},
                "capabilities": m.capability_count if privileged else 0,
                "discovered_operations": m.discovered_operation_count if privileged else 0,
                "reviewed_operations": m.reviewed_operation_count if privileged else 0,
                "event_mappings": [{"model": x.model_name, "operation": x.operation, "event_type": x.event_type, "source": x.source} for x in mappings] if privileged else [],
                "unavailable_mutations": parse(getattr(m, "unavailable_mutations_json", "[]"), []) if privileged else [],
                "automatic_read": m.automatic_read,
                "automatic_events": m.automatic_events,
                "automatic_audit": m.automatic_audit,
                "last_sync": str(m.last_sync) if m.last_sync else None,
                "error": m.last_error,
            })
        return request.make_json_response({"modules": rows})

    @http.route("/api/control-plane/integrations/sync", type="json", auth="none", csrf=False, methods=["POST"])
    def sync(self, **params):
        user, key, blocked = _authenticate()
        if blocked or not user or not _check_rate_limit(key):
            return {"error": "unauthorized"}
        if not user.has_group("base.group_system"):
            return {"error": "access_denied"}
        env = _scoped_user_env(user)
        env["ai.control.module"].sync_installed_modules()
        return {"status": "ok"}
