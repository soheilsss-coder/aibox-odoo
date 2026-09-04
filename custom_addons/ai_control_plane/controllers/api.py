import json
import logging


_logger = logging.getLogger(__name__)

from odoo import fields, http
from odoo.http import request

from odoo.addons.ai_gateway.controllers.gateway import (
    _authenticate, _check_rate_limit, _scoped_user_env, _json_response,
    _cors_preflight_response, _is_privileged, _audit,
)


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

    @staticmethod
    def _auth_response():
        """Return the authenticated, current-device environment.

        The product uses the same session/API-key contract as the rest of the
        gateway. Module installation is a privileged operation, while the
        navigation endpoint below is deliberately available to ordinary users
        and is filtered by their native menu groups.
        """
        user, key, blocked = _authenticate()
        if blocked:
            return None, _json_response({"error": "rate limited"}, status=429)
        if not user or not _check_rate_limit(key):
            return None, _json_response({"error": "unauthorized"}, status=401)
        return _scoped_user_env(user), None

    @staticmethod
    def _parse_registry(value, default):
        try:
            parsed = json.loads(value or json.dumps(default))
            return parsed if isinstance(parsed, type(default)) else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _dependencies(env, module):
        dependencies = getattr(module, "dependencies_id", False)
        if not dependencies:
            return []
        names = sorted(set(dependencies.mapped("name")))
        records = env["ir.module.module"].sudo().search([("name", "in", names)])
        labels = {record.name: record.shortdesc or record.name for record in records}
        # Technical dependency identifiers never need to reach the customer
        # UI. Keep a clear fallback for a dependency whose manifest record is
        # temporarily unavailable during an install/upgrade.
        return [labels.get(name, "پیش‌نیاز فنی") for name in names]

    def _catalog_row(self, env, module):
        registry = env["ai.control.module"].sudo().search([
            ("technical_name", "=", module.name),
        ], limit=1)
        latest_request = env["ai.module.install.request"].sudo().search([
            ("module_id", "=", module.id), ("company_id", "=", env.company.id),
        ], order="requested_at desc,id desc", limit=1)
        return {
            # The numeric id is an opaque action key for the admin panel. The
            # technical module name never needs to be shown to a customer.
            "id": module.id,
            "label": module.shortdesc or module.name,
            "version": module.installed_version or module.latest_version or "",
            "category": module.category_id.name if getattr(module, "category_id", False) else "",
            "application": bool(getattr(module, "application", False)),
            "state": module.state,
            "dependencies": self._dependencies(env, module),
            "menu_count": registry.discovered_menus if registry else 0,
            "integration_level": registry.integration_level if registry else "discovered_read_only",
            "certification_state": registry.certification_state if registry else "discovered",
            "automatic_read": bool(registry.automatic_read) if registry else False,
            "automatic_events": bool(registry.automatic_events) if registry else False,
            "automatic_audit": bool(registry.automatic_audit) if registry else False,
            "capability_count": registry.capability_count if registry else 0,
            "reviewed_operation_count": registry.reviewed_operation_count if registry else 0,
            "last_error": registry.last_error if registry else False,
            "request": ({
                "key": latest_request.request_key,
                "state": latest_request.state,
                "error": latest_request.error or False,
                "requested_at": str(latest_request.requested_at) if latest_request.requested_at else None,
                "completed_at": str(latest_request.completed_at) if latest_request.completed_at else None,
            } if latest_request else None),
        }

    @http.route("/api/admin/modules", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def admin_modules(self, **kwargs):
        """List installable business applications for this appliance.

        Installed technical dependencies are intentionally not presented as
        customer-selectable apps. Only modules marked as customer-facing
        applications by their manifest are offered in this catalog.
        """
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = self._auth_response()
        if err:
            return err
        if not _is_privileged(env, env.user):
            return _json_response({"error": "access denied"}, status=403)
        modules = env["ir.module.module"].sudo().search([
            ("state", "in", ["installed", "uninstalled", "uninstallable"]),
        ], order="application desc, shortdesc, name")
        rows = [self._catalog_row(env, module) for module in modules if bool(
            getattr(module, "application", False)
        )]
        return _json_response({"modules": rows})

    @http.route("/api/admin/modules/install", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def admin_module_install(self, **kwargs):
        """Install one official application on this customer appliance.

        This calls the platform's own immediate installer, including its
        dependency and registry lifecycle. It is intentionally one module per
        request: the UI can show exactly which selection failed and a partial
        batch can never be mistaken for a successful all-or-nothing install.
        Automatic discovery is scheduled by the ir.module.module post-commit
        hook and its restart-safe cron; this request never asks an admin to run
        a second manual sync command.
        """
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = self._auth_response()
        if err:
            return err
        if not _is_privileged(env, env.user):
            return _json_response({"error": "access denied"}, status=403)
        try:
            payload = json.loads(request.httprequest.data or b"{}")
        except (TypeError, ValueError):
            return _json_response({"error": "invalid JSON body"}, status=400)
        if not isinstance(payload, dict):
            return _json_response({"error": "JSON body must be an object"}, status=400)
        try:
            module_id = int(payload.get("module_id"))
        except (TypeError, ValueError):
            return _json_response({"error": "module_id is required"}, status=400)
        module = env["ir.module.module"].sudo().browse(module_id).exists()
        if not module:
            return _json_response({"error": "module not found"}, status=404)
        module = module[0]
        if not bool(getattr(module, "application", False)):
            return _json_response({"error": "only selectable business applications may be installed"}, status=403)
        if module.state == "installed":
            # Idempotent checkbox behavior: a retry after a network timeout
            # never attempts to install an already installed module again.
            try:
                env["ai.control.module"].sync_installed_modules()
            except Exception:  # noqa: BLE001
                _logger.exception("Could not refresh module registry for %s", module.name)
            return _json_response({"status": "installed", "module": self._catalog_row(env, module)})
        active_request = env["ai.module.install.request"].sudo().search([
            ("module_id", "=", module.id), ("company_id", "=", env.company.id),
            ("state", "=", "installing"),
        ], limit=1)
        if active_request:
            return _json_response({"error": "module installation is already in progress"}, status=409)
        if module.state in ("to install", "to upgrade", "to remove"):
            return _json_response({"error": "module installation is already in progress"}, status=409)
        if module.state == "uninstallable":
            return _json_response({"error": "module is not installable on this appliance"}, status=409)

        Request = env["ai.module.install.request"].sudo()
        install_request = Request.create({
            "module_id": module.id,
            "module_name": module.name,
            "module_label": module.shortdesc or module.name,
            "company_id": env.company.id,
            "requested_by_id": env.user.id,
            "state": "installing",
        })
        _audit(env, env.user.id, "control_plane", "admin.module_install.requested", {
            "module_id": module.id, "module_label": module.shortdesc or module.name,
            "request_key": install_request.request_key,
        }, success=True)
        try:
            # This is the official module lifecycle entrypoint. Do not shell
            # out from a web request and do not expose arbitrary command/ORM
            # arguments to the browser.
            module.button_immediate_install()
            install_request.sudo().write({
                "state": "installed",
                "completed_at": fields.Datetime.now(),
                "error": False,
            })
            _audit(env, env.user.id, "control_plane", "admin.module_install.completed", {
                "module_id": module.id, "module_label": module.shortdesc or module.name,
                "request_key": install_request.request_key,
            }, success=True)
            return _json_response({
                "status": "installed",
                "sync": "automatic_pending",
                "module": self._catalog_row(env, module),
            })
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Module installation failed for %s", module.name)
            try:
                install_request.sudo().write({
                    "state": "failed",
                    "completed_at": fields.Datetime.now(),
                    # Never return the raw exception to the customer browser;
                    # it may contain filesystem paths or dependency details.
                    "error": "installation failed; inspect the appliance audit log",
                })
                _audit(env, env.user.id, "control_plane", "admin.module_install.failed", {
                    "module_id": module.id, "module_label": module.shortdesc or module.name,
                }, success=False, error_message=str(exc))
            except Exception:  # noqa: BLE001
                _logger.exception("Could not persist failed module request for %s", module.name)
            return _json_response({"error": "module installation failed; inspect the admin audit log"}, status=409)

    @http.route("/api/modules/navigation", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def module_navigation(self, **kwargs):
        """Return installed application menus visible to the current user.

        The product shell consumes this as navigation data. Menu membership
        is filtered using the same native groups as the business client; no
        technical model names, routes or arbitrary ORM actions are exposed.
        """
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = self._auth_response()
        if err:
            return err
        installed = env["ir.module.module"].sudo().search([
            ("state", "=", "installed"), ("application", "=", True),
        ], order="shortdesc,name")
        registry_model = env["ai.control.module"].sudo()
        Data = env["ir.model.data"].sudo()
        user_group_ids = set(env.user.groups_id.ids)
        result = []
        for module in installed:
            registry = registry_model.search([("technical_name", "=", module.name)], limit=1)
            if not registry:
                continue
            xml_menus = Data.search([
                ("module", "=", module.name), ("model", "=", "ir.ui.menu"),
            ])
            menus = env["ir.ui.menu"].sudo().browse(xml_menus.mapped("res_id")).exists()
            visible = []
            for menu in menus:
                groups = set(menu.groups_id.ids)
                if groups and not groups.intersection(user_group_ids):
                    continue
                visible.append({
                    "id": menu.id,
                    "label": menu.name,
                    "parent_id": menu.parent_id.id if menu.parent_id else None,
                    "has_action": bool(menu.action),
                })
            visible.sort(key=lambda row: (row["parent_id"] or 0, row["label"]))
            if not visible:
                continue
            result.append({
                "id": registry.id,
                "label": module.shortdesc or module.name,
                "menus": visible,
                "integration_level": registry.integration_level,
                "certification_state": registry.certification_state,
                "capability_count": registry.capability_count,
                "reviewed_operation_count": registry.reviewed_operation_count,
            })
        return _json_response({"modules": result})

    @staticmethod
    def _visible_menu(env, menu):
        groups = set(menu.groups_id.ids)
        return not groups or bool(groups.intersection(set(env.user.groups_id.ids)))

    @staticmethod
    def _safe_action_fields(Model):
        sensitive = {
            "password", "secret", "token", "api_key", "private_key", "iban",
            "bank_account", "access_token", "refresh_token", "client_secret",
        }
        preferred = ("display_name", "name", "ref", "code", "state", "active", "date", "write_date")
        candidates = []
        for name, field in Model._fields.items():
            lowered = name.lower()
            if any(part in lowered for part in sensitive):
                continue
            if field.type in {"binary", "html", "one2many", "many2many", "many2one", "reference"}:
                continue
            if not getattr(field, "store", True):
                continue
            candidates.append(name)
        selected = [name for name in preferred if name in candidates]
        selected.extend(name for name in sorted(set(candidates) - set(selected))[:8])
        return selected[:10]

    @http.route("/api/modules/menus/<int:menu_id>", type="http", auth="none", csrf=False,
                methods=["GET", "OPTIONS"])
    def module_menu(self, menu_id, **kwargs):
        """Read the real records behind one visible application menu.

        The menu record, not a browser-supplied model/domain, determines the
        action and model. This gives the product shell a useful generic list
        for newly installed applications while preserving native ACLs and
        record rules. Mutations stay on reviewed adapters.
        """
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = self._auth_response()
        if err:
            return err
        menu = env["ir.ui.menu"].sudo().browse(menu_id).exists()
        if not menu:
            return _json_response({"error": "menu not found"}, status=404)
        menu = menu[0]
        if not self._visible_menu(env, menu):
            return _json_response({"error": "access denied"}, status=403)
        installed_apps = set(env["ir.module.module"].sudo().search([
            ("state", "=", "installed"), ("application", "=", True),
        ]).mapped("name"))
        owned = env["ir.model.data"].sudo().search([
            ("model", "=", "ir.ui.menu"), ("res_id", "=", menu.id),
            ("module", "in", list(installed_apps)),
        ], limit=1)
        if not owned:
            return _json_response({"error": "menu is not an active application menu"}, status=404)
        action = menu.action
        if not action or action._name != "ir.actions.act_window" or not action.res_model:
            return _json_response({
                "title": menu.name, "columns": [], "rows": [],
                "message": "این بخش منوی عملیاتی مستقیمی برای نمایش جدولی ندارد.",
            })
        model_name = action.res_model
        if model_name not in env:
            return _json_response({"error": "the selected application is not ready"}, status=409)
        Model = env[model_name]
        safe_fields = self._safe_action_fields(Model)
        if not safe_fields:
            return _json_response({
                "title": menu.name, "columns": [], "rows": [],
                "message": "برای این بخش نمای خواندنی امنی آماده نیست.",
            })
        try:
            limit = min(max(int(kwargs.get("limit", 50)), 1), 100)
        except (TypeError, ValueError):
            limit = 50
        try:
            records = Model.search([], order="id desc", limit=limit)
            raw = records.read(safe_fields)
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Could not read application menu %s", menu.id)
            return _json_response({"error": "records could not be loaded"}, status=403)
        columns = [{"key": name, "label": Model._fields[name].string or name} for name in safe_fields]
        rows = [{"id": row.get("id"), "values": [row.get(name) for name in safe_fields]} for row in raw]
        return _json_response({
            "title": menu.name,
            "columns": columns,
            "rows": rows,
            "count": len(rows),
            "limit": limit,
            "read_only": True,
            "message": "نمایش خواندنی بر اساس دسترسی حساب کاربری شما.",
        })
