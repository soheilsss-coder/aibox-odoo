from datetime import date, datetime, time, timedelta

from odoo import fields, models
from odoo.addons.llm_tool.decorators import llm_tool


class LLMToolMyAttendance(models.Model):
    _inherit = "llm.tool"

    # Roadmap item #9 (Business Tools, remaining item): "list_my_tasks,
    # get_my_attendance_summary, و هر فرآیند دیگری که در طول استفاده‌ی
    # واقعی معلوم شود لازم است". This is the personal counterpart to
    # get_attendance_report (company_ai_demo/models/hr_decree.py),
    # which is org-wide and really meant for HR/managers. This one is
    # hard-scoped to self.env.user's own hr.employee record only, so
    # it is safe for ANY employee to call - no ir.rule/ACL question to
    # get right, because it never reads anyone else's attendance.
    @llm_tool(read_only_hint=True)
    def get_my_attendance_summary(self, days: int = 7) -> dict:
        """Get the CURRENT user's own attendance for the last N days -
        check-in/check-out times and total worked hours per day. Only
        ever returns the caller's own records, never a co-worker's -
        for that, an HR/manager role should use get_attendance_report
        instead.

        Parameters:
            days: How many days back to include, counting today.
                Defaults to 7. Capped at 31 to keep the response small.
        """
        employee = self.env.user.employee_id
        if not employee:
            return {"error": "no_employee_record",
                    "hint": "کاربر فعلی به هیچ hr.employee متصل نیست."}

        days = max(1, min(days, 31))
        period_start = datetime.combine(date.today() - timedelta(days=days - 1), time.min)

        attendances = self.env["hr.attendance"].search([
            ("employee_id", "=", employee.id),
            ("check_in", ">=", period_start),
        ], order="check_in desc")

        by_day = {}
        for att in attendances:
            day_key = str(fields.Datetime.context_timestamp(self, att.check_in).date())
            entry = by_day.setdefault(day_key, {"date": day_key, "sessions": [], "hours": 0.0})
            entry["sessions"].append({
                "check_in": str(att.check_in),
                "check_out": str(att.check_out) if att.check_out else None,
            })
            entry["hours"] += att.worked_hours or 0.0

        days_list = sorted(by_day.values(), key=lambda d: d["date"], reverse=True)
        total_hours = sum(d["hours"] for d in days_list)

        return {
            "employee": employee.name,
            "period_days": days,
            "total_hours": round(total_hours, 2),
            "days": [{**d, "hours": round(d["hours"], 2)} for d in days_list],
        }
