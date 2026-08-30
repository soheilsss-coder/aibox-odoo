import logging

from odoo import fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.llm_tool.decorators import llm_tool

_logger = logging.getLogger(__name__)


def _audit(env, action, payload, success=True, error_message=None):
    env["ai.gateway.audit.log"].sudo().log(
        user_id=env.user.id, source="tool", action=action,
        payload=payload, success=success, error_message=error_message,
    )


class LLMToolHrLeave(models.Model):
    _inherit = "llm.tool"

    # NOTE: self-service "request my own leave" already exists as
    # create_leave_request in company_ai_demo/models/leave_request.py -
    # not duplicated here. What was missing (and is added below) is the
    # MANAGER side: approving/rejecting someone else's request, which
    # is the part that actually needs a permission check.

    # ------------------------------------------------------------------
    # Manager-facing: approve/reject SOMEONE ELSE'S request
    # ------------------------------------------------------------------
    @llm_tool(destructive_hint=True)
    def approve_leave(self, employee_name: str = "", leave_id: int = 0,
                       idempotency_key: str = "") -> dict:
        """Approve a pending leave request. This calls hr.leave's own
        action_approve(), so Odoo's normal HR-manager permission check
        applies exactly as it would in the web client - if the current
        user is not authorized to approve leave, this returns an
        access-denied error instead of approving anything, no matter
        what the assistant's own reasoning concluded. A manager can
        never approve their own leave request through this tool, even
        if they technically hold the approver permission.

        Parameters:
            employee_name: Name (or partial name) of the employee whose
                request should be approved. Used if leave_id is not given.
            leave_id: Exact hr.leave record id, if already known.
            idempotency_key: Optional - pass the same value again on a
                retry of the exact same request to avoid double-approving.
        """
        return self._resolve_and_act_on_leave(
            employee_name, leave_id, "action_approve", "approve_leave",
            idempotency_key=idempotency_key,
        )

    @llm_tool(destructive_hint=True)
    def reject_leave(self, employee_name: str = "", leave_id: int = 0, reason: str = "",
                      idempotency_key: str = "") -> dict:
        """Reject/refuse a pending leave request. Same permission model
        as approve_leave: Odoo's own hr.leave access rules decide
        whether the current user may do this, and a manager can never
        reject their own request through this tool.

        Parameters:
            employee_name: Name (or partial name) of the employee.
            leave_id: Exact hr.leave record id, if already known.
            reason: Optional reason shown to the employee.
            idempotency_key: Optional - pass the same value again on a
                retry of the exact same request to avoid double-rejecting.
        """
        return self._resolve_and_act_on_leave(
            employee_name, leave_id, "action_refuse", "reject_leave",
            reason=reason, idempotency_key=idempotency_key,
        )

    def _resolve_and_act_on_leave(self, employee_name, leave_id, method_name, action_label,
                                   reason=None, idempotency_key=""):
        # Risk Engine defense-in-depth (roadmap #18/#20): records the
        # risk level into the audit trail and would block outright if
        # this were ever mis-registered at RISK_5. The real permission
        # logic for THIS tool is still the self-approval guard below -
        # this call does not replace it.
        self.env["ai.gateway.execution.gate"].authorize(action_label)

        cached = self.env["ai.gateway.idempotency"].get_cached(self.env.user.id, idempotency_key)
        if cached is not None:
            return cached

        payload = {"employee_name": employee_name, "leave_id": leave_id}
        if not employee_name and not leave_id:
            return {"error": "missing_required_field", "missing_fields": ["employee_name or leave_id"],
                    "hint": "از کاربر بپرس درخواست مرخصی کدوم کارمند."}

        domain = [("state", "in", ("confirm", "validate1"))]
        if leave_id:
            domain = [("id", "=", leave_id)]
        elif employee_name:
            domain.append(("employee_id.name", "ilike", employee_name))

        leave = self.env["hr.leave"].search(domain, limit=1)
        if not leave:
            _audit(self.env, action_label, payload, success=False, error_message="not_found")
            return {"error": f"هیچ درخواست مرخصی در انتظار تاییدی برای '{employee_name or leave_id}' پیدا نشد."}

        # SELF-APPROVAL GUARD: even if Odoo's ACL would technically let
        # this user call action_approve/action_refuse (e.g. they hold
        # the HR Manager group), a manager must never be able to
        # approve/reject their OWN request through this tool. This is a
        # policy check ACL alone cannot express, so it is enforced here
        # in code, before the actual Odoo method is ever called.
        if leave.employee_id.user_id and leave.employee_id.user_id.id == self.env.user.id:
            _audit(self.env, action_label, payload, success=False, error_message="self_approval_blocked")
            return {"error": "access_denied: شما نمی‌توانید درخواست مرخصی خودتان را تایید یا رد کنید."}

        idem_rec = None
        if idempotency_key:
            idem_rec, owner = self.env["ai.gateway.idempotency"].sudo().claim(self.env.user.id, idempotency_key, action_label)
            if not owner:
                if idem_rec.status == "completed":
                    return self.env["ai.gateway.idempotency"].get_cached(self.env.user.id, idempotency_key)
                return {"error": "idempotency_in_progress", "message": "همین عملیات در درخواست دیگری در حال اجراست."}
        try:
            if reason and hasattr(leave, "message_post"):
                leave.message_post(body=reason)
            getattr(leave, method_name)()
            _audit(self.env, action_label, payload)
            result = {"status": "done", "leave_id": leave.id,
                      "employee": leave.employee_id.name, "state": leave.state,
                      # See the matching note on create_task in
                      # task_tools.py: without an explicit recipient here,
                      # ai_integration's notification subscriber for
                      # "leave.approved" has no user to resolve (its
                      # built-in fallback only matches event_type
                      # "leave.created", not "leave.approved") and would
                      # silently notify no one.
                      "notify_user_ids": (
                          [leave.employee_id.user_id.id]
                          if leave.employee_id.user_id else []
                      )}
            # Event Bus integration (roadmap #9/#10): approving leave must
            # publish a durable domain event so the Calendar, Notification
            # and Audit subscribers already registered for "leave.approved"
            # in ai_integration/data/core_event_subscribers.xml actually
            # fire. Calling action_approve() on hr.leave directly (per this
            # module's ORM-only convention) does not publish anything on
            # its own - this was a real integration gap: the subscribers
            # existed but nothing ever triggered them. Reject is
            # intentionally not published here; no subscriber currently
            # listens for a rejection event.
            if method_name == "action_approve" and "ai.control.event" in self.env:
                self.env["ai.control.event"].sudo().publish(
                    "leave.approved", aggregate=leave, payload=result,
                    user=self.env.user,
                )
            idem_rec.complete(result) if idem_rec else None
            return result
        except AccessError as exc:
            if idem_rec: idem_rec.fail(exc)
            _audit(self.env, action_label, payload, success=False, error_message=str(exc))
            return {"error": "access_denied"}
        except UserError as exc:
            if idem_rec: idem_rec.fail(exc)
            _audit(self.env, action_label, payload, success=False, error_message=str(exc))
            return {"error": str(exc)}

    @llm_tool(read_only_hint=True)
    def list_pending_leaves(self) -> dict:
        """List leave requests currently awaiting approval, limited to
        whatever hr.leave records Odoo's own record rules let the
        current user see (a regular employee sees none here; a
        manager/HR officer sees their team's requests)."""
        leaves = self.env["hr.leave"].search([("state", "in", ("confirm", "validate1"))])
        return {"count": len(leaves), "pending": [
            {"id": l.id, "employee": l.employee_id.name,
             "date_from": str(l.date_from), "date_to": str(l.date_to), "state": l.state}
            for l in leaves
        ]}
