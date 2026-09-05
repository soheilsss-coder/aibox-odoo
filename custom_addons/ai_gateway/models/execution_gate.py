import hashlib
import json
import secrets
from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class AiGatewayExecutionGate(models.AbstractModel):
    """Single mandatory policy boundary for AI tool execution.

    The model deliberately lives in ai_gateway so every business-tool
    addon depends on the same gate. A tool is never trusted merely
    because it is registered with the LLM framework: the gate evaluates
    registration, capability authorization, risk and (for RISK 3/4)
    human approval before the business method is allowed to mutate data.

    RISK 5 is always denied. RISK 3/4 create one durable approval
    request containing the exact tool+arguments. Approval re-executes
    the exact action through this same gate with a one-time context flag.
    """
    _name = "ai.gateway.execution.gate"
    _description = "Central AI Tool Execution Gate"

    @api.model
    def _registry(self, tool_name):
        # v46: the unified integration registry is the mandatory source of
        # the Capability→Tool→Risk contract. The legacy risk registry remains
        # for compatibility but may not define an executable tool by itself.
        if "ai.integration.unified.registry" in self.env:
            registry = self.env["ai.integration.unified.registry"]
            # Only fall back to the native-tool risk registry when the tool is
            # not a reviewed business operation. A registered operation with
            # a missing/mismatched risk or capability contract must fail closed;
            # treating its AccessError as a native-tool fallback would bypass
            # the unified contract.
            if registry.resolve(tool_name):
                return registry.execution_contract(tool_name)
        if "ai.gateway.tool.risk" not in self.env:
            return None
        risk = self.env["ai.gateway.tool.risk"].sudo().search(
            [("tool_name", "=", tool_name)], limit=1
        )
        if not risk:
            return None
        return (None, risk, None)

    @api.model
    def _profile_allows_tool(self, tool_name):
        """Apply the active customer's compiled tool policy at execution time."""
        if "ai.customer.configuration.profile" not in self.env:
            return True
        profile = self.env["ai.customer.configuration.profile"].active_for_company(self.env.company)
        if not profile:
            return True
        policy = profile.runtime_config().get("sections", {}).get("tools", {})
        allowed = policy.get("allowed_tools", policy.get("allow", []))
        denied = policy.get("denied_tools", policy.get("deny", []))
        if isinstance(allowed, list) and allowed and tool_name not in {str(item) for item in allowed}:
            return False
        if isinstance(denied, list) and tool_name in {str(item) for item in denied}:
            return False
        return True

    @api.model
    def _audit(self, action, payload, success=True, error_message=None):
        if "ai.gateway.audit.log" in self.env:
            self.env["ai.gateway.audit.log"].sudo().log(
                user_id=self.env.user.id, source="execution_gate", action=action,
                payload=payload, success=success, error_message=error_message
            )

    @api.model
    def _approval_key(self, tool_name, args, user_id, company_id=None):
        raw = json.dumps(
            {"tool": tool_name, "args": args or {}, "user": user_id,
             "company": company_id or self.env.company.id},
            sort_keys=True, default=str, ensure_ascii=False
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    @api.model
    def _resolve_target(self, operation, args):
        """Resolve a concrete ERP target from reviewed adapter arguments.
        Create operations intentionally have no record yet; their immutable
        argument payload is the target contract. Mutating/approval operations
        with an id field must carry that exact record into the approval.
        """
        if not operation or not args:
            return None
        model = None
        field_map = {
            "stock.transfer.confirm": ("stock.picking", "picking_id"),
            "account.invoice.post": ("account.move", "move_id"),
            "approve_leave": ("hr.leave", "leave_id"),
            "reject_leave": ("hr.leave", "leave_id"),
        }
        key = operation.tool_name if hasattr(operation, "tool_name") else None
        if key in field_map:
            model, field = field_map[key]
            rid = args.get(field)
            if rid and model in self.env:
                rec = self.env[model].browse(int(rid))
                return rec if rec.exists() else None
        model_name = getattr(operation, "model_name", False)
        rid = args.get("record_id") or args.get("id")
        if model_name and rid and model_name in self.env:
            rec = self.env[model_name].browse(int(rid))
            return rec if rec.exists() else None
        return None

    @api.model
    def authorize(self, tool_name, args=None, record=None, context_label="",
                  create_approval=True):
        """Authorize the current tool invocation or stop it.

        Returns a small decision dictionary for successful low-risk
        calls. High-risk calls raise UserError after creating a durable
        approval request, so the underlying tool method is never reached.
        """
        args = args or {}
        contract = self._registry(tool_name)
        if not contract:
            self._audit(tool_name, {"reason": "unregistered_tool"}, False, "unregistered_tool")
            raise AccessError("access_denied: AI tool is not registered in the central risk registry")

        operation, rec, cap = contract
        if not self._profile_allows_tool(tool_name):
            self._audit(tool_name, {"reason": "customer_profile_tool_policy"}, False, "customer_profile_tool_policy")
            raise AccessError("access_denied: this tool is disabled by the active customer configuration profile")
        # Risk rows for optional tools are durable metadata, not proof that the
        # owning official addon is installed in this database. Reject stale
        # direct-tool calls here as well as in the assistant catalog.
        owner = getattr(rec, "module_name", False) if rec else getattr(operation, "module_name", False)
        if rec and not operation and not owner:
            self._audit(tool_name, {"reason": "tool_owner_missing"}, False, "tool_owner_missing")
            raise AccessError("access_denied: AI tool has no owning module connection")
        if owner and "ir.module.module" in self.env:
            installed = self.env["ir.module.module"].sudo().search([
                ("name", "=", owner), ("state", "=", "installed"),
            ], limit=1)
            if not installed:
                self._audit(tool_name, {"reason": "owner_module_not_installed", "module": owner}, False, "owner_module_not_installed")
                raise AccessError("access_denied: the owning module is not installed")
        # The binding is the single runtime join between Capability, Tool,
        # Risk and Approval. Older releases accidentally referenced a
        # non-existent local variable here, which made every gate call fail
        # with NameError before reaching authorization. Resolve it explicitly
        # and verify that it cannot contradict the canonical operation/risk
        # contract.
        binding = None
        if "ai.control.tool.binding" in self.env:
            binding = self.env["ai.control.tool.binding"].sudo().search(
                [("tool_name", "=", tool_name), ("active", "=", True)], limit=1
            )
            if binding:
                binding = binding[0]
                if binding.capability_name != (operation.capability_name if operation else rec.capability_name):
                    raise AccessError("execution contract mismatch: capability binding differs from registry")
                if int(binding.risk_level or 0) != int(operation.risk_level if operation else rec.risk_level or 0):
                    raise AccessError("execution contract mismatch: risk binding differs from registry")
        if record is None:
            record = self._resolve_target(operation, args)
        risk = int(binding.risk_level if binding else (operation.risk_level if operation else rec.risk_level or 0))
        capability = binding.capability_name if binding else (operation.capability_name if operation else rec.capability_name)
        payload = {"tool": tool_name, "risk_level": risk, "capability": capability, "context": context_label}

        # Approval replay is only possible from the approval executor,
        # never from an arbitrary caller that can set a model context.
        approved = self.env.context.get("ai_gateway_approved_execution")
        if approved:
            if not self.env.context.get("approval_action"):
                raise AccessError("approved execution requires the internal approval executor")
            if "ai.gateway.approval" not in self.env:
                raise AccessError("approved execution cannot be verified")
            approval = self.env["ai.gateway.approval"].sudo().browse(int(approved))
            valid_state = approval.state == "approved" or (approval.state == "executing" and self.env.context.get("approval_action"))
            if not approval.exists() or not valid_state or approval.executed_at or approval.decided_by_id.id != self.env.user.id:
                raise AccessError("approval token is invalid, expired or already executed")
            if approval.company_id != self.env.company:
                raise AccessError("approval token belongs to another company")
            # The approver executes the already-approved action. Requiring
            # requested_by_id here would make every legitimate approval fail
            # because self-approval is explicitly forbidden.
            if approval.tool_name != tool_name or approval.decided_by_id.id != self.env.user.id:
                raise AccessError("approval token does not match this tool invocation")
            try:
                approved_args = json.loads(approval.tool_args or "{}")
            except Exception:
                raise AccessError("approval token has invalid stored arguments")
            if approved_args != args:
                raise AccessError("approval token does not match the exact approved arguments")
        elif risk >= 5:
            self._audit(tool_name, payload, False, "risk_5_human_only")
            raise AccessError("access_denied: RISK_5 tools are human-only")

        if capability and "ai.control.authorization" in self.env:
            self.env["ai.control.authorization"].require(capability, record=record)

        # High-impact AI actions must stop before the business method.
        if not approved and risk >= 3:
            if not create_approval or "ai.gateway.approval" not in self.env:
                raise AccessError("approval_required: this AI action requires human approval")
            Approval = self.env["ai.gateway.approval"].sudo()
            key = self._approval_key(tool_name, args, self.env.user.id, self.env.company.id)
            existing = Approval.search([
                ("approval_key", "=", key), ("company_id", "=", self.env.company.id),
                ("state", "=", "pending"),
            ], limit=1)
            if existing:
                approval = existing
            else:
                group = binding.approval_group_id if binding and binding.approval_group_id else rec.approver_group_id
                if not group:
                    raise AccessError("approval_required: no approver group is configured for this tool")
                approval = Approval.create({
                    "name": "AI approval: %s" % tool_name,
                    "requested_by_id": self.env.user.id,
                    "approver_group_id": group.id,
                    "tool_name": tool_name,
                    "tool_args": json.dumps(args, ensure_ascii=False, sort_keys=True, default=str),
                    "approval_key": key,
                    "action_model": record._name if record else False,
                    "action_res_id": record.id if record else False,
                    "capability_name": capability or False,
                })
            self._audit(tool_name, {**payload, "approval_id": approval.id}, False, "approval_required")
            raise UserError("approval_required: approval #%s created; the action will execute only after an authorized human approves it." % approval.id)

        self._audit(tool_name, payload, True)
        return {"allowed": True, "risk_level": risk, "capability": capability}

    @api.model
    def execute_approved(self, tool_name, args=None):
        args = args or {}
        approval_id = self.env.context.get("ai_gateway_approved_execution")
        idempotency_key = None
        if approval_id and "ai.gateway.approval" in self.env:
            approval = self.env["ai.gateway.approval"].sudo().browse(int(approval_id))
            if approval.exists():
                idempotency_key = approval.approval_key or ("approval:%s" % approval.id)
        Tool = self.env["llm.tool"]
        method = getattr(Tool, tool_name, None)
        # Reviewed ERP business adapters are first-class tools even when
        # the underlying llm.tool addon has no Python method with this name.
        if not callable(method) and "ai.integration.unified.registry" in self.env:
            self.authorize(tool_name, args=args)
            return self._execute_once(tool_name, args, idempotency_key=idempotency_key)
        if not callable(method):
            raise UserError("tool_not_found: %s" % tool_name)
        # The approval record has already been validated by the caller;
        # authorize() re-checks capability/risk and verifies the one-time token.
        self.authorize(tool_name, args=args)
        return self._execute_once(tool_name, args, method=method, idempotency_key=idempotency_key)

    @api.model
    def _execute_once(self, tool_name, args=None, method=None, idempotency_key=None):
        args = args or {}
        idem = self.env["ai.gateway.idempotency"].sudo() if "ai.gateway.idempotency" in self.env else None
        if idem and idempotency_key:
            rec, owner = idem.claim(self.env.user.id, idempotency_key, tool_name)
            if rec and not owner:
                if rec.status == "completed":
                    return idem.get_cached(self.env.user.id, idempotency_key)
                raise UserError("idempotency_in_progress: another request owns this action")
        if method is None:
            if "ai.integration.unified.registry" in self.env:
                result = self.env["ai.integration.unified.registry"].execute(tool_name, args=args)
            else:
                Tool = self.env["llm.tool"]
                method = getattr(Tool, tool_name, None)
                if not callable(method):
                    raise UserError("tool_not_found: %s" % tool_name)
                result = method(**args)
        else:
            result = method(**args)
        if idem and idempotency_key:
            idem.browse(rec.id).complete(result)
        return result

    @api.model
    def execute(self, tool_name, args=None, idempotency_key=None):
        """Canonical gateway execution endpoint for integrations/workflows.
        Direct callers cannot bypass authorize()."""
        args = args or {}
        self.authorize(tool_name, args=args)
        Tool = self.env["llm.tool"]
        method = getattr(Tool, tool_name, None)
        return self._execute_once(tool_name, args, method=method if callable(method) else None, idempotency_key=idempotency_key)
