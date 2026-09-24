import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProjectTaskAutomation(models.Model):
    """Roadmap فاز ۵ (اتوماسیون), items #30 (Events), #32 (Task System -
    dependency) and #35 (Escalation) - all three layered directly onto
    the existing `project.task` model instead of a separate
    Workflow/Event-broker engine, exactly per the roadmap's own
    guidance for items #29/#30: Odoo's native `state`/`stage_id` +
    `bus.bus` + `ir.cron` is enough, no Temporal/Kafka/RabbitMQ needed.

    Item #29 (Workflow) itself needed no code - see Scenario 19 in
    05_acceptance_tests.py, which verifies (rather than assumes) that
    an hr.leave state change already produces a notification via
    Odoo's own mail-thread/activity machinery.
    """

    _inherit = "project.task"

    # ------------------------------------------------------------------
    # Roadmap #32 (Task System, remaining item): dependency between
    # tasks - "task B only after task A is done".
    # ------------------------------------------------------------------
    depends_on_task_ids = fields.Many2many(
        "project.task", "project_task_dependency_rel", "task_id", "depends_on_id",
        string="وابسته به این تسک‌ها",
        help="این تسک تا وقتی همه‌ی این تسک‌ها به یک stage بسته منتقل نشدن، "
             "قابل بستن نیست.",
    )
    blocking_task_ids = fields.Many2many(
        "project.task", "project_task_dependency_rel", "depends_on_id", "task_id",
        string="تسک‌هایی که به این تسک وابسته‌اند", copy=False,
        help="تسک‌های دیگری که این تسک را به‌عنوان پیش‌نیاز خودشون علامت زدن. "
             "این طرفِ رابطه از سمت خودِ آن تسک‌ها مدیریت می‌شود.",
    )

    # ------------------------------------------------------------------
    # Roadmap #35 (Escalation): 0 = no escalation yet (just the
    # assignee, handled by the pre-existing cron_notify_overdue_tasks),
    # 1 = direct manager, 2 = department manager, 3 = Executive/CEO.
    # ------------------------------------------------------------------
    escalation_level = fields.Integer(
        default=0, copy=False, tracking=True,
        help="۰=بدون تشدید، ۱=مدیر مستقیم، ۲=مدیر بخش، ۳=Executive/مدیرعامل. "
             "با اجرای هر بار cron_escalate_overdue_tasks به‌روزرسانی می‌شود.",
    )

    @api.constrains("depends_on_task_ids")
    def _check_no_self_dependency(self):
        # صادقانه: این فقط جلوی وابستگی مستقیم یک تسک به خودش را
        # می‌گیرد، نه چرخه‌های غیرمستقیم (A->B->A) - برای این حجم از
        # پروژه، تشخیص چرخه‌ی کامل ارزش پیچیدگی اضافه‌اش را نداشت؛ اگر
        # لازم شد، بعداً همین‌جا اضافه می‌شود.
        for task in self:
            if task in task.depends_on_task_ids:
                raise UserError("یک تسک نمی‌تواند به خودش وابسته باشد.")

    def _pending_dependencies(self):
        self.ensure_one()
        return self.depends_on_task_ids.filtered(lambda t: not t.stage_id.is_closed)

    # ------------------------------------------------------------------
    # Roadmap #30 (Events, simple): "which model change -> which
    # action" mapping. Flat dict on purpose - no separate event-broker
    # model, no pub/sub engine; write() override + bus.bus is the
    # whole implementation, as the roadmap item itself asks for.
    # ------------------------------------------------------------------
    _EVENT_ACTIONS = {
        "stage_id": "_on_stage_changed",
        "escalation_level": "_on_escalation_changed",
    }

    def write(self, vals):
        # --- dependency gate (roadmap #32) - checked BEFORE the write,
        # against the stage this write would move the task INTO. ---
        if "stage_id" in vals:
            new_stage = self.env["project.task.type"].browse(vals["stage_id"])
            if new_stage.is_closed:
                for task in self:
                    pending = task._pending_dependencies()
                    if pending:
                        raise UserError(
                            "تسک «%s» را نمی‌شود بست: به این تسک‌های هنوز بازِ دیگر "
                            "وابسته است: %s" % (task.name, "، ".join(pending.mapped("name")))
                        )

        tracked_fields = [f for f in self._EVENT_ACTIONS if f in vals]
        before = {t.id: {f: t[f] for f in tracked_fields} for t in self} if tracked_fields else {}

        result = super().write(vals)

        for task in self:
            for field_name in tracked_fields:
                old_value = before[task.id][field_name]
                new_value = task[field_name]
                changed = (
                    old_value.id != new_value.id if field_name == "stage_id"
                    else old_value != new_value
                )
                if changed:
                    task._dispatch_event(field_name, new_value)
        return result

    def _dispatch_event(self, field_name, new_value):
        handler_name = self._EVENT_ACTIONS.get(field_name)
        if handler_name:
            getattr(self, handler_name)(new_value)

    def _on_stage_changed(self, new_stage):
        self.ensure_one()
        # A closed task has nothing left to escalate - reset it so a
        # re-opened task later starts the escalation ladder from zero
        # again instead of immediately re-notifying the Executive.
        if new_stage.is_closed and self.escalation_level:
            self.escalation_level = 0
        self._push_bus_event("stage_changed", {"stage": new_stage.name})

    def _on_escalation_changed(self, new_level):
        self.ensure_one()
        self._push_bus_event("escalation_changed", {"escalation_level": new_level})

    def _push_bus_event(self, event_type, extra):
        """Publish a durable domain event; realtime consumers (Buzz/web),
        notifications, workflows and audit are subscribers of the central
        event bus instead of this business model talking to bus.bus directly."""
        self.ensure_one()
        payload = {
            "task_id": self.id,
            "task_name": self.name,
            "event": event_type,
            "notify_user_ids": self.user_ids.ids,
            **extra,
        }
        if "ai.control.event" in self.env:
            self.env["ai.control.event"].publish(
                f"task.{event_type}", aggregate=self, payload=payload, user=self.env.user
            )

    # ------------------------------------------------------------------
    # Roadmap #35 (Escalation): multi-step escalation chain.
    # ------------------------------------------------------------------
    def _escalation_target(self, level):
        """res.users to notify at a given escalation level, walking
        assignee -> direct manager -> department manager -> Executive,
        falling through to the next level up whenever a link is empty
        (e.g. no department manager set) instead of silently notifying
        no one."""
        self.ensure_one()
        assignees = self.user_ids
        if level <= 0:
            return assignees

        employees = assignees.mapped("employee_id")
        if level == 1:
            managers = employees.mapped("parent_id.user_id")
            return managers or self._escalation_target(2)
        if level == 2:
            dept_managers = employees.mapped("department_id.manager_id.user_id")
            return dept_managers or self._escalation_target(3)

        # level >= 3: everyone holding Role: Executive.
        return self.env["res.users"].sudo().search(
            [("groups_id", "=", self.env.ref("ai_business_tools.role_executive").id)]
        )

    _ESCALATION_LABELS = {1: "مدیر مستقیم", 2: "مدیر بخش", 3: "مدیرعامل / Executive"}

    def cron_escalate_overdue_tasks(self):
        """Scheduled job (data/cron_data.xml). Complements the
        pre-existing cron_notify_overdue_tasks (which reminds the
        assignee every day - level 0) by escalating to increasingly
        senior people the longer a task stays overdue: employee ->
        manager -> department manager -> Executive, exactly per
        roadmap #35's own example. Runs as the same restricted
        ai_automation_service_user as the other automation crons.
        """
        today = fields.Date.context_today(self)
        params = self.env["ir.config_parameter"].sudo()
        # Days-overdue -> escalation level thresholds, configurable per
        # deployment via System Parameters (like company_ai_demo's
        # vision_api_base) rather than hardcoded, since there is no
        # Setup Wizard yet (roadmap #46) for this.
        level_days = {
            1: int(params.get_param("ai_business_tools.escalation_level1_days", 3)),
            2: int(params.get_param("ai_business_tools.escalation_level2_days", 7)),
            3: int(params.get_param("ai_business_tools.escalation_level3_days", 14)),
        }

        overdue = self.env["project.task"].sudo().search([
            ("date_deadline", "<", today),
            ("stage_id.is_closed", "=", False),
        ])
        escalated = 0
        for task in overdue:
            days_late = (today - task.date_deadline).days
            target_level = 0
            for level in (3, 2, 1):
                if days_late >= level_days[level]:
                    target_level = level
                    break

            # Only act when we're moving to a NEW (higher) level - a
            # task already escalated to level 2 does not get re-pinged
            # at level 2 every single day, only when it climbs further.
            if target_level <= task.escalation_level:
                continue

            task.escalation_level = target_level  # triggers _on_escalation_changed via write()
            targets = task._escalation_target(target_level)
            label = self._ESCALATION_LABELS.get(target_level, "")
            for user in targets:
                task.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=f"🔺 تشدید تاخیر (سطح {target_level} - {label}): {task.name}",
                    note=(f"این تسک {days_late} روز از سررسیدش ({task.date_deadline}) گذشته و "
                          f"هنوز بسته نشده. مسئول اصلی: "
                          f"{', '.join(task.user_ids.mapped('name')) or 'نامشخص'}."),
                    user_id=user.id,
                )
            escalated += 1

        _logger.info("cron_escalate_overdue_tasks: escalated %s task(s)", escalated)
