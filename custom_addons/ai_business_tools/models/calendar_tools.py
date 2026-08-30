import logging

from odoo import models
from odoo.exceptions import AccessError, UserError
from odoo.addons.llm_tool.decorators import llm_tool

_logger = logging.getLogger(__name__)


def _audit(env, action, payload, success=True, error_message=None):
    env["ai.gateway.audit.log"].sudo().log(
        user_id=env.user.id, source="tool", action=action,
        payload=payload, success=success, error_message=error_message,
    )


class LLMToolCalendar(models.Model):
    _inherit = "llm.tool"

    @llm_tool(destructive_hint=True)
    def schedule_meeting(self, title: str = "", start: str = "",
                         duration_hours: float = 1.0,
                         participants: str = "", notes: str = "") -> dict:
        """Schedule a meeting in Odoo's native calendar. title, start
        and at least one participant are REQUIRED - if any of them is
        missing from what the user said, do NOT invent a value and do
        NOT call this tool yet. Ask the user for exactly the missing
        field(s) first.

        On success a real calendar.event is created with the provided
        participants as attendees, so the event shows on everyone's
        calendar and Odoo sends the native invitations - no separate
        notification code is needed here.

        Parameters:
            title: Meeting subject.
            start: Start date/time, format 'YYYY-MM-DD HH:MM:SS'
                (24-hour). If the user says a plain date without a time,
                use '09:00:00' as a sensible default.
            duration_hours: Meeting length in hours, default 1.0.
            participants: Comma-separated names (or emails or employee
                codes) of the people who should attend.
            notes: Optional agenda / summary text.
        """
        self.env["ai.gateway.execution.gate"].authorize("schedule_meeting")

        missing = []
        if not title:
            missing.append("title")
        if not start:
            missing.append("start")
        if not participants:
            missing.append("participants")
        if missing:
            return {"error": "missing_required_field", "missing_fields": missing,
                    "hint": "دقیقاً همین فیلد(های) گم‌شده را از کاربر بپرس، بقیه‌ی اطلاعات را دوباره نپرس."}

        payload = {"title": title, "start": start, "duration_hours": duration_hours,
                   "participants": participants, "notes": notes}

        partner_ids = []
        unresolved = []
        for token in [p.strip() for p in participants.split(",") if p.strip()]:
            user, err = self._resolve_assignee_user(token)
            if err:
                _audit(self.env, "schedule_meeting", payload, success=False, error_message=err[0])
                return {"error": err[0], "message": err[1], "candidates": err[2] or []}
            if not user:
                unresolved.append(token)
            elif user.partner_id:
                partner_ids.append(user.partner_id.id)
        if unresolved:
            _audit(self.env, "schedule_meeting", payload, success=False, error_message="participant_not_found")
            return {"error": "participant_not_found",
                    "message": "برای مشارکت‌کنندگان زیر کاربر فعالی پیدا نشد: %s" % "، ".join(unresolved)}
        if not partner_ids:
            return {"error": "no_attendee", "message": "هیچ شرکت‌کننده‌ی قابل استفاده‌ای مشخص نشد."}

        if self.env.user.partner_id.id not in partner_ids:
            partner_ids.append(self.env.user.partner_id.id)

        from datetime import datetime, timedelta
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            try:
                start_dt = datetime.strptime("%s 09:00:00" % start, "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                _audit(self.env, "schedule_meeting", payload, success=False, error_message="invalid_start")
                return {"error": "invalid_start",
                        "message": "زمان شروع قابل فهم نبود؛ قالب درست: '2026-03-05 14:30:00'."}
        stop_dt = start_dt + timedelta(hours=float(duration_hours or 1.0))
        rec = None
        try:
            rec = self.env["calendar.event"].create({
                "name": title,
                "start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "stop": stop_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "allday": False,
                "description": notes or "",
                "user_id": self.env.user.partner_id.id,
                "partner_ids": [(6, 0, partner_ids)],
            })
        except (AccessError, UserError) as exc:
            _audit(self.env, "schedule_meeting", payload, success=False, error_message=str(exc))
            return {"error": "access_denied", "message": "ایجاد رویداد تقویم مجاز نیست."}

        _audit(self.env, "schedule_meeting", payload)
        return {"status": "scheduled", "event_id": rec.id, "title": title,
                "start": rec.start, "stop": rec.stop,
                "attendees": self.env["res.partner"].browse(partner_ids).mapped("name")}