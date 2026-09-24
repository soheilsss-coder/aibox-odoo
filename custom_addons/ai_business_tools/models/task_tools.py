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


class LLMToolTask(models.Model):
    _inherit = "llm.tool"

    def _resolve_assignee_user(self, name: str = "", email: str = "",
                               employee_code: str = ""):
        """Resolve a recipient to exactly one res.users record by
        (in priority order) employee code, work email, or name.
        Returns (user, error). Human-configurable "employee code" is
        mapped to the two employee identity fields Odoo ships:
        barcode (attendance badge) first, identification_id as a
        fallback. Never guesses on ambiguity - it reports the candidate
        names so the assistant can ask for more detail."""
        if employee_code:
            code = employee_code.strip()
            if "employee_code" in self.env["hr.employee"]._fields:
                employees = self.env["hr.employee"].search(
                    [("employee_code", "=", code)], limit=20)
            elif "barcode" in self.env["hr.employee"]._fields:
                employees = self.env["hr.employee"].search(
                    [("barcode", "=", code)], limit=20)
            else:
                employees = self.env["hr.employee"].search(
                    [("identification_id", "=", code)], limit=20)
            employees = employees.filtered("user_id")
            if len(employees) > 1:
                return (self.env["res.users"],
                        ("ambiguous_assignee", "چند کارمند با این کد پیدا شد؛ کد دقیق را وارد کنید.", employees.mapped("name")))
            return (employees[:1].user_id if employees else self.env["res.users"], None)

        if email:
            mail = email.strip().lower()
            users = self.env["res.users"].search([("email", "=ilike", mail)], limit=20)
            if len(users) > 1:
                return (self.env["res.users"],
                        ("ambiguous_assignee", "چند کاربر با این ایمیل پیدا شد.", users.mapped("name")))
            if not users:
                employees = self.env["hr.employee"].search(
                    [("work_email", "=ilike", mail)], limit=20).filtered("user_id")
                if len(employees) > 1:
                    return (self.env["res.users"],
                            ("ambiguous_assignee", "چند کارمند با این ایمیل پیدا شد.", employees.mapped("name")))
                users = employees[:1].user_id if employees else self.env["res.users"]
            return (users, None)

        if name:
            users = self.env["res.users"].search([("name", "ilike", name)], limit=20)
            if len(users) > 1:
                return (self.env["res.users"],
                        ("ambiguous_assignee", "چند کاربر با این نام پیدا شد؛ نام کامل، ایمیل یا کد کارمند را مشخص کنید.", users.mapped("name")))
            if not users:
                employees = self.env["hr.employee"].search(
                    [("name", "ilike", name)], limit=20).filtered("user_id")
                if len(employees) > 1:
                    return (self.env["res.users"],
                            ("ambiguous_assignee", "چند کارمند با این نام پیدا شد؛ نام کامل، ایمیل یا کد کارمند را مشخص کنید.", employees.mapped("name")))
                users = employees[:1].user_id if employees else self.env["res.users"]
            return (users, None)

        return (self.env["res.users"], ("missing_assignee", "فیلد گیرنده پر نشده است.", None))

    @llm_tool(destructive_hint=True)
    def create_task(self, title: str = "", assignee_name: str = "",
                     assignee_email: str = "", employee_code: str = "",
                     deadline: str = "", project_name: str = "",
                     description: str = "", depends_on_titles: str = "",
                     idempotency_key: str = "") -> dict:
        """Create a task and assign it to someone. Exactly one of
        assignee_name, assignee_email or employee_code is REQUIRED
        (they identify the same person - give priority to whatever the
        user actually said), and title + deadline are REQUIRED too. If
        any required field is missing from what the user said, do NOT
        invent a value and do NOT call this tool yet. Ask the user for
        exactly the missing field(s) first, then call this tool once
        you have them all.

        On success this creates the task, puts it on the assignee's
        calendar via an activity with the given due date, and Odoo's
        own notification system alerts the assignee - no separate
        notification code is needed here.

        Parameters:
            title: Short task title.
            assignee_name: Name (or partial name) of the person this
                task is for.
            assignee_email: Alternative - the person's work email.
                Used only if assignee_name is not given.
            employee_code: Alternative - the person's employee code
                (attendance badge / staff code). Used only if neither
                the name nor the email is given.
            deadline: Due date, YYYY-MM-DD.
            project_name: Optional project name; a default project is
                used if omitted or not found.
            description: Optional longer description.
            depends_on_titles: Optional - comma-separated titles of
                OTHER existing tasks that must be finished before this
                one can be closed (e.g. "Design mockup, Get sign-off").
                Only pass this if the user actually described a
                dependency; do not invent one. Titles that don't match
                any existing task are silently skipped and reported
                back in the result, not treated as an error.
            idempotency_key: Optional - pass the same value again on a
                retry of the exact same request to avoid creating the
                same task twice.
        """
        self.env["ai.gateway.execution.gate"].authorize("create_task")

        cached = self.env["ai.gateway.idempotency"].get_cached(self.env.user.id, idempotency_key)
        if cached is not None:
            return cached

        idem_rec = None

        missing = [n for n, v in (
            ("title", title), ("deadline", deadline)
        ) if not v]
        if not (assignee_name or assignee_email or employee_code):
            missing.append("assignee (نام/ایمیل/کد کارمند)")
        if missing:
            return {"error": "missing_required_field", "missing_fields": missing,
                    "hint": "دقیقاً همین فیلد(های) گم‌شده را از کاربر بپرس، بقیه‌ی اطلاعات را دوباره نپرس."}

        payload = {"title": title, "deadline": deadline,
                   "assignee_name": assignee_name, "assignee_email": assignee_email,
                   "employee_code": employee_code}

        assignee_user, err = self._resolve_assignee_user(assignee_name, assignee_email, employee_code)
        if err:
            _audit(self.env, "create_task", payload, success=False, error_message=err[0])
            return {"error": err[0], "message": err[1], "candidates": err[2] or []}
        if not assignee_user:
            _audit(self.env, "create_task", payload, success=False, error_message="assignee_not_found")
            return {"error": "assignee_not_found",
                    "message": f"هیچ کاربر/کارمند فعالی با این مشخصات پیدا نشد."}

        project = self.env["project.project"]
        if project_name:
            matches = project.search([("name", "ilike", project_name)], limit=20)
            if len(matches) > 1:
                return {"error": "ambiguous_project", "message": "چند پروژه پیدا شد؛ نام دقیق پروژه را مشخص کنید.", "candidates": matches.mapped("name")}
            project = matches[:1]
        if not project:
            project = project.search([("name", "=", "AI Tasks")], limit=1)
        if not project:
            try:
                project = project.create({"name": "AI Tasks"})
            except (AccessError, UserError) as exc:
                _audit(self.env, "create_task", payload, success=False, error_message=str(exc))
                return {"error": "access_denied", "message": "دسترسی ایجاد پروژه‌ی پیش‌فرض وجود ندارد."}
        if idempotency_key:
            idem_rec, owner = self.env["ai.gateway.idempotency"].sudo().claim(self.env.user.id, idempotency_key, "create_task")
            if not owner:
                if idem_rec.status == "completed":
                    return self.env["ai.gateway.idempotency"].get_cached(self.env.user.id, idempotency_key)
                return {"error": "idempotency_in_progress", "message": "همین عملیات در درخواست دیگری در حال اجراست."}
        try:
            task = self.env["project.task"].create({
                "name": title,
                "project_id": project.id,
                "user_ids": [(6, 0, [assignee_user.id])],
                "date_deadline": deadline,
                "description": description or "",
            })
            task.activity_schedule(
                "mail.mail_activity_data_todo",
                date_deadline=deadline,
                summary=title,
                user_id=assignee_user.id,
            )

            # Roadmap #32 (Task System, remaining item): dependency
            # between tasks. Best-effort name lookup, not a hard
            # requirement - unmatched titles are reported, not errors,
            # since the assistant should not fail the whole task
            # creation over an unmatched dependency title.
            unmatched_dependencies = []
            if depends_on_titles:
                dep_names = [n.strip() for n in depends_on_titles.split(",") if n.strip()]
                found = self.env["project.task"]
                for dep_name in dep_names:
                    matches = self.env["project.task"].search(
                        [("name", "ilike", dep_name), ("id", "!=", task.id)], limit=20
                    )
                    if len(matches) > 1:
                        unmatched_dependencies.append("ambiguous:" + dep_name)
                    elif matches:
                        found |= matches[:1]
                    else:
                        unmatched_dependencies.append(dep_name)
                if found:
                    task.depends_on_task_ids = [(6, 0, found.ids)]

            _audit(self.env, "create_task", payload)
            result = {"status": "created", "task_id": task.id, "assignee": assignee_user.name,
                      "deadline": deadline, "project": project.name,
                      "depends_on": task.depends_on_task_ids.mapped("name"),
                      "unmatched_dependencies": unmatched_dependencies,
                      # Roadmap #9 (Calendar Integration, Deadline -> Reminder
                      # -> Escalation): carried through the "task.created"
                      # event payload so that downstream workflow steps
                      # (ai_workflow/data/default_workflows.xml,
                      # "task_deadline_escalation") can actually resolve a
                      # real recipient for the reminder/escalation
                      # notification instead of publishing an event with no
                      # addressable user - see
                      # ai_integration/models/event_dispatch.py
                      # _recipient_users(), which reads this exact key.
                      "notify_user_ids": [assignee_user.id]}
            idem_rec.complete(result) if idem_rec else None
            if "ai.control.event" in self.env:
                self.env["ai.control.event"].publish("task.created", aggregate=task, payload=result)
            return result
        except (AccessError, UserError) as exc:
            if idem_rec: idem_rec.fail(exc)
            _audit(self.env, "create_task", payload, success=False, error_message=str(exc))
            return {"error": "access_denied"}

    @llm_tool(read_only_hint=True)
    def list_overdue_tasks(self) -> dict:
        """List tasks whose deadline has passed and are still not
        marked done, limited to whatever project.task records Odoo's
        record rules let the current user see. Used both for direct
        questions ('what's overdue?') and by the daily reminder cron."""
        today = fields.Date.context_today(self)
        tasks = self.env["project.task"].search([
            ("date_deadline", "<", today),
            ("stage_id.is_closed", "=", False),
        ])
        return {"count": len(tasks), "overdue": [
            {"id": t.id, "title": t.name,
             "assignee": ", ".join(t.user_ids.mapped("name")) or "بدون مسئول",
             "deadline": str(t.date_deadline)}
            for t in tasks
        ]}

    # Roadmap item #9 (Business Tools, remaining item): "list_my_tasks"
    # - deliberately hard-scoped to the CURRENT user's own tasks via
    # user_ids=self.env.user, not just relying on record rules to
    # narrow it (unlike list_overdue_tasks/list_pending_leaves, which
    # are manager-facing and depend entirely on Odoo's own ACL to
    # decide what's visible). This is the personal "what's on my
    # plate" view every employee needs, regardless of role.
    @llm_tool(read_only_hint=True)
    def list_my_tasks(self, include_done: bool = False) -> dict:
        """List tasks assigned to the CURRENT user only - 'what do I
        have to do'. Unlike list_overdue_tasks (which is scoped by
        Odoo's project record rules and mainly useful for a
        manager reviewing a team), this always means 'my own tasks',
        for any employee regardless of role.

        Parameters:
            include_done: If true, also include tasks in a closed/done
                stage. Defaults to false (open tasks only).
        """
        domain = [("user_ids", "in", [self.env.user.id])]
        if not include_done:
            domain.append(("stage_id.is_closed", "=", False))
        today = fields.Date.context_today(self)
        tasks = self.env["project.task"].search(domain, order="date_deadline")
        return {"count": len(tasks), "tasks": [
            {"id": t.id, "title": t.name,
             "project": t.project_id.name or "",
             "deadline": str(t.date_deadline) if t.date_deadline else None,
             "overdue": bool(t.date_deadline and t.date_deadline < today and not t.stage_id.is_closed),
             "stage": t.stage_id.name or "", "done": bool(t.stage_id.is_closed)}
            for t in tasks
        ]}

    def cron_notify_overdue_tasks(self):
        """Scheduled job (see data/cron_data.xml): runs as a dedicated
        restricted service user, not admin, so an autonomous job can
        never do more than that limited account is allowed to see.
        Posts a to-do activity reminder to whoever a task is overdue
        for - this is proactive, not something the employee has to ask
        the chat for."""
        today = fields.Date.context_today(self)
        overdue = self.env["project.task"].sudo().search([
            ("date_deadline", "<", today),
            ("stage_id.is_closed", "=", False),
        ])
        for task in overdue:
            for user in task.user_ids:
                task.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=f"⚠️ تسک عقب‌افتاده: {task.name}",
                    note=f"سررسید این تسک {task.date_deadline} بود و هنوز انجام نشده.",
                    user_id=user.id,
                )
        _logger.info("cron_notify_overdue_tasks: notified for %s overdue task(s)", len(overdue))
