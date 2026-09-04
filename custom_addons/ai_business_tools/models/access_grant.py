import logging
from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import ValidationError, AccessError

_logger = logging.getLogger(__name__)


class AiGatewayAccessGrant(models.Model):
    """Ephemeral authorization grant.

    v42 deliberately NEVER edits res.groups.users.  A grant is an authorization
    fact evaluated by the central Authorization Engine, not a temporary role
    membership.  This removes the classic expiry race where revoking one grant
    can accidentally remove a user's permanent role.
    """

    _name = "ai.gateway.access.grant"
    _description = "Temporary / Delegated Access Grant"
    _order = "create_date desc"

    to_user_id = fields.Many2one("res.users", required=True, string="Grant To", index=True, ondelete="cascade")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True, ondelete="restrict")
    group_id = fields.Many2one("res.groups", string="Role / Group", index=True, ondelete="restrict")
    capability_name = fields.Char(index=True, string="Capability")
    resource_model = fields.Char(index=True)
    resource_id = fields.Integer(index=True)
    delegated_from_id = fields.Many2one("res.users", string="Delegated From", index=True, ondelete="restrict")
    start_date = fields.Date(default=fields.Date.context_today, required=True)
    expires_on = fields.Date(required=True)
    reason = fields.Char(required=True)
    state = fields.Selection([
        ("scheduled", "Scheduled"), ("active", "Active"),
        ("expired", "Expired"), ("revoked", "Revoked"),
    ], default="scheduled", index=True, required=True)
    granted_by_id = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True, ondelete="restrict")
    approved_by_id = fields.Many2one("res.users", readonly=True, ondelete="restrict")
    approved_at = fields.Datetime(readonly=True)
    grant_type = fields.Selection([
        ("temporary", "Temporary"), ("delegated", "Delegated")
    ], default="temporary", required=True)
    approval_id = fields.Many2one("ai.gateway.approval", readonly=True, ondelete="set null")
    active = fields.Boolean(default=True, index=True)

    @api.constrains("start_date", "expires_on")
    def _check_dates(self):
        for rec in self:
            if rec.expires_on < rec.start_date:
                raise ValidationError("Grant expiry must be on or after its start date.")
            if rec.expires_on < fields.Date.context_today(rec):
                # Historical records may be imported, but newly created grants
                # must not be born already expired.
                if rec.create_date and rec.create_date.date() >= fields.Date.context_today(rec):
                    raise ValidationError("A new grant cannot already be expired.")

    @api.constrains("company_id", "to_user_id", "delegated_from_id", "group_id", "capability_name", "resource_model", "resource_id", "grant_type")
    def _check_scope(self):
        for rec in self:
            if rec.company_id and rec.to_user_id and rec.company_id not in rec.to_user_id.company_ids:
                raise ValidationError("Grant recipient must belong to the grant company.")
            if rec.company_id and rec.delegated_from_id and rec.company_id not in rec.delegated_from_id.company_ids:
                raise ValidationError("Delegator must belong to the grant company.")
            if not rec.group_id and not rec.capability_name:
                raise ValidationError("A grant must contain a group or capability.")
            if rec.resource_id and not rec.resource_model:
                raise ValidationError("resource_model is required when resource_id is set.")
            if rec.grant_type == "delegated" and not rec.delegated_from_id:
                raise ValidationError("Delegated grants require a delegator.")
            if rec.delegated_from_id and rec.delegated_from_id == rec.to_user_id:
                raise ValidationError("A user cannot delegate to themselves.")

    @api.constrains("group_id")
    def _check_role_group(self):
        for rec in self:
            if not rec.group_id:
                continue
            module = getattr(rec.group_id, "module", "") or ""
            xmlid = rec.group_id.get_external_id().get(rec.group_id.id, "") or ""
            if module != "ai_business_tools" and not xmlid.startswith("ai_business_tools."):
                raise ValidationError("Only product-defined role groups may receive temporary/delegated access.")

    @api.model
    def _active_grants_for(self, user, capability=None, record=None):
        today = fields.Date.context_today(self)
        domain = [
            ("to_user_id", "=", user.id), ("company_id", "=", self.env.company.id),
            ("state", "=", "active"), ("active", "=", True),
            ("start_date", "<=", today), ("expires_on", ">=", today),
        ]
        if capability:
            domain += ["|", ("capability_name", "=", capability), ("capability_name", "=", False)]
        grants = self.sudo().search(domain)
        if not record:
            return grants
        return grants.filtered(lambda g: not g.resource_id or (
            g.resource_model == record._name and g.resource_id == record.id
        ))

    @api.model
    def effective_groups(self, user):
        """Return permanent groups + grant-derived groups WITHOUT mutating membership."""
        groups = user.groups_id
        for grant in self._active_grants_for(user):
            if grant.group_id:
                groups |= grant.group_id
        return groups

    @api.model
    def grant_allows(self, user, capability, record=None):
        """Central-engine helper: grants may authorize a capability or role.

        Delegated grants are valid only while the delegator remains authorized
        for the same capability/resource. This prevents privilege laundering.
        """
        for grant in self._active_grants_for(user, capability=capability, record=record):
            if grant.capability_name and grant.capability_name != capability:
                continue
            if grant.grant_type == "delegated":
                if not grant.delegated_from_id:
                    continue
                # Prevent recursive delegation chains: the delegator must hold
                # permanent/effective authority, but a grant-derived authority
                # is intentionally not accepted as the source of delegation.
                source_groups = grant.delegated_from_id.groups_id
                if grant.group_id and grant.group_id not in source_groups:
                    continue
            return True
        return False

    def action_approve(self):
        for rec in self:
            if rec.state != "scheduled":
                raise ValidationError("Only scheduled grants can be approved.")
            if rec.grant_type == "delegated" and rec.delegated_from_id:
                if rec.group_id and rec.group_id not in rec.delegated_from_id.groups_id:
                    raise AccessError("Delegator does not hold the delegated role.")
            rec.write({
                "state": "active" if rec.start_date <= fields.Date.context_today(rec) else "scheduled",
                "approved_by_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
            })

    def action_revoke_now(self):
        for rec in self:
            rec.write({"state": "revoked", "active": False})
            if "ai.gateway.audit.log" in self.env:
                self.env["ai.gateway.audit.log"].sudo().log(
                    user_id=self.env.context.get("authorization_actor_id") or self.env.user.id,
                    source="authorization", action="access_grant_revoked",
                    payload={"grant_id": rec.id, "user_id": rec.to_user_id.id,
                             "capability": rec.capability_name, "resource_model": rec.resource_model,
                             "resource_id": rec.resource_id},
                )

    @api.model
    def cron_apply_and_expire_grants(self):
        """Only transitions grant state. It never edits res.groups.users."""
        today = fields.Date.context_today(self)
        scheduled = self.sudo().search([("state", "=", "scheduled"), ("start_date", "<=", today)])
        for grant in scheduled:
            grant.write({"state": "active"})
        expired = self.sudo().search([("state", "=", "active"), ("expires_on", "<", today)])
        for grant in expired:
            grant.write({"state": "expired", "active": False})
            _logger.info("access_grant expired: id=%s user=%s", grant.id, grant.to_user_id.login)
