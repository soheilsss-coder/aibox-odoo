from odoo import api, fields, models


class AiGatewayApprovalMatrix(models.Model):
    """Deterministic approval-threshold rules (roadmap #31 Rules
    Engine) - e.g. 'purchase under 1,000 -> manager; 1,000-10,000 ->
    manager+finance; over 10,000 -> CFO+CEO'. The point: this table is
    the source of truth, never the AI's own judgment - a tool looks up
    get_approver_group() and follows it exactly, it never estimates
    who should approve something based on the amount itself.

    No purchase/expense tool exists yet in this project (see roadmap
    item list), so this table currently only has one entry
    (generate_hr_decree, which does not vary by amount - process=None
    threshold). It is built generic on purpose so the NEXT tool that
    needs threshold-based approval (e.g. a future create_purchase_
    request) just adds rows here instead of hardcoding logic in
    Python."""

    _name = "ai.gateway.approval.matrix"
    _description = "AI Gateway - Approval Threshold Rules"
    _order = "process, min_amount"

    process = fields.Char(required=True, index=True, help="e.g. 'purchase', 'expense', 'hr_decree'")
    min_amount = fields.Float(default=0.0, help="Inclusive lower bound; 0 = no lower bound")
    max_amount = fields.Float(help="Exclusive upper bound; empty = no upper bound")
    approver_group_id = fields.Many2one("res.groups", required=True)
    notes = fields.Char()

    @api.model
    def get_approver_group(self, process, amount=None):
        """Returns the res.groups recordset required to approve this
        process at this amount, following the FIRST matching rule in
        order - never guessed, never left to the AI to infer."""
        domain = [("process", "=", process)]
        rules = self.sudo().search(domain, order="min_amount")
        if amount is None:
            return rules[:1].approver_group_id if rules else self.env["res.groups"]
        for rule in rules:
            lower_ok = amount >= rule.min_amount
            upper_ok = (not rule.max_amount) or amount < rule.max_amount
            if lower_ok and upper_ok:
                return rule.approver_group_id
        return self.env["res.groups"]
