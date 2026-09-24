import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.llm_tool.decorators import llm_tool

_logger = logging.getLogger(__name__)


def _audit(env, action, payload, success=True, error_message=None):
    env["ai.gateway.audit.log"].sudo().log(
        user_id=env.user.id, source="tool", action=action,
        payload=payload, success=success, error_message=error_message,
    )


class AiScheduleRule(models.Model):
    """A user-owned recurring assistant job. The rule owns a real
    ir.cron (created/updated here, never hand-edited), so scheduling is
    Odoo-native: the interval fields, the cron user and the worker
    pipeline all come from Odoo. Each run executes the stored prompt
    exactly like a chat turn, and the result is posted on the rule's
    own mail thread to the notify_user_ids followers."""
    _name = "ai.schedule.rule"
    _description = "Scheduled AI Command"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(string="Name", required=True)
    prompt_text = fields.Text(
        string="Prompt", required=True,
        help="Stored instruction executed each run by the assistant.")
    interval_type = fields.Selection(
        [("minutes", "Minutes"), ("hours", "Hours"),
         ("days", "Days"), ("weeks", "Weeks"), ("months", "Months")],
        string="Repeat every", required=True, default="days")
    interval_number = fields.Integer(string="Interval", required=True, default=1)
    user_id = fields.Many2one("res.users", string="Owner", required=True,
                              default=lambda self: self.env.user)
    cron_id = fields.Many2one("ir.cron", string="Cron", readonly=True, ondelete="set null")
    notify_user_ids = fields.Many2many("res.users", string="Notify on result")
    state = fields.Selection([("pending", "Pending"), ("ok", "Last run OK"),
                              ("error", "Last run failed")],
                             string="State", default="pending", readonly=True)
    last_run_datetime = fields.Datetime(string="Last run", readonly=True)
    last_result = fields.Text(string="Last result", readonly=True)
    last_error = fields.Text(string="Last error", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        for rule in rules:
            rule._ensure_cron()
        return rules

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in
               ("name", "interval_type", "interval_number", "user_id", "active")):
            for rule in self:
                if rule.cron_id:
                    rule._ensure_cron()
        return res

    def _ensure_cron(self):
        """Create or reschedule the backing ir.cron. Uses the plain
        model/function/args contract (state=code) the same way the
        module's own cron_data.xml does, with the rule id baked into
        the code so each rule maps to exactly one scheduled job."""
        self.ensure_one()
        model = self.env["ir.model"]._get(self._name)
        vals = {
            "name": "AI: scheduled command - %s" % self.name,
            "model_id": model.id,
            "state": "code",
            "code": "model._cron_run_selected(%d)" % self.id,
            "interval_number": max(1, int(self.interval_number or 1)),
            "interval_type": self.interval_type,
            "user_id": self.user_id.id,
            "active": bool(self.active),
        }
        if self.cron_id:
            self.cron_id.write(vals)
        else:
            self.cron_id = self.env["ir.cron"].create(vals)
        return self.cron_id

    def _cron_run_selected(self, rule_id):
        """Invoked by the per-rule ir.cron. Runs the stored prompt as an
        assistant turn in the rule OWNER's real environment (single
        pipeline, thread ownership and tool allowlist identical to web
        chat), stores the outcome and posts it to the followers."""
        rule = self.browse(int(rule_id)).exists()
        if not rule or not rule.active:
            return False
        owner_env = self.env(user=rule.user_id.id)
        # Same env-based chat core the /api/chat and Telegram paths use.
        from custom_addons.ai_gateway.controllers.gateway import _run_chat_env  # noqa: PLC0415,E402
        result = _run_chat_env(owner_env, rule.prompt_text)
        ok = "error" not in result
        rule.sudo().write({
            "last_run_datetime": fields.Datetime.now(),
            "state": "ok" if ok else "error",
            "last_result": (result.get("reply") or "")[:20000],
            "last_error": result.get("error") if not ok else False,
        })
        followers = rule.notify_user_ids.partner_id
        if followers:
            rule.sudo().message_subscribe(partner_ids=followers.ids)
        body = result.get("reply") or result.get("error") or "no output"
        rule.sudo().message_post(
            subject="Scheduled command '%s' %s" % (rule.name, "succeeded" if ok else "failed"),
            body=body,
            subtype_xmlid="mail.mt_comment",
        )
        return ok

    def action_disable(self):
        for rule in self:
            rule.write({"active": False})


