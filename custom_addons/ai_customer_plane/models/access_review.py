from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AiAccessReview(models.Model):
    _name = "ai.customer.access.review"
    _description = "Customer Access Review"
    _order = "id desc"

    name = fields.Char(required=True)
    reviewer_id = fields.Many2one("res.users", required=True, default=lambda s: s.env.user)
    scope_company_id = fields.Many2one("res.company", default=lambda s: s.env.company)
    status = fields.Selection([
        ("draft", "Draft"), ("open", "Open"), ("completed", "Completed"), ("cancelled", "Cancelled")
    ], default="draft", required=True, index=True)
    due_at = fields.Datetime(index=True)
    line_ids = fields.One2many("ai.customer.access.review.line", "review_id")
    completed_at = fields.Datetime(readonly=True)

    def complete(self):
        if not any(self.env.user.has_group(x) for x in (
            "ai_business_tools.role_security", "ai_business_tools.role_executive",
            "ai_business_tools.role_system_admin"
        )):
            raise ValidationError("Only Security, Executive or System Admin may complete an access review.")
        for rec in self:
            rec.write({"status": "completed", "completed_at": fields.Datetime.now()})
        return True


class AiAccessReviewLine(models.Model):
    _name = "ai.customer.access.review.line"
    _description = "Access Review Line"

    review_id = fields.Many2one("ai.customer.access.review", required=True, ondelete="cascade")
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade")
    capability = fields.Char(index=True)
    decision = fields.Selection([
        ("pending", "Pending"), ("retain", "Retain"), ("revoke", "Revoke")
    ], default="pending", required=True)
    evidence = fields.Text()
    decided_by = fields.Many2one("res.users", readonly=True)
    decided_at = fields.Datetime(readonly=True)

    def decide(self, decision, evidence=None):
        if not any(self.env.user.has_group(x) for x in (
            "ai_business_tools.role_security", "ai_business_tools.role_executive",
            "ai_business_tools.role_system_admin"
        )):
            raise ValidationError("Only Security, Executive or System Admin may decide an access review.")
        if decision not in ("retain", "revoke"):
            raise ValueError("Invalid access-review decision.")
        for line in self:
            if line.review_id.status not in ("open", "draft"):
                raise ValidationError("Access-review lines can only be decided while the review is open.")
            if decision == "revoke":
                # Revocation must change the authorization facts, not merely record
                # a human decision. Temporary/delegated grants are the supported
                # revocable authorization layer and are never converted to role edits.
                Grant = self.env["ai.gateway.access.grant"].sudo()
                grants = Grant.search([
                    ("to_user_id", "=", line.user_id.id),
                    ("capability_name", "=", line.capability),
                    ("active", "=", True),
                ])
                for grant in grants:
                    grant.action_revoke_now()
                Delegation = self.env["ai.customer.delegation"] if "ai.customer.delegation" in self.env else None
                if Delegation:
                    delegations = Delegation.sudo().search([
                        ("delegatee_id", "=", line.user_id.id),
                        ("capability", "=", line.capability),
                        ("active", "=", True),
                    ])
                    for delegation in delegations:
                        delegation.revoke()
            line.write({
                "decision": decision, "evidence": evidence or False,
                "decided_by": self.env.user.id, "decided_at": fields.Datetime.now()
            })
        return True
