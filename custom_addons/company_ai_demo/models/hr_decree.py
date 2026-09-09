import logging
from datetime import date, datetime, time

from odoo import fields, models
from odoo.addons.llm_tool.decorators import llm_tool

_logger = logging.getLogger(__name__)


class HrDecree(models.Model):
    _name = "hr.decree"
    _description = "AI-Generated HR Decree"
    _order = "create_date desc"

    employee_id = fields.Many2one("hr.employee", required=True, string="Employee")
    decree_type = fields.Selection(
        [("raise", "Salary Raise"), ("promotion", "Promotion"),
         ("warning", "Warning"), ("other", "Other")],
        default="other", string="Type",
    )
    body = fields.Text(string="Decree Text", required=True)
    state = fields.Selection(
        [("pending_approval", "Pending Approval"), ("draft", "Draft"),
         ("sent_for_signature", "Sent for Signature"), ("signed", "Signed")],
        default="pending_approval",
    )
    # Kept as a plain Integer, NOT Many2one("sign.request", ...): the
    # Sign app is optional (may not be installed on a Community-only,
    # bare-metal setup), and a Many2one to an uninstalled comodel makes
    # Odoo fail at module load time - defeating the whole point of the
    # "if 'sign.request' in self.env" fallback below. Look the record
    # up manually with self.env["sign.request"].browse(id) when needed.
    sign_request_id = fields.Integer(string="Signature Request ID")
    created_by_ai = fields.Boolean(default=True)

    def action_mark_approved(self):
        """Called ONLY by ai.gateway.approval._apply_approved_action()
        after a human (not the requester) has approved the pending
        ai.gateway.approval record - never called directly from the
        AI tool. This is the actual moment the decree becomes real
        (routed to Sign, or a to-do created for the manager)."""
        self.ensure_one()
        self.write({"state": "draft"})
        if "sign.request" in self.env:
            try:
                sign_request = self.env["llm.tool"]._create_sign_request_for_decree(self, self.employee_id)
                self.write({"sign_request_id": sign_request.id, "state": "sent_for_signature"})
                return
            except Exception:  # noqa: BLE001
                pass
        if self.employee_id.parent_id.user_id:
            self.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=f"Please review & sign approved decree for {self.employee_id.name}",
                user_id=self.employee_id.parent_id.user_id.id,
            )


