from odoo import api, fields, models
from odoo.exceptions import UserError


class AiGatewayApproval(models.Model):
    """A pending human approval for a high-risk AI-initiated action.
    Used for anything more sensitive than everyday operations (leave,
    tasks) - e.g. HR decrees (raises/promotions/warnings). The AI tool
    that wants to do the risky thing creates one of these in 'pending'
    state and stops; nothing actually happens until someone with the
    right authority (never the same person who requested it) approves
    it here, in the normal Odoo UI."""

    _name = "ai.gateway.approval"
    _description = "AI Gateway - Pending High-Risk Approval"
    _order = "create_date desc"

    name = fields.Char(required=True, help="Short description of the requested action")
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company,
    )
    requested_by_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    approver_group_id = fields.Many2one(
        "res.groups", required=True,
        help="Only members of this group may approve/reject",
    )
    action_model = fields.Char(help="Technical model this approval will act on, e.g. hr.decree")
    action_res_id = fields.Integer(help="Record id this approval is about")
    state = fields.Selection(
        [("pending", "Pending"), ("executing", "Executing"), ("approved", "Approved"), ("rejected", "Rejected"), ("expired", "Expired")],
        default="pending", index=True,
    )
    decided_by_id = fields.Many2one("res.users")
    decision_note = fields.Text()
    policy_snapshot = fields.Text(default="{}", readonly=True, copy=False)
    expires_at = fields.Datetime(readonly=True, copy=False)
    requested_at = fields.Datetime(default=fields.Datetime.now, readonly=True, copy=False)
    approval_hash = fields.Char(readonly=True, copy=False, index=True)
    approval_key = fields.Char(readonly=True, copy=False, index=True)
    tool_name = fields.Char(readonly=True, copy=False, index=True)
    tool_args = fields.Text(readonly=True, copy=False)
    capability_name = fields.Char(readonly=True, copy=False, index=True)
    executed_at = fields.Datetime(readonly=True, copy=False)
    execution_result = fields.Text(readonly=True, copy=False)
    approval_payload_hash = fields.Char(readonly=True, copy=False, index=True)
    integrity_version = fields.Integer(default=2, readonly=True, copy=False)
    execution_nonce_hash = fields.Char(readonly=True, copy=False, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        import hashlib, json
        for vals in vals_list:
            vals.setdefault("company_id", self.env.company.id)
            vals.setdefault("requested_by_id", self.env.user.id)
            vals.setdefault("expires_at", fields.Datetime.add(fields.Datetime.now(), hours=48))
            snapshot = {k: vals.get(k) for k in ("name", "company_id", "requested_by_id", "approver_group_id", "action_model", "action_res_id")}
            payload = {**snapshot, "tool_name": vals.get("tool_name"), "tool_args": vals.get("tool_args"), "capability_name": vals.get("capability_name")}
            vals.setdefault("policy_snapshot", json.dumps(payload, sort_keys=True, default=str))
            vals.setdefault("approval_hash", hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest())
            vals.setdefault("approval_payload_hash", hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest())
            group_id = vals.get("approver_group_id")
            if group_id:
                group = self.env["res.groups"].sudo().browse(int(group_id))
                xmlids = set(group.get_external_id().values()) if group.exists() else set()
                if not any(x.startswith("ai_business_tools.role_") for x in xmlids):
                    raise UserError("Only product-defined approval roles may approve AI actions.")
        records = super().create(vals_list)
        if "ai.gateway.approval.history" in self.env:
            self.env["ai.gateway.approval.history"].sudo().create([
                {"approval_id": rec.id, "event": "created", "actor_id": rec.requested_by_id.id, "state_before": False, "state_after": rec.state}
                for rec in records
            ])
        return records

    def action_approve(self):
        # Serialize approval decisions. Without a row lock two workers can
        # both observe pending and execute the same business action.
        ids = tuple(self.ids)
        if ids:
            self.env.cr.execute("SELECT id FROM ai_gateway_approval WHERE id IN %s FOR UPDATE", [ids])
        self.invalidate_recordset()
        for rec in self:
            if rec.requested_by_id.id == self.env.user.id:
                raise UserError("درخواست‌دهنده نمی‌تواند تاییدیه‌ی خودش را تایید کند.")
            if rec.approver_group_id not in self.env.user.groups_id:
                raise UserError("شما عضو گروه لازم برای تایید این درخواست نیستید.")
            if rec.state != "pending":
                raise UserError("این تاییدیه قبلاً تعیین تکلیف شده است.")
            if rec.expires_at and rec.expires_at < fields.Datetime.now():
                raise UserError("این تاییدیه منقضی شده است.")
            target = self.env[rec.action_model].browse(rec.action_res_id) if (rec.action_model and rec.action_res_id and rec.action_model in self.env) else None
            if rec.action_model and rec.action_res_id and rec.action_model in self.env:
                if not target.exists():
                    raise UserError("رکورد هدف تاییدیه دیگر وجود ندارد؛ عملیات متوقف شد.")
            if "ai.control.authorization" in self.env and rec.capability_name:
                self.env["ai.control.authorization"].require(rec.capability_name, record=target)
            elif "ai.control.authorization" in self.env:
                capability = {"hr.decree": "hr.decree.approve"}.get(rec.action_model)
                if capability:
                    self.env["ai.control.authorization"].require(capability, record=target)
            # Re-validate immutable target/policy immediately before commit.
            rec._verify_integrity()
            rec.with_context(approval_action=True).write({"state": "executing", "decided_by_id": self.env.user.id})
            if "ai.gateway.approval.history" in self.env:
                self.env["ai.gateway.approval.history"].sudo().create({"approval_id": rec.id, "event": "executing", "actor_id": self.env.user.id, "state_before": "pending", "state_after": "executing"})
            rec.with_context(approval_action=True)._apply_approved_action()
            rec.with_context(approval_action=True).write({"state": "approved", "decided_by_id": self.env.user.id})
            if "ai.gateway.approval.history" in self.env:
                self.env["ai.gateway.approval.history"].sudo().create({"approval_id": rec.id, "event": "approved", "actor_id": self.env.user.id, "state_before": "executing", "state_after": "approved"})
            if "ai.control.event" in self.env:
                self.env["ai.control.event"].publish("approval.approved", aggregate=rec, payload={"approval_id": rec.id, "action": rec.action_model})

    def _verify_integrity(self):
        import hashlib, json
        for rec in self:
            snapshot = {"name": rec.name, "company_id": rec.company_id.id, "requested_by_id": rec.requested_by_id.id, "approver_group_id": rec.approver_group_id.id, "action_model": rec.action_model, "action_res_id": rec.action_res_id}
            expected = hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()
            if rec.approval_hash and rec.approval_hash != expected:
                raise UserError("integrity_error: محتوای اصلی تاییدیه تغییر کرده است.")
            if rec.approval_payload_hash:
                payload = {**snapshot, "tool_name": rec.tool_name, "tool_args": rec.tool_args, "capability_name": rec.capability_name}
                expected_payload = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
                if rec.approval_payload_hash != expected_payload:
                    raise UserError("integrity_error: tool/arguments approval payload changed.")
        return True

    @api.model
    def cron_expire_pending(self):
        """Close expired requests so the product never shows a stale action."""
        now = fields.Datetime.now()
        for rec in self.sudo().search([
            ("state", "=", "pending"), ("expires_at", "!=", False),
            ("expires_at", "<=", now),
        ]):
            rec.with_context(approval_action=True).write({
                "state": "expired", "decision_note": "expired",
            })
            if "ai.gateway.approval.history" in self.env:
                self.env["ai.gateway.approval.history"].sudo().create({
                    "approval_id": rec.id, "event": "expired", "actor_id": self.env.user.id,
                    "state_before": "pending", "state_after": "expired", "note": "expired",
                })
            if "ai.control.event" in self.env:
                self.env["ai.control.event"].sudo().publish(
                    "approval.expired", aggregate=rec,
                    payload={"approval_id": rec.id, "action": rec.action_model},
                )
        return True

    def action_reject(self, note=""):
        for rec in self:
            if rec.state != "pending":
                raise UserError("این تاییدیه دیگر در انتظار تصمیم نیست.")
            if rec.expires_at and rec.expires_at < fields.Datetime.now():
                raise UserError("این تاییدیه منقضی شده است.")
            if rec.approver_group_id not in self.env.user.groups_id:
                raise UserError("شما عضو گروه لازم برای رد این درخواست نیستید.")
            old_state = rec.state
            rec.with_context(approval_action=True).write({"state": "rejected", "decided_by_id": self.env.user.id,
                       "decision_note": note})
            if "ai.gateway.approval.history" in self.env:
                self.env["ai.gateway.approval.history"].sudo().create({"approval_id": rec.id, "event": "rejected", "actor_id": self.env.user.id, "state_before": old_state, "state_after": "rejected", "note": note})
            if "ai.control.event" in self.env:
                self.env["ai.control.event"].publish(
                    "approval.rejected", aggregate=rec,
                    payload={"approval_id": rec.id, "action": rec.action_model, "decision_note": note},
                )

    def action_cancel(self):
        for rec in self:
            if rec.state != "pending":
                raise UserError("فقط تاییدیه در انتظار را می‌توان لغو کرد.")
            if self.env.user != rec.requested_by_id and not self.env.user.has_group("base.group_system"):
                raise UserError("فقط درخواست‌دهنده یا مدیر سیستم می‌تواند تاییدیه را لغو کند.")
            rec.with_context(approval_action=True).write({"state": "rejected", "decided_by_id": self.env.user.id, "decision_note": "cancelled"})
            if "ai.gateway.approval.history" in self.env:
                self.env["ai.gateway.approval.history"].sudo().create({"approval_id": rec.id, "event": "cancelled", "actor_id": self.env.user.id, "state_before": "pending", "state_after": "rejected", "note": "cancelled"})
            if "ai.control.event" in self.env:
                self.env["ai.control.event"].publish(
                    "approval.cancelled", aggregate=rec,
                    payload={"approval_id": rec.id, "action": rec.action_model},
                )

    def _apply_approved_action(self):
        """Hook: called right after approval. Each risky action type
        registers what 'actually do it now' means - kept here (not in
        the tool file) so the tool only ever CREATES a pending request,
        never performs the sensitive step itself."""
        self.ensure_one()
        if self.tool_name:
            import json
            if self.executed_at:
                raise UserError("این عملیات قبلاً اجرا شده است.")
            args = json.loads(self.tool_args or "{}")
            result = self.env["ai.gateway.execution.gate"].with_context(
                ai_gateway_approved_execution=self.id
            ).execute_approved(self.tool_name, args)
            self.with_context(approval_action=True).write({
                "executed_at": fields.Datetime.now(),
                "execution_result": json.dumps(result, ensure_ascii=False, default=str),
            })
            return
        if self.action_model == "hr.decree" and self.action_res_id:
            decree = self.env["hr.decree"].browse(self.action_res_id)
            if decree.exists() and hasattr(decree, "action_mark_approved"):
                decree.action_mark_approved()
    def write(self, vals):
        protected = {"company_id", "requested_by_id", "approver_group_id", "action_model", "action_res_id", "name", "policy_snapshot", "approval_hash", "expires_at", "requested_at", "state", "decided_by_id", "approval_key", "tool_name", "tool_args", "capability_name", "executed_at", "execution_result", "approval_payload_hash", "integrity_version"}
        if not self.env.context.get("approval_action") and protected.intersection(vals):
            raise UserError("اطلاعات اصلی تاییدیه قابل ویرایش نیست؛ فقط approve/reject/cancel از مسیر مجاز انجام شود.")
        return super().write(vals)

