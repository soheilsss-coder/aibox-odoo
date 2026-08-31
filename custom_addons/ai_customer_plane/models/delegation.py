from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import date_utils


class AiDelegation(models.Model):
    _name = "ai.customer.delegation"
    _description = "Customer Authorization Delegation"
    _order = "id desc"

    delegator_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    delegatee_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    capability = fields.Char(required=True, index=True)
    resource_model = fields.Char(index=True)
    resource_id = fields.Integer(index=True)
    starts_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    expires_at = fields.Datetime(required=True, index=True)
    approval_id = fields.Many2one("ai.gateway.approval", index=True, ondelete="set null")
    reason = fields.Text(required=True)
    active = fields.Boolean(default=True, index=True)
    created_by = fields.Many2one("res.users", required=True, default=lambda s: s.env.user, readonly=True)
    revoked_at = fields.Datetime(readonly=True)
    revoked_by = fields.Many2one("res.users", readonly=True)

    _sql_constraints = [
        ("valid_window", "CHECK(expires_at > starts_at)", "Delegation expiry must be after its start."),
        ("no_self", "CHECK(delegator_id <> delegatee_id)", "A delegation cannot target the delegator."),
    ]

    @api.constrains("delegator_id", "delegatee_id", "capability", "resource_model", "resource_id")
    def _check_delegator_authority(self):
        for rec in self:
            # Delegation never creates authority for the delegator. The central
            # authorization engine remains the source of truth.
            if rec.delegator_id != self.env.user and not self.env.user.has_group("base.group_system"):
                raise AccessError("Only the delegator or a system administrator may create this delegation.")
            if "ai.gateway.audit.log" in self.env:
                self.env["ai.gateway.audit.log"].sudo().log(user_id=self.env.user.id, source="customer_control_plane", action="delegation.created", payload={"delegation_id": rec.id, "delegator_id": rec.delegator_id.id, "delegatee_id": rec.delegatee_id.id, "capability": rec.capability, "resource_model": rec.resource_model, "resource_id": rec.resource_id, "expires_at": rec.expires_at})
            if "ai.control.authorization" in self.env:
                # Keep delegation on the canonical authorization contract.  The
                # old call passed the user positionally and unsupported
                # ``model``/``res_id`` keywords, which made every constrained
                # create fail with TypeError.  Resolve the optional target
                # record first so the same object-level checks used at runtime
                # also apply while creating the delegation.
                target = False
                if rec.resource_model:
                    if rec.resource_model not in self.env:
                        raise AccessError("Delegation target model is not available.")
                    if rec.resource_id:
                        target = self.env[rec.resource_model].browse(rec.resource_id).exists()
                        if not target:
                            raise AccessError("Delegation target record was not found.")
                allowed = self.env["ai.control.authorization"].sudo().check_capability(
                    rec.capability,
                    user=rec.delegator_id,
                    record=target or None,
                    action="execute",
                )
                if not allowed:
                    raise AccessError("Delegator does not currently hold the capability being delegated.")

    def is_active_now(self):
        self.ensure_one()
        now = fields.Datetime.now()
        return bool(self.active and not self.revoked_at and self.starts_at <= now <= self.expires_at)

    def revoke(self):
        for rec in self:
            if rec.delegator_id != self.env.user and not self.env.user.has_group("base.group_system"):
                raise AccessError("Only the delegator or a system administrator may revoke a delegation.")
            rec.sudo().write({"active": False, "revoked_at": fields.Datetime.now(), "revoked_by": self.env.user.id})
            if "ai.gateway.audit.log" in self.env:
                self.env["ai.gateway.audit.log"].sudo().log(user_id=self.env.user.id, source="customer_control_plane", action="delegation.revoked", payload={"delegation_id": rec.id, "delegatee_id": rec.delegatee_id.id, "capability": rec.capability, "resource_model": rec.resource_model, "resource_id": rec.resource_id})
        return True

    @api.model
    def effective_for(self, user, capability, model=None, res_id=None):
        domain = [
            ("delegatee_id", "=", user.id), ("capability", "=", capability),
            ("active", "=", True), ("revoked_at", "=", False),
            ("starts_at", "<=", fields.Datetime.now()),
            ("expires_at", ">=", fields.Datetime.now()),
        ]
        if model:
            domain += ["|", ("resource_model", "=", False), ("resource_model", "=", model)]
        if res_id:
            domain += ["|", ("resource_id", "=", False), ("resource_id", "=", res_id)]
        return self.sudo().search(domain)
