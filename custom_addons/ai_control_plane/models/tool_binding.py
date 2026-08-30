from odoo import api, fields, models

class AiToolBinding(models.Model):
    _name = "ai.control.tool.binding"
    _description = "Unified Capability to Tool Binding"
    tool_name = fields.Char(required=True, index=True)
    capability_name = fields.Char(required=True, index=True)
    policy_id = fields.Many2one("ai.control.policy", index=True, ondelete="set null")
    risk_level = fields.Integer(default=0)
    approval_required = fields.Boolean(default=False)
    approval_group_id = fields.Many2one("res.groups", ondelete="restrict")
    handler_key = fields.Char()
    active = fields.Boolean(default=True, index=True)
    source = fields.Selection([("registry", "Registry"), ("adapter", "Adapter"), ("system", "System")], default="registry", required=True)
    _sql_constraints=[("tool_unique","unique(tool_name)","Tool binding already exists.")]

    @api.model
    def sync_from_risk_registry(self):
        if "ai.gateway.tool.risk" not in self.env:
            return 0
        count=0
        for risk in self.env["ai.gateway.tool.risk"].sudo().search([]):
            if not risk.capability_name:
                continue
            binding=self.sudo().search([("tool_name","=",risk.tool_name)],limit=1)
            vals={"tool_name":risk.tool_name,"capability_name":risk.capability_name,"risk_level":risk.risk_level,"approval_required":risk.risk_level>=3,"approval_group_id":risk.approver_group_id.id or False,"source":"registry","active":risk.risk_level<5}
            if binding: binding.write(vals)
            else: self.sudo().create(vals)
            count+=1
        return count
