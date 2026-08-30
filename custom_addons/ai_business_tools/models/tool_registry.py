from odoo import fields, models
from odoo.addons.llm_tool.decorators import llm_tool


class LLMToolRegistry(models.Model):
    _inherit = "llm.tool"

    @llm_tool(read_only_hint=True)
    def list_available_tools(self) -> dict:
        """List every business tool registered in the risk registry
        (roadmap #15 Tool Registry), with its risk level and, for
        sensitive tools, which group must approve it. Useful for a
        human reviewing what an AI-driven session is even capable of,
        or for the assistant itself to check before attempting
        something unfamiliar. Note: this reflects the manually
        maintained registry (data/tool_risk_data.xml), not a live scan
        of every Python method - any custom tool added later must be
        registered there to show up here."""
        risks = self.env["ai.gateway.tool.risk"].sudo().search([], order="risk_level desc, tool_name")
        return {
            "count": len(risks),
            "tools": [
                {
                    "name": r.tool_name,
                    "risk_level": r.risk_level,
                    "requires_approval_from": r.approver_group_id.name if r.approver_group_id else None,
                    "description": r.description or "",
                }
                for r in risks
            ],
        }