class LLMToolHrDecree(models.Model):
    _inherit = "llm.tool"

    @llm_tool(read_only_hint=True)
    def get_attendance_report(self, target_date: str = "") -> dict:
        """Attendance is hierarchical: employee=own, manager=team,
        HR/security=department/company, executive=company. Never expose
        the entire workforce to an ordinary employee."""
        day = fields.Date.from_string(target_date) if target_date else date.today()
        day_start = datetime.combine(day, time.min); day_end = datetime.combine(day, time.max)
        user = self.env.user
        employee = self.env["hr.employee"].search([("user_id", "=", user.id)], limit=1)
        is_exec = any(user.has_group(x) for x in ("ai_business_tools.role_executive", "ai_business_tools.role_system_admin", "ai_business_tools.role_security"))
        is_hr = user.has_group("hr.group_hr_user") or user.has_group("hr.group_hr_manager")
        is_manager = user.has_group("ai_business_tools.role_manager") or user.has_group("ai_business_tools.role_hr_manager")
        if "ai.control.authorization" in self.env and not (is_hr or is_manager or is_exec):
            # ordinary employee: only own attendance
            if not employee:
                return {"error": "access_denied: attendance is restricted"}
        Attendance = self.env["hr.attendance"]
        domain=[("check_in", ">=", day_start), ("check_in", "<=", day_end)]
        if is_exec or is_hr:
            if is_hr and not is_exec and employee and employee.department_id:
                domain.append(("employee_id.department_id", "=", employee.department_id.id))
        elif is_manager and employee:
            domain.append(("employee_id.parent_id", "=", employee.id))
        elif employee:
            domain.append(("employee_id", "=", employee.id))
        else:
            return {"error": "access_denied: attendance is restricted"}
        attendances=Attendance.search(domain)
        present=[{"employee":a.employee_id.name,"check_in":str(a.check_in),"check_out":str(a.check_out) if a.check_out else None} for a in attendances]
        late=[x for x in present if x["check_in"] and x["check_in"][11:13].isdigit() and int(x["check_in"][11:13])>=9]
        return {"date":str(day),"present_count":len(present),"late_count":len(late),"present":present,"late":late}

    @llm_tool(destructive_hint=True)
    def generate_hr_decree(self, employee_name: str, decree_type: str, decree_text: str) -> dict:
        """Draft an HR decree (raise/promotion/warning/other) for an
        employee - this is HIGH RISK (it can affect someone's pay or
        employment status), so it does NOT take effect by itself. It
        only creates a pending approval request for a human HR Manager
        to review; nothing is sent for signature or acted on until that
        human explicitly approves it in Odoo (Settings > AI Approvals).
        The person who asked for this decree can never approve their
        own request, even if they are themselves an HR Manager.

        Parameters:
            employee_name: Full or partial name of the employee.
            decree_type: One of raise, promotion, warning, other.
            decree_text: Full text of the decree.
        """
        # Risk Engine defense-in-depth (roadmap #18/#20) - soft-checked
        # since company_ai_demo does not hard-depend on ai_business_tools.
        # Same as elsewhere: this does NOT replace the approval-object
        # flow below, it's a generic net that also stamps risk_level
        # into the audit trail.
        if "ai.gateway.tool.risk" in self.env:
            risk = self.env["ai.gateway.tool.risk"].sudo().search([("tool_name", "=", "generate_hr_decree")], limit=1)
            if risk and int(risk.risk_level or 0) >= 5:
                return {"error": "access_denied: RISK_5 tools are human-only"}

        employee = self.env["hr.employee"].search(
            [("name", "ilike", employee_name)], limit=1
        )
        if not employee:
            return {"error": f"No employee found matching '{employee_name}'"}

        hr_manager_group = self.env.ref("hr.group_hr_manager", raise_if_not_found=False)
        if not hr_manager_group:
            return {"error": "hr.group_hr_manager not found - is the hr module installed?"}

        approver_group = hr_manager_group
        if "ai.gateway.approval.matrix" in self.env:
            matrix_group = self.env["ai.gateway.approval.matrix"].get_approver_group("hr_decree")
            if matrix_group:
                approver_group = matrix_group

        decree = self.env["hr.decree"].create({
            "employee_id": employee.id,
            "decree_type": decree_type if decree_type in ("raise", "promotion", "warning", "other") else "other",
            "body": decree_text,
            "state": "pending_approval",
        })
        approval = self.env["ai.gateway.approval"].sudo().create({
            "name": f"HR Decree ({decree_type}) for {employee.name}",
            "requested_by_id": self.env.user.id,
            "approver_group_id": approver_group.id,
            "action_model": "hr.decree",
            "action_res_id": decree.id,
        })
        self.env["ai.gateway.audit.log"].sudo().log(
            user_id=self.env.user.id, source="tool", action="generate_hr_decree",
            payload={"employee": employee.name, "decree_type": decree_type},
        )
        return {"status": "pending_approval", "decree_id": decree.id,
                "approval_id": approval.id, "employee": employee.name,
                "note": "این حکم موقتاً ذخیره شد ولی تا زمانی که یک مدیر منابع انسانی دیگر "
                        "(نه خودتان) آن را در Odoo تایید نکند، هیچ اثری ندارد."}

    def _create_sign_request_for_decree(self, decree, employee):
        SignRequest = self.env["sign.request"]
        template = self.env["sign.template"].search([], limit=1)
        if not template:
            raise ValueError("No sign.template found - upload a decree template first")
        signer_vals = [(0, 0, {"partner_id": employee.user_id.partner_id.id})]
        if employee.parent_id.user_id:
            signer_vals.append((0, 0, {"partner_id": employee.parent_id.user_id.partner_id.id}))
        return SignRequest.create({
            "template_id": template.id, "reference": f"Decree - {employee.name}",
            "request_item_ids": signer_vals,
        })
