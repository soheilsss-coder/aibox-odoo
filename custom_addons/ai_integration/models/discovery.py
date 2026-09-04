import hashlib
import json
import logging
import re

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AiIntegrationDiscovery(models.Model):
    """Universal, automatic onboarding for every installed Odoo module.

    Discovery creates a safe read-only operation for each model. It never
    invents a business write, approval, delete, financial, or stock operation;
    those paths require a source-reviewed adapter contract. The same sync runs
    after install/upgrade state changes and is also safe to run from the cron.
    """

    _inherit = "ai.control.module"

    model_names_json = fields.Text(default="[]")
    group_names_json = fields.Text(default="[]")
    menu_names_json = fields.Text(default="[]")
    view_names_json = fields.Text(default="[]")
    scope_json = fields.Text(default="{}")
    capability_names_json = fields.Text(default="[]")
    integration_status = fields.Selection([
        ("ready", "Ready"), ("warning", "Warning"), ("failed", "Failed")
    ], default="ready")

    _SENSITIVE_FIELD_PARTS = (
        "password", "secret", "token", "api_key", "private_key", "ssh_key",
        "access_token", "refresh_token", "client_secret", "database_password",
    )
    _PREFERRED_FIELDS = (
        "display_name", "name", "ref", "code", "state", "stage_id", "active",
        "company_id", "department_id", "user_id", "partner_id", "date",
        "date_start", "date_end", "write_date",
    )

    def _safe_model_names(self, module):
        records = self.env["ir.model"].sudo().search([("model", "!=", False)])
        return sorted({record.model for record in records if module in {
            item.strip() for item in (record.modules or "").split(",") if item.strip()
        }})

    @classmethod
    def _safe_field(cls, name, field):
        lowered = name.lower()
        if any(part in lowered for part in cls._SENSITIVE_FIELD_PARTS):
            return False
        if lowered.endswith("_password") or field.type in {"binary", "html", "one2many", "many2many"}:
            return False
        return True

    def _safe_field_names(self, model_name):
        Model = self.env[model_name]
        safe = [
            name for name, field in Model._fields.items()
            if self._safe_field(name, field)
        ]
        preferred = [name for name in self._PREFERRED_FIELDS if name in safe]
        # Stable, bounded field lists prevent the generic fallback from
        # becoming an arbitrary field/ORM read surface.
        remainder = sorted(set(safe) - set(preferred))[:12]
        return (preferred + remainder)[:20] or ["id"]

    def _data_resource_names(self, module_name, model_name, label_field):
        """Resolve XML-owned menus/views/groups without trusting user input."""
        Data = self.env["ir.model.data"].sudo()
        rows = Data.search([("module", "=", module_name), ("model", "=", model_name)])
        if not rows:
            return []
        Resource = self.env[model_name].sudo()
        values = Resource.browse(rows.mapped("res_id")).exists()
        return sorted({
            str(getattr(value, label_field, False) or getattr(value, "name", False) or value.id)
            for value in values
        })

    def _scope_metadata(self, model_names):
        result = {}
        for model_name in model_names:
            Model = self.env[model_name]
            names = set(Model._fields)
            result[model_name] = {
                "company": "company_id" in names,
                "department": "department_id" in names or "department_ids" in names,
                "user": any(name in names for name in ("user_id", "user_ids", "create_uid", "write_uid")),
                "employee": "employee_id" in names,
                "native_acl": True,
                "record_rules": True,
            }
        return result

    @staticmethod
    def _operation_key(module_name, model_name):
        readable = re.sub(r"[^a-z0-9_]+", "_", "%s_%s" % (module_name, model_name.lower())).strip("_")
        digest = hashlib.sha256((module_name + ":" + model_name).encode()).hexdigest()[:12]
        return "discovered.%s.read_%s" % (readable[:80], digest)

    @staticmethod
    def _capability_key(module_name, model_name):
        digest = hashlib.sha256((module_name + ":" + model_name).encode()).hexdigest()[:16]
        return "discovered.%s.read" % digest

    def _system_admin_group_commands(self):
        group = self.env.ref("ai_business_tools.role_system_admin", raise_if_not_found=False)
        return [(6, 0, [group.id])] if group else []

    def _ensure_discovered_adapter(self, module, label):
        Adapter = self.env["ai.integration.adapter"].sudo()
        adapter = Adapter.for_module(module)
        if adapter:
            return adapter
        return Adapter.create({
            "module_name": module,
            "label": label or module,
            "capability_prefix": "discovered.%s" % module,
            "event_prefix": "module",
            "state": "discovered",
            "notes": "Automatically created fallback. Business mutations require a source-reviewed adapter.",
        })

    def _ensure_discovered_operation(self, module_name, model_name, adapter):
        Cap = self.env["ai.control.capability"].sudo()
        Operation = self.env["ai.integration.operation"].sudo()
        Risk = self.env["ai.gateway.tool.risk"].sudo()
        cap_name = self._capability_key(module_name, model_name)
        capability = Cap.search([("name", "=", cap_name)], limit=1)
        if not capability:
            capability = Cap.create({
                "name": cap_name,
                "module_name": module_name,
                "description": "Automatically discovered read-only capability for %s" % model_name,
                "operation": "read",
                "risk_level": 0,
                "model_name": model_name,
                "source": "discovered",
                # Automatic inventory must not become an employee-wide ORM
                # read grant.  A privileged operator can review the inventory;
                # business users need a source-reviewed adapter instead.
                "group_ids": self._system_admin_group_commands(),
            })
        elif capability.source == "discovered":
            # Upgrade existing databases that were discovered before this
            # restriction was added.
            capability.write({"group_ids": self._system_admin_group_commands()})
        fields_json = json.dumps(self._safe_field_names(model_name), ensure_ascii=False)
        tool_name = self._operation_key(module_name, model_name)
        operation = Operation.search([("tool_name", "=", tool_name)], limit=1)
        values = {
            "module_name": module_name,
            "adapter_id": adapter.id,
            "capability_name": capability.name,
            "operation": "read",
            "risk_level": 0,
            "handler_key": "discovered_model_read",
            "description": "Automatically discovered read summary; no mutation is available.",
            "source": "discovered",
            "coverage": "discovered_read",
            "model_name": model_name,
            "field_names_json": fields_json,
            "active": True,
        }
        if operation:
            operation.write(values)
        else:
            operation = Operation.create(dict(values, tool_name=tool_name))
        risk = Risk.search([("tool_name", "=", tool_name)], limit=1)
        risk_values = {
            "tool_name": tool_name,
            "capability_name": cap_name,
            "risk_level": 0,
            "description": "Read-only discovered module summary",
        }
        if risk:
            risk.write(risk_values)
        else:
            Risk.create(risk_values)
        return capability, operation

    def _ensure_event_mappings(self, module_name, model_name, adapter):
        Mapping = self.env["ai.integration.event.mapping"].sudo()
        for operation in ("insert", "update", "delete"):
            mapping = Mapping.search([
                ("module_name", "=", module_name),
                ("model_name", "=", model_name),
                ("operation", "=", operation),
            ], limit=1)
            values = {
                "event_type": "module.%s.%s" % (operation, hashlib.sha256(model_name.encode()).hexdigest()[:10]),
                "adapter_id": adapter.id,
                "source": "discovered",
                "active": True,
                "description": "Automatic lifecycle event mapping; payload is metadata-only.",
            }
            if mapping:
                # Discovery may refresh its own fallback, but it must never
                # overwrite a source-reviewed event mapping supplied by an
                # adapter module.
                if mapping.source != "reviewed":
                    mapping.write(values)
            else:
                Mapping.create(dict(values, module_name=module_name, model_name=model_name, operation=operation))

    @api.model
    def sync_installed_modules(self):
        result = super().sync_installed_modules()
        Module = self.env["ir.module.module"].sudo()
        installed = Module.search([("state", "=", "installed")])
        Adapter = self.env["ai.integration.adapter"].sudo()
        Cap = self.env["ai.control.capability"].sudo()
        trigger_result = {"triggers_created": 0}
        trigger_error = False
        onboarding_error = False
        # A removed module must not leave an executable discovered operation
        # behind. Source-reviewed contracts remain managed explicitly by their
        # adapter owner and are never auto-mutated here.
        installed_names = set(installed.mapped("name"))
        self.env["ai.integration.operation"].sudo().search([
            ("source", "=", "discovered"), ("module_name", "not in", list(installed_names)),
        ]).write({"active": False})
        self.env["ai.integration.adapter"].sudo().search([
            ("state", "=", "discovered"), ("module_name", "not in", list(installed_names)),
        ]).write({"active": False})
        self.env["ai.integration.event.mapping"].sudo().search([
            ("source", "=", "discovered"), ("module_name", "not in", list(installed_names)),
        ]).write({"active": False})
        if "ai.integration.change.trigger" in self.env:
            try:
                trigger_result = self.env["ai.integration.change.trigger"].ensure_triggers()
            except Exception as exc:  # noqa: BLE001
                # Read onboarding remains available, but event/audit is not
                # claimed as active if the database cannot install triggers.
                trigger_error = str(exc)
                _logger.exception("Universal module event trigger installation failed")
        for mod in installed:
            rec = self.sudo().search([("technical_name", "=", mod.name)], limit=1)
            if not rec:
                continue
            models = [name for name in self._safe_model_names(mod.name) if name in self.env]
            groups = self.env["res.groups"].sudo().search([("category_id", "!=", False)])
            group_names = sorted({
                group.name for group in groups
                if mod.name in (getattr(group, "module", "") or "").split(",")
            })
            group_names = sorted(set(group_names) | set(self._data_resource_names(mod.name, "res.groups", "name")))
            menu_names = self._data_resource_names(mod.name, "ir.ui.menu", "complete_name")
            view_names = self._data_resource_names(mod.name, "ir.ui.view", "name")
            scope = self._scope_metadata(models)
            adapter = Adapter.for_module(mod.name)
            if not adapter:
                adapter = self._ensure_discovered_adapter(mod.name, mod.shortdesc or mod.name)
            cap_names = set(Cap.search([
                ("module_name", "=", mod.name), ("active", "=", True)
            ]).mapped("name"))
            discovered_operations = 0
            for model_name in models:
                # Keep the old model.read capability for the safe generic read
                # tool, while routing the bounded operation through its own
                # module-scoped capability and reviewed execution gate.
                generic_cap = "%s.read" % model_name
                try:
                    with self.env.cr.savepoint():
                        generic = Cap.search([("name", "=", generic_cap)], limit=1)
                        if not generic:
                            Cap.create({
                                "name": generic_cap,
                                "module_name": mod.name,
                                "description": "Discovered read-only capability for %s" % model_name,
                                "operation": "read",
                                "risk_level": 0,
                                "model_name": model_name,
                                "source": "discovered",
                                "group_ids": self._system_admin_group_commands(),
                            })
                        elif generic.source == "discovered":
                            generic.write({"group_ids": self._system_admin_group_commands()})
                except Exception as exc:  # noqa: BLE001
                    _logger.exception("Could not create discovered capability for %s", model_name)
                    onboarding_error = onboarding_error or str(exc)
                    continue
                cap_names.add(generic_cap)
                try:
                    with self.env.cr.savepoint():
                        capability, operation = self._ensure_discovered_operation(mod.name, model_name, adapter)
                        self._ensure_event_mappings(mod.name, model_name, adapter)
                        cap_names.add(capability.name)
                        discovered_operations += int(operation.source == "discovered")
                except Exception as exc:  # noqa: BLE001
                    _logger.exception("Could not create discovered operation for %s", model_name)
                    onboarding_error = onboarding_error or str(exc)
            all_ops = self.env["ai.integration.operation"].sudo().search([
                ("module_name", "=", mod.name), ("active", "=", True)
            ])
            reviewed_ops = all_ops.filtered(lambda op: op.coverage == "reviewed_operational" and op.source == "reviewed")
            operational = bool(adapter.state == "ready" and reviewed_ops)
            mutation_kinds = ("create", "update", "delete", "approve", "execute")
            unavailable = [{
                "operation": kind,
                "status": "adapter-required",
                "reason": "Only source-reviewed handlers may perform this side effect.",
            } for kind in mutation_kinds if not any(
                op.operation == kind for op in reviewed_ops
            )]
            rec.write({
                "discovered_models": len(models),
                "discovered_groups": len(group_names),
                "discovered_menus": len(menu_names),
                "discovered_views": len(view_names),
                "capability_count": len(cap_names),
                "model_names_json": json.dumps(models),
                "group_names_json": json.dumps(group_names),
                "menu_names_json": json.dumps(menu_names),
                "view_names_json": json.dumps(view_names),
                "scope_json": json.dumps(scope, ensure_ascii=False),
                "capability_names_json": json.dumps(sorted(cap_names)),
                "integration_status": "ready" if models and not (trigger_error or onboarding_error) else "warning",
                "integration_level": "reviewed_operational" if operational else "discovered_read_only",
                "certification_state": (
                    "baseline_ready" if models and operational and not (trigger_error or onboarding_error)
                    else "adapter_required" if models
                    else "discovered"
                ),
                "automatic_read": bool(models and not onboarding_error),
                "automatic_events": not bool(trigger_error),
                "automatic_audit": not bool(trigger_error),
                "discovered_operation_count": len(all_ops.filtered(lambda op: op.source == "discovered")),
                "reviewed_operation_count": len(all_ops.filtered(lambda op: op.source == "reviewed")),
                "unavailable_mutations_json": json.dumps(unavailable),
                "last_error": trigger_error or onboarding_error or False,
            })
            if "ai.integration.test.runner" in self.env:
                try:
                    test = self.env["ai.integration.test.runner"].run_for_module(mod.name)
                    if test["status"] != "pass":
                        rec.write({"integration_status": "warning"})
                except Exception as exc:  # noqa: BLE001
                    rec.write({"integration_status": "warning", "last_error": str(exc)})
        base_result = result if isinstance(result, dict) else {}
        return dict(base_result, universal_onboarding=True, **trigger_result)
