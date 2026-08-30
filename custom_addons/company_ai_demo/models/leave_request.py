import logging

from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool

_logger = logging.getLogger(__name__)


class LLMToolLeaveRequest(models.Model):
    """Self-service leave request - distinct from generate_hr_decree.
    An employee (any role) can request time off for THEMSELVES only;
    it goes into Odoo's normal approval flow (their manager sees it in
    Odoo's own Time Off app and gets Odoo's own built-in notification -
    no custom notification system needed, this reuses what Odoo
    already does). This tool never approves anything by itself.
    """

    _inherit = "llm.tool"

    @llm_tool(destructive_hint=True)
    def create_leave_request(
        self,
        date_from: str,
        date_to: str,
        reason: str = "",
        idempotency_key: str = "",
    ) -> dict:
        """Create a time-off (leave) request for the CURRENTLY LOGGED IN
        user only - not for anyone else. This just submits a request;
        it does not approve it. The employee's manager will see it in
        their own Time Off approvals automatically via Odoo's existing
        workflow. If the user asks to request leave for someone else,
        do NOT use this tool - only use it for the current user's own
        request (use generate_hr_decree or the generic tools if a
        manager is explicitly approving/creating leave for a
        subordinate instead).

        If date_from or date_to is missing or ambiguous, ASK THE USER
        for the missing date before calling this tool - do not guess a
        date for a leave request.

        Parameters:
            date_from: Start date, format YYYY-MM-DD.
            date_to: End date, format YYYY-MM-DD.
            reason: Optional short reason/note for the request.
            idempotency_key: Optional - pass the same value again on a
                retry of the exact same request to avoid submitting the
                same leave request twice.
        """
        if "ai.gateway.tool.risk" in self.env:
            self.env["ai.gateway.execution.gate"].authorize("create_leave_request")
        if date_from > date_to:
            return {"error": "invalid_date_range", "message": "تاریخ شروع نباید بعد از تاریخ پایان باشد."}
        cached = None
        if "ai.gateway.idempotency" in self.env:
            cached = self.env["ai.gateway.idempotency"].get_cached(self.env.user.id, idempotency_key)
        if cached is not None:
            return cached

        employee = self.env["hr.employee"].search(
            [("user_id", "=", self.env.user.id)], limit=1
        )
        if not employee:
            return {
                "error": "No employee record linked to your user account - "
                         "ask an administrator to link one."
            }

        leave_type = self.env["hr.leave.type"].search(
            [("requires_allocation", "=", "no")], limit=1
        )
        if not leave_type:
            leave_type = self.env["hr.leave.type"].search([], limit=1)
        if not leave_type:
            return {"error": "No leave type configured in the system."}

        idem_rec = None
        if idempotency_key and "ai.gateway.idempotency" in self.env:
            idem_rec, owner = self.env["ai.gateway.idempotency"].sudo().claim(self.env.user.id, idempotency_key, "create_leave_request")
            if not owner:
                if idem_rec.status == "completed":
                    return self.env["ai.gateway.idempotency"].get_cached(self.env.user.id, idempotency_key)
                return {"error": "idempotency_in_progress", "message": "همین عملیات در درخواست دیگری در حال اجراست."}
        try:
            leave = self.env["hr.leave"].create({
                "employee_id": employee.id,
                "holiday_status_id": leave_type.id,
                "date_from": f"{date_from} 08:00:00",
                "date_to": f"{date_to} 18:00:00",
                "name": reason or "درخواست مرخصی",
            })
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Leave request creation failed: %s", exc)
            if idem_rec: idem_rec.fail(exc)
            return {"error": "Could not create leave request, check server logs for details"}

        result = {
            "status": "submitted_for_approval",
            "leave_id": leave.id,
            "employee": employee.name,
            "date_from": date_from,
            "date_to": date_to,
            "note": "Your manager will see this in their Time Off approvals.",
        }
        if "ai.gateway.idempotency" in self.env:
            idem_rec.complete(result) if idem_rec else None
        if "ai.control.event" in self.env:
            self.env["ai.control.event"].publish("leave.created", aggregate=leave, payload=result)
        return result
