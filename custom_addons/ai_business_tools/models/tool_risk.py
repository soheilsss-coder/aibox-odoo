from odoo import api, fields, models
from odoo.exceptions import UserError


class AiGatewayToolRisk(models.Model):
    """Central risk registry for AI tools (roadmap #20 Risk Engine).

    The registry is an explicit catalog, but enforcement is NOT optional
    at tool level: every AI execution must enter
    ai.gateway.execution.gate, which resolves this registry plus the
    unified Capability/Tool contract before authorization, risk, approval
    and commit-time checks. Tool methods may call the gate for defense in
    depth; they are not the authoritative security boundary. Unknown or
    unregistered tools are denied by default.

    RISK_0 = read-only, no gate needed
    RISK_1 = low-impact write (e.g. create your own task/leave request)
    RISK_2 = business mutation affecting someone else (approve/reject)
    RISK_3 = sensitive - requires an ai.gateway.approval from a human
             other than the requester before it takes effect
    RISK_4 = high impact (pay/employment) - same as RISK_3 but always
             requires an approver group, never optional
    RISK_5 = human-only, no AI tool should ever be allowed to do this
             at all (e.g. deleting a user, changing someone's salary
             number directly) - not currently exposed as a tool
    """

    _name = "ai.gateway.tool.risk"
    _description = "AI Gateway - Tool Risk Registry"
    _rec_name = "tool_name"

    tool_name = fields.Char(required=True, index=True)
    # Explicit owner of the tool surface. This prevents an installed
    # module's tool from being offered to the agent (or executed directly)
    # after that module is absent from the current database.
    module_name = fields.Char(index=True, help="Technical addon that owns this AI tool")
    risk_level = fields.Integer(required=True, default=0)
    approver_group_id = fields.Many2one(
        "res.groups",
        help="Required for risk_level >= 3 - who may approve this tool's pending actions",
    )
    description = fields.Char()
    capability_name = fields.Char(index=True, help="Central authorization capability required by this tool")

    _sql_constraints = [
        ("tool_name_unique", "unique(tool_name)", "This tool already has a risk entry."),
    ]

    @api.model
    def get_risk_level(self, tool_name):
        rec = self.sudo().search([("tool_name", "=", tool_name)], limit=1)
        return rec.risk_level if rec else 5

    @api.model
    def get_approver_group(self, tool_name):
        rec = self.sudo().search([("tool_name", "=", tool_name)], limit=1)
        return rec.approver_group_id if rec else self.env["res.groups"]

    @api.model
    def enforce(self, tool_name, context_label=""):
        """Backward-compatible shim. All enforcement is now centralized
        in ai.gateway.execution.gate; no business tool should implement
        its own risk decision.
        """
        return self.env["ai.gateway.execution.gate"].authorize(
            tool_name, context_label=context_label
        )

    @api.model
    def registered_tool_ids(self):
        installed_names = set(self.env["ir.module.module"].sudo().search([
            ("state", "=", "installed"),
        ]).mapped("name"))
        risks = self.sudo().search([]).filtered(
            lambda risk: bool(risk.module_name and risk.module_name in installed_names)
        )
        names = set(risks.mapped("tool_name"))
        Tool = self.env["llm.tool"]
        return Tool.search([]).filtered(lambda t: (getattr(t, "name", "") or "") in names and not (getattr(t, "name", "") or "").startswith("llm_tool_odoo_")).ids

    @api.model
    def allowed_tool_ids_for_user(self, user=None):
        """Return the tools the caller is allowed to invoke/request.

        Approval authority is deliberately NOT required here: a requester
        may invoke a high-risk tool and receive a durable approval request.
        Only the configured approver must belong to approver_group_id.
        Capability authorization remains the primary role/resource gate.
        """
        user = user or self.env.user
        risks = self.sudo().search([])
        installed_names = set(self.env["ir.module.module"].sudo().search([
            ("state", "=", "installed"),
        ]).mapped("name"))
        allowed_names = set()
        for risk in risks:
            # A risk row is not proof that its owning addon is installed.
            # Keep optional module tools out of the agent until the official
            # module and its server-side adapter are present in this database.
            if not risk.module_name or risk.module_name not in installed_names:
                # Unowned tool metadata is not an agent connection. Require
                # an explicit module owner before the tool can be advertised.
                continue
            if risk.risk_level >= 5:
                continue
            if risk.capability_name and "ai.control.authorization" in self.env:
                if not self.env["ai.control.authorization"].decide(
                    risk.capability_name, user=user
                ):
                    continue
            elif risk.risk_level >= 2 and not risk.capability_name:
                if not any(user.has_group(x) for x in (
                    "ai_business_tools.role_manager",
                    "ai_business_tools.role_hr_manager",
                    "ai_business_tools.role_executive",
                )):
                    continue
            allowed_names.add(risk.tool_name)
        Tool = self.env["llm.tool"]
        result = Tool.browse()
        for tool in Tool.search([]):
            name = getattr(tool, "name", "") or ""
            if name in allowed_names and not name.startswith("llm_tool_odoo_"):
                result |= tool
        return result.ids

