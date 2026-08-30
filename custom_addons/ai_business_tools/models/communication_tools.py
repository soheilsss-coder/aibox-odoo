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


class LLMToolCommunication(models.Model):
    _inherit = "llm.tool"

    @llm_tool(destructive_hint=True)
    def send_personal_message(self, recipient_name: str = "",
                              recipient_email: str = "",
                              employee_code: str = "",
                              subject: str = "", message_body: str = "",
                              idempotency_key: str = "") -> dict:
        """Send a personal message to one colleague through Odoo's own
        messenger (Discuss). Exactly one of recipient_name,
        recipient_email or employee_code identifies the person, and
        message_body is REQUIRED - if any of them is missing from what
        the user said, do NOT invent a value and do NOT call this tool
        yet; ask for the missing field(s) first.

        No separate notification code is needed: Odoo's native message
        on the recipient's partner record delivers the notification to
        their Discuss inbox, and the author is recorded as the current
        user.

        Parameters:
            recipient_name: Name (or partial name) of the recipient.
            recipient_email: Alternative - the recipient's work email.
            employee_code: Alternative - the recipient's employee code.
            subject: Optional short subject line.
            message_body: The message itself, REQUIRED.
            idempotency_key: Optional - reuse on retries of the same
                request to avoid sending a duplicate message.
        """
        self.env["ai.gateway.execution.gate"].authorize("send_personal_message")

        cached = self.env["ai.gateway.idempotency"].get_cached(self.env.user.id, idempotency_key)
        if cached is not None:
            return cached

        missing = []
        if not message_body:
            missing.append("message_body")
        if not (recipient_name or recipient_email or employee_code):
            missing.append("recipient (نام/ایمیل/کد کارمند)")
        if missing:
            return {"error": "missing_required_field", "missing_fields": missing,
                    "hint": "دقیقاً همین فیلد(های) گم‌شده را از کاربر بپرس، بقیه‌ی اطلاعات را دوباره نپرس."}

        payload = {"recipient_name": recipient_name, "recipient_email": recipient_email,
                   "employee_code": employee_code, "subject": subject, "message_body": message_body}

        recipient, err = self._resolve_assignee_user(recipient_name, recipient_email, employee_code)
        if err:
            _audit(self.env, "send_personal_message", payload, success=False, error_message=err[0])
            return {"error": err[0], "message": err[1], "candidates": err[2] or []}
        if not recipient:
            _audit(self.env, "send_personal_message", payload, success=False, error_message="recipient_not_found")
            return {"error": "recipient_not_found",
                    "message": "هیچ کاربر/کارمند فعالی با این مشخصات پیدا نشد."}

        partner = recipient.partner_id
        if not partner or not recipient.has_group("base.group_user"):
            _audit(self.env, "send_personal_message", payload, success=False, error_message="recipient_inactive")
            return {"error": "recipient_inactive",
                    "message": "این کاربر حذف‌شده یا غیرفعال است و نمی‌تواند پیام دریافت کند."}

        idem_rec = None
        if idempotency_key:
            idem_rec, owner = self.env["ai.gateway.idempotency"].sudo().claim(
                self.env.user.id, idempotency_key, "send_personal_message")
            if not owner:
                if idem_rec.status == "completed":
                    return self.env["ai.gateway.idempotency"].get_cached(self.env.user.id, idempotency_key)
                return {"error": "idempotency_in_progress",
                        "message": "همین عملیات در درخواست دیگری در حال اجراست."}
        try:
            # Native Odoo messenger: posting on the recipient's partner record
            # puts the message in their Discuss inbox and records the sender.
            msg = partner.message_post(
                subject=subject or "",
                body=message_body,
                author_id=self.env.user.partner_id.id,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
        except (AccessError, UserError) as exc:
            if idem_rec:
                idem_rec.fail(exc)
            _audit(self.env, "send_personal_message", payload, success=False, error_message=str(exc))
            return {"error": "access_denied", "message": "ارسال پیام مجاز نیست."}

        result = {"status": "sent", "message_id": msg.id, "recipient": recipient.name,
                  "sender": self.env.user.name}
        if idem_rec:
            idem_rec.complete(result)
        _audit(self.env, "send_personal_message", payload)
        return result