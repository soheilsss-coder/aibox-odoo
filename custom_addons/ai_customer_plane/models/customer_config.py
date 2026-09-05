import hashlib
import json

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AiConfigurationProfile(models.Model):
    _name = "ai.customer.configuration.profile"
    _description = "Customer Control Plane Configuration Profile"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    active = fields.Boolean(default=True)
    role_policy_json = fields.Text(default="{}")
    capability_policy_json = fields.Text(default="{}")
    approval_matrix_json = fields.Text(default="{}")
    document_policy_json = fields.Text(default="{}")
    agent_config_json = fields.Text(default="{}")
    tool_config_json = fields.Text(default="{}")
    workflow_config_json = fields.Text(default="{}")
    feature_config_json = fields.Text(default="{}")
    compiled_config_json = fields.Text(default="{}", readonly=True, copy=False)
    compiled_hash = fields.Char(readonly=True, copy=False, index=True)
    compiled_at = fields.Datetime(readonly=True, copy=False)
    activated_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    activated_at = fields.Datetime(readonly=True, copy=False)
    previous_profile_id = fields.Many2one(
        "ai.customer.configuration.profile", readonly=True, copy=False, ondelete="set null",
    )
    deployment_result_json = fields.Text(default="{}", readonly=True, copy=False)
    version = fields.Integer(default=1)
    state = fields.Selection([("draft", "Draft"), ("active", "Active"), ("archived", "Archived")],
                             default="draft", required=True)

    _CONFIG_FIELDS = {
        "role_policy_json", "capability_policy_json", "approval_matrix_json",
        "document_policy_json", "agent_config_json", "tool_config_json",
        "workflow_config_json", "feature_config_json",
    }

    _sql_constraints = [
        ("name_company_unique", "unique(name,company_id)", "Profile name must be unique per company.")
    ]

    def _record_history(self, reason=""):
        History = self.env["ai.customer.configuration.profile.history"]
        for profile in self:
            History.create_snapshot(profile, reason=reason)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._record_history(reason="created")
        return records

    def clone(self, name):
        self.ensure_one()
        name = (name or "").strip()
        if not name:
            raise ValidationError("A cloned profile requires a name.")
        values = {
            "name": name,
            "company_id": self.company_id.id,
            "active": True,
            "state": "draft",
        }
        for field_name in self._CONFIG_FIELDS:
            values[field_name] = getattr(self, field_name) or "{}"
        return self.create(values)

    def write(self, vals):
        config_changed = bool(self._CONFIG_FIELDS.intersection(vals))
        name_changed = "name" in vals
        state_changed = "state" in vals or "active" in vals
        if config_changed:
            vals = dict(vals)
            vals.update({
                "version": max(self.mapped("version") or [1]) + 1,
                "state": "draft",
                "compiled_config_json": "{}",
                "compiled_hash": False,
                "compiled_at": False,
                "activated_by_id": False,
                "activated_at": False,
                "previous_profile_id": False,
                "deployment_result_json": "{}",
            })
        result = super().write(vals)
        if config_changed or name_changed or state_changed:
            reason = "configuration changed" if config_changed else "name changed" if name_changed else "state changed"
            self._record_history(reason=reason)
        return result

    @api.model
    def active_for_company(self, company=None):
        company = company or self.env.company
        return self.sudo().search([
            ("company_id", "=", company.id), ("state", "=", "active"),
            ("active", "=", True),
        ], order="id desc", limit=1)

    def runtime_config(self):
        self.ensure_one()
        if not self.compiled_hash:
            return {}
        try:
            value = json.loads(self.compiled_config_json or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @api.model
    def _parse_section(self, raw, label):
        try:
            value = json.loads(raw or "{}")
        except (TypeError, ValueError) as exc:
            raise ValidationError("%s must contain valid JSON." % label) from exc
        if not isinstance(value, dict):
            raise ValidationError("%s must be a JSON object." % label)
        return value

    def _apply_role_policy(self, policy):
        """Apply profile-owned role rules to the native role-policy model.

        The profile remains the source of truth for rules it owns. Existing
        manually managed policies are not touched, and switching profiles
        deactivates only rules owned by a previous profile for this company.
        """
        rules = policy.get("rules", []) if isinstance(policy, dict) else []
        if rules and not isinstance(rules, list):
            raise ValidationError("role_policy.rules must be a list.")
        if "ai.customer.role.policy" not in self.env:
            if rules:
                raise ValidationError("The role policy model is not available.")
            return 0
        Policy = self.env["ai.customer.role.policy"].sudo()
        Policy.search([
            ("company_id", "=", self.company_id.id),
            ("profile_id", "!=", self.id),
            ("profile_id", "!=", False),
        ]).write({"active": False})
        written = 0
        active_keys = set()
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                raise ValidationError("role_policy.rules[%s] must be an object." % index)
            xmlid = str(
                rule.get("role_group_xmlid") or rule.get("role_xmlid") or rule.get("role") or ""
            ).strip()
            if not xmlid:
                raise ValidationError("role_policy.rules[%s] requires a product role XML ID." % index)
            role = self.env.ref(xmlid, raise_if_not_found=False)
            if not role or role._name != "res.groups":
                raise ValidationError("Unknown role XML ID: %s" % xmlid)
            external_ids = set(role.get_external_id().values())
            if not any(value.startswith("ai_business_tools.role_") for value in external_ids):
                raise ValidationError("Only product-defined roles may be used in a profile.")
            key = str(rule.get("key") or "%s:%s" % (self.id, index)).strip()[:128]
            active_keys.add(key)
            values = {
                "name": str(rule.get("name") or "%s / %s" % (self.name, key))[:200],
                "company_id": self.company_id.id,
                "profile_id": self.id,
                "profile_rule_key": key,
                "department": str(rule.get("department") or "").strip(),
                "position": str(rule.get("position") or "").strip(),
                "job_level": str(rule.get("job_level") or "").strip(),
                "manager_required": bool(rule.get("manager_required", False)),
                "location": str(rule.get("location") or "").strip(),
                "employment_type": str(rule.get("employment_type") or "").strip(),
                "role_group_id": role.id,
                "priority": int(rule.get("priority", 10) or 10),
                "active": True,
            }
            existing = Policy.search([
                ("company_id", "=", self.company_id.id),
                ("profile_id", "=", self.id),
                ("profile_rule_key", "=", key),
            ], limit=1)
            if existing:
                existing.write(values)
            else:
                Policy.create(values)
            written += 1
        stale = Policy.search([
            ("company_id", "=", self.company_id.id), ("profile_id", "=", self.id),
            ("profile_rule_key", "not in", list(active_keys) or ["__none__"]),
        ])
        stale.write({"active": False})
        return written

    def apply_runtime(self):
        """Apply profile-owned settings through existing authorization models."""
        self.ensure_one()
        runtime = self.runtime_config()
        sections = runtime.get("sections", {})
        role_policy = sections.get("role_policy", {})
        role_rules = self._apply_role_policy(role_policy)
        applied = [
            "capability_policy", "approval_matrix", "document_policy", "agent_config",
            "tool_config", "workflow_config", "feature_config",
        ]
        if role_rules or "rules" in role_policy:
            applied.append("role_policy")
        return {"applied_sections": applied, "role_rule_count": role_rules}

    def export_snapshot(self):
        self.ensure_one()
        sections = {}
        for public_name, field_name in (
            ("role_policy", "role_policy_json"),
            ("capability_policy", "capability_policy_json"),
            ("approval_matrix", "approval_matrix_json"),
            ("document_policy", "document_policy_json"),
            ("agent_config", "agent_config_json"),
            ("tool_config", "tool_config_json"),
            ("workflow_config", "workflow_config_json"),
            ("feature_config", "feature_config_json"),
        ):
            sections[public_name] = self._parse_section(getattr(self, field_name), field_name)
        return {
            "schema_version": 1,
            "name": self.name,
            "company_id": self.company_id.id,
            "source_profile_id": self.id,
            "source_version": self.version,
            "state": self.state,
            "sections": sections,
            "compiled_hash": self.compiled_hash or "",
        }

    @api.model
    def create_from_snapshot(self, snapshot, name=None, company=None):
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
            raise ValidationError("Unsupported profile snapshot schema.")
        sections = snapshot.get("sections")
        if not isinstance(sections, dict):
            raise ValidationError("Profile snapshot sections are required.")
        values = {
            "name": str(name or snapshot.get("name") or "Imported profile").strip(),
            "company_id": (company or self.env.company).id,
            "state": "draft",
        }
        if not values["name"] or len(values["name"]) > 200:
            raise ValidationError("Imported profile name is invalid.")
        for public_name, field_name in (
            ("role_policy", "role_policy_json"),
            ("capability_policy", "capability_policy_json"),
            ("approval_matrix", "approval_matrix_json"),
            ("document_policy", "document_policy_json"),
            ("agent_config", "agent_config_json"),
            ("tool_config", "tool_config_json"),
            ("workflow_config", "workflow_config_json"),
            ("feature_config", "feature_config_json"),
        ):
            value = sections.get(public_name, sections.get(field_name, {}))
            if not isinstance(value, dict):
                raise ValidationError("Imported %s must be an object." % public_name)
            values[field_name] = json.dumps(value, sort_keys=True, ensure_ascii=False)
        return self.create(values)

    def rollback_from_history(self, history, name=None):
        self.ensure_one()
        if not history or history.company_id != self.company_id:
            raise ValidationError("History snapshot does not belong to this company.")
        try:
            snapshot = json.loads(history.snapshot_json or "{}")
        except (TypeError, ValueError) as exc:
            raise ValidationError("History snapshot is invalid.") from exc
        return self.create_from_snapshot(snapshot, name=name or "%s rollback v%s" % (self.name, history.profile_version), company=self.company_id)

    def compile_runtime(self):
        """Compile customer JSON into a validated, immutable runtime snapshot.

        A profile is not considered deployable merely because its JSON parses.
        Explicit tool names are checked against the central registry and their
        capability/risk contract before the snapshot is stored.
        """
        self.ensure_one()
        sections = {
            "role_policy": self._parse_section(self.role_policy_json, "role_policy_json"),
            "capability_policy": self._parse_section(self.capability_policy_json, "capability_policy_json"),
            "approval_matrix": self._parse_section(self.approval_matrix_json, "approval_matrix_json"),
            "document_policy": self._parse_section(self.document_policy_json, "document_policy_json"),
            "agent": self._parse_section(self.agent_config_json, "agent_config_json"),
            "tools": self._parse_section(self.tool_config_json, "tool_config_json"),
            "workflow": self._parse_section(self.workflow_config_json, "workflow_config_json"),
            "features": self._parse_section(self.feature_config_json, "feature_config_json"),
        }
        configured_tools = sections["tools"].get("allowed_tools", sections["tools"].get("tools", []))
        if configured_tools and not isinstance(configured_tools, list):
            raise ValidationError("tool_config_json.allowed_tools must be a list.")
        document_policy = sections["document_policy"]
        allowed_levels = document_policy.get("allowed_access_levels", [])
        if allowed_levels and (
            not isinstance(allowed_levels, list)
            or any(str(item) not in ("company", "group", "department", "personal") for item in allowed_levels)
        ):
            raise ValidationError("document_policy.allowed_access_levels contains an invalid level.")
        default_level = document_policy.get("default_access_level")
        if default_level and default_level not in {str(item) for item in allowed_levels or [default_level]}:
            raise ValidationError("document_policy.default_access_level is not allowed.")
        approval_policy = sections["approval_matrix"]
        for key in ("force_approval_tools", "approval_required_tools"):
            value = approval_policy.get(key, [])
            if value and not isinstance(value, list):
                raise ValidationError("approval_matrix.%s must be a list." % key)
        for key in ("risk_threshold", "minimum_risk"):
            if key in approval_policy:
                try:
                    if int(approval_policy[key]) < 0 or int(approval_policy[key]) > 5:
                        raise ValueError
                except (TypeError, ValueError):
                    raise ValidationError("approval_matrix.%s must be an integer from 0 to 5." % key)
        feature_policy = sections["features"]
        for key in ("enabled_features", "disabled_features"):
            value = feature_policy.get(key, [])
            if value and not isinstance(value, list):
                raise ValidationError("feature_config.%s must be a list." % key)
        capability_policy = sections["capability_policy"]
        configured_capabilities = []
        for key in ("allowed_capabilities", "denied_capabilities", "allow", "deny"):
            value = capability_policy.get(key, [])
            if value and not isinstance(value, list):
                raise ValidationError("capability_policy.%s must be a list." % key)
            configured_capabilities.extend(value or [])
        if configured_capabilities and "ai.control.capability" not in self.env:
            raise ValidationError("The capability registry is not available.")
        if configured_capabilities:
            known = set(self.env["ai.control.capability"].sudo().search([
                ("name", "in", [str(item) for item in configured_capabilities]),
            ]).mapped("name"))
            unknown = sorted({str(item) for item in configured_capabilities} - known)
            if unknown:
                raise ValidationError("Capability contract is incomplete: %s" % ", ".join(unknown))
        contracts = []
        if configured_tools:
            if "ai.integration.unified.registry" not in self.env:
                raise ValidationError("The unified integration registry is not available.")
            registry = self.env["ai.integration.unified.registry"].sudo()
            for tool_name in sorted(set(str(item) for item in configured_tools)):
                try:
                    operation, risk, capability = registry.execution_contract(tool_name)
                except Exception as exc:  # noqa: BLE001
                    raise ValidationError("Tool contract is incomplete: %s" % tool_name) from exc
                contracts.append({
                    "tool": operation.tool_name,
                    "capability": capability.name,
                    "risk_level": int(risk.risk_level or 0),
                    "operation": operation.operation,
                    "module": operation.module_name,
                    "contract_version": operation.contract_version,
                })
        snapshot = {
            "profile_id": self.id,
            "company_id": self.company_id.id,
            "source_version": self.version,
            "sections": sections,
            "tool_contracts": contracts,
        }
        serialized = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self.write({
            "compiled_config_json": serialized,
            "compiled_hash": hashlib.sha256(serialized.encode()).hexdigest(),
            "compiled_at": fields.Datetime.now(),
        })
        self._record_history(reason="compiled")
        return snapshot

    def activate(self):
        for rec in self:
            previous = self.search([
                ("company_id", "=", rec.company_id.id),
                ("id", "!=", rec.id),
                ("state", "=", "active"),
            ], order="id desc", limit=1)
            rec.compile_runtime()
            applied = rec.apply_runtime()
            previous.write({"state": "archived"})
            # compile_runtime puts the record back in draft only because it
            # writes the compiled fields, not because activation failed.
            rec.write({
                "state": "active",
                "active": True,
                "activated_by_id": self.env.user.id,
                "activated_at": fields.Datetime.now(),
                "previous_profile_id": previous.id if previous else False,
                "deployment_result_json": json.dumps(applied, sort_keys=True),
            })
        return True


class AiDeploymentWizard(models.TransientModel):
    _name = "ai.customer.deployment.wizard"
    _description = "Customer Deployment Wizard"

    profile_id = fields.Many2one("ai.customer.configuration.profile", required=True)
    dry_run = fields.Boolean(default=True)
    result_json = fields.Text(default="{}")

    def run(self):
        """Validate the profile against the live registry without guessing.

        Readiness is derived from installed modules and the reviewed operations
        actually registered for them. A module with only discovered read
        capabilities is reportable, while every mutation operation must have a
        ready adapter and a unified execution contract.
        """
        profile = self.profile_id
        required_models = [
            "ai.control.authorization", "ai.control.capability", "ai.control.module",
            "ai.integration.adapter", "ai.integration.operation", "ai.integration.subscription",
            "ai.gateway.execution.gate", "ai.gateway.approval", "ai.gateway.access.grant",
            "ai.integration.agent.module",
            "ai.customer.role.assignment", "ai.customer.role.policy", "ai.workflow",
            "ai.document.index.job", "ai.rag.index.snapshot", "ai.model.profile", "ai.gateway.session",
            "ai.customer.sso.provider", "ai.customer.scim.token",
        ]
        checks = {
            "profile": bool(profile),
            "company": bool(profile and profile.company_id),
            "profile_compiled": bool(profile and profile.compiled_hash and profile.compiled_at),
            "required_models": {m: (m in self.env) for m in required_models},
        }

        installed_names = set()
        registry_names = set()
        if "ir.module.module" in self.env:
            installed_names = set(self.env["ir.module.module"].sudo().search(
                [("state", "=", "installed")]).mapped("name"))
        if "ai.control.module" in self.env:
            registry_names = set(self.env["ai.control.module"].sudo().search(
                [("state", "=", "installed")]).mapped("technical_name"))
        missing_registry = sorted(installed_names - registry_names)
        checks["installed_module_count"] = len(installed_names)
        checks["unregistered_installed_modules"] = missing_registry
        checks["all_installed_modules_registered"] = not missing_registry

        # Installation is incomplete until every installed module is joined to
        # the local Company Assistant. Refreshing here is idempotent and keeps
        # the handoff check independent of whether the one-minute onboarding
        # cron has already run.
        bindings = self.env["ai.integration.agent.module"].sudo() if "ai.integration.agent.module" in self.env else None
        if bindings is not None:
            try:
                bindings.refresh_if_stale()
            except Exception:  # noqa: BLE001
                checks["agent_binding_error"] = True
        checks["installed_module_agent_connections"] = {}
        if bindings is not None and "ai.control.module" in self.env:
            for module in self.env["ai.control.module"].sudo().search([
                ("technical_name", "in", sorted(installed_names)),
                ("state", "=", "installed"),
            ]):
                checks["installed_module_agent_connections"][module.technical_name] = bool(
                    module.agent_connected and module.agent_connection_state in (
                        "connected", "connected_no_tools"
                    )
                )
        checks["all_installed_modules_agent_connected"] = bool(
            bindings is not None
            and checks["installed_module_agent_connections"]
            and all(checks["installed_module_agent_connections"].values())
        )

        adapters = self.env["ai.integration.adapter"].sudo() if "ai.integration.adapter" in self.env else None
        all_operations = self.env["ai.integration.operation"].sudo() if "ai.integration.operation" in self.env else None
        active_operations = all_operations.search([("active", "=", True)]) if all_operations is not None else None
        operation_modules_all = set(active_operations.mapped("module_name")) if active_operations is not None else set()
        # Optional operation records are loaded by the integration module even
        # when their native Odoo domain is not installed. They must be
        # reportable, but cannot make an unrelated tenant unready.
        operation_modules = operation_modules_all.intersection(installed_names)
        operations = active_operations.filtered(lambda op: op.module_name in operation_modules) if active_operations is not None else None
        checks["operation_modules"] = sorted(operation_modules)
        checks["uninstalled_operation_modules"] = sorted(operation_modules_all - installed_names)
        checks["operation_modules_installed"] = {
            module: module in installed_names for module in sorted(operation_modules)
        }
        checks["all_operation_modules_installed"] = all(
            checks["operation_modules_installed"].values())
        checks["required_adapters"] = {
            module: bool(adapters.search_count([
                ("module_name", "=", module), ("active", "=", True), ("state", "=", "ready")
            ]))
            for module in sorted(operation_modules)
        } if adapters is not None else {}
        checks["all_required_adapters"] = all(checks["required_adapters"].values())
        checks["operation_contracts"] = {}
        if operations is not None and "ai.integration.unified.registry" in self.env:
            registry = self.env["ai.integration.unified.registry"].sudo()
            for operation in operations:
                try:
                    contract = registry.execution_contract(operation.tool_name)
                    handler = getattr(
                        self.env["ai.integration.adapter.service"],
                        "_handle_%s" % operation.handler_key,
                        None,
                    )
                    checks["operation_contracts"][operation.tool_name] = bool(
                        contract and handler
                    )
                except Exception:  # noqa: BLE001
                    checks["operation_contracts"][operation.tool_name] = False
        checks["all_operation_contracts"] = all(
            checks["operation_contracts"].values())

        subscriptions = self.env["ai.integration.subscription"].sudo() if "ai.integration.subscription" in self.env else None
        active_targets = set(subscriptions.search([("active", "=", True)]).mapped("target")) if subscriptions is not None else set()
        required_targets = {"audit", "ai", "notification"}
        optional_target_modules = {
            "workflow": "ai_workflow", "calendar": "calendar", "buzz": "ai_collaboration",
            "telegram": "ai_telegram_bridge", "memory": "company_ai_demo", "rag": "ai_rag",
        }
        required_targets.update(target for target, module in optional_target_modules.items()
                                if module in installed_names)
        checks["subscriber_matrix"] = sorted(active_targets)
        checks["required_subscribers"] = sorted(required_targets)
        checks["all_subscribers"] = required_targets.issubset(active_targets)
        checks["capability_count"] = self.env["ai.control.capability"].sudo().search_count(
            [("active", "=", True)]) if "ai.control.capability" in self.env else 0
        checks["integration_operations"] = operations.search_count(
            [("active", "=", True)]) if operations is not None else 0
        # A tenant may legitimately have no optional business domain enabled;
        # that is not a failed deployment. If an installed domain is mapped to
        # an operation, however, its reviewed operation set must be present.
        checks["operation_coverage"] = (not operation_modules) or bool(operations)
        checks["workflow_engine"] = "ai.workflow" in self.env
        checks["async_rag"] = "ai.document.index.job" in self.env
        checks["model_registry"] = "ai.model.profile" in self.env
        checks["sso"] = "ai.customer.sso.provider" in self.env
        checks["scim"] = "ai.customer.scim.token" in self.env
        checks["frontend_capability_api"] = True
        checks["all_required_models"] = all(checks["required_models"].values())
        checks["ready"] = bool(
            checks["profile"] and checks["company"] and checks["profile_compiled"]
            and checks["all_required_models"] and checks["all_installed_modules_registered"]
            and checks["all_installed_modules_agent_connected"]
            and checks["all_required_adapters"] and checks["all_operation_modules_installed"]
            and checks["all_operation_contracts"] and checks["all_subscribers"]
            and checks["capability_count"] and checks["operation_coverage"]
        )
        self.result_json = json.dumps(checks, sort_keys=True, ensure_ascii=False)
        if not checks["ready"] and not self.dry_run:
            raise ValueError("Deployment prerequisites failed; production activation is blocked.")
        return True