class LLMToolScheduled(models.Model):
    _inherit = "llm.tool"

    @llm_tool(destructive_hint=True)
    def create_scheduled_command(self, name: str = "", prompt_text: str = "",
                                 interval_number: int = 1,
                                 interval_type: str = "days",
                                 notify_names: str = "",
                                 idempotency_key: str = "") -> dict:
        """Create a recurring automation rule that runs a stored
        instruction at a fixed interval through Odoo's native ir.cron
        scheduler. name, prompt_text and interval_type are REQUIRED -
        if any is missing from what the user said, do NOT invent a
        value; ask for the missing field(s) first.

        Every run executes the exact text of prompt_text as a fresh
        assistant turn (same pipeline, thread ownership and tool
        allowlist as chat), so the job can call whatever business tools
        the owner is allowed to - e.g. "گزارش حقوق این ماه را بساز"
        becomes a real monthly job. The result is stored on the rule
        and notified to the listed people.

        Parameters:
            name: Short name for the automation (shown on the
                management list too).
            prompt_text: The stored instruction executed each run.
            interval_number: Every N interval_type, default 1.
            interval_type: One of minutes, hours, days, weeks, months.
            notify_names: Optional comma-separated names/emails/employee
                codes of people to notify with the result.
            idempotency_key: Optional - reuse on retries to avoid
                creating the same automation twice.
        """
        self.env["ai.gateway.execution.gate"].authorize("create_scheduled_command")

        cached = self.env["ai.gateway.idempotency"].get_cached(self.env.user.id, idempotency_key)
        if cached is not None:
            return cached

        missing = [k for k, v in (("name", name), ("prompt_text", prompt_text),
                                  ("interval_type", interval_type)) if not v]
        if missing:
            return {"error": "missing_required_field", "missing_fields": missing,
                    "hint": "دقیقاً همین فیلد(های) گم‌شده را از کاربر بپرس، بقیه‌ی اطلاعات را دوباره نپرس."}

        payload = {"name": name, "prompt_text": prompt_text,
                   "interval_number": interval_number, "interval_type": interval_type,
                   "notify_names": notify_names}

        notify_user_ids = []
        for token in [p.strip() for p in notify_names.split(",") if p.strip()]:
            user, err = self._resolve_assignee_user(token)
            if err:
                _audit(self.env, "create_scheduled_command", payload, success=False, error_message=err[0])
                return {"error": err[0], "message": err[1], "candidates": err[2] or []}
            if user:
                notify_user_ids.append(user.id)

        try:
            rule = self.env["ai.schedule.rule"].create({
                "name": name,
                "prompt_text": prompt_text,
                "interval_number": max(1, int(interval_number or 1)),
                "interval_type": interval_type,
                "user_id": self.env.user.id,
                "notify_user_ids": [(6, 0, notify_user_ids)],
            })
        except (AccessError, UserError) as exc:
            _audit(self.env, "create_scheduled_command", payload, success=False, error_message=str(exc))
            return {"error": "access_denied", "message": "ایجاد اتوماسیون زمان‌بندی مجاز نیست."}

        _audit(self.env, "create_scheduled_command", payload)
        return {"status": "created", "rule_id": rule.id, "name": rule.name,
                "cron_id": rule.cron_id.id,
                "next_run": str(rule.cron_id.nextcall) if rule.cron_id else None,
                "repeat": "%s %s" % (rule.interval_number, rule.interval_type),
                "notified_users": rule.notify_user_ids.mapped("name")}