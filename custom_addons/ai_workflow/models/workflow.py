import json
import logging
import socket
import os
import uuid
from datetime import timedelta

from psycopg2 import IntegrityError
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AiWorkflow(models.Model):
    _name = "ai.workflow"
    _description = "Durable AI Workflow"
    _order = "id desc"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    trigger_event = fields.Char(required=True, index=True)
    state = fields.Selection(
        [("draft", "Draft"), ("active", "Active"), ("paused", "Paused")],
        default="draft", required=True, index=True,
    )
    definition_json = fields.Text(default="{}", required=True)
    max_attempts = fields.Integer(default=5)
    lock_timeout_seconds = fields.Integer(default=300)
    version = fields.Integer(default=1)
    compensation_definition_json = fields.Text(default="[]")

    _sql_constraints = [
        ("code_company_unique", "unique(code)", "Workflow code must be unique."),
        ("max_attempts_positive", "CHECK(max_attempts > 0)", "max_attempts must be positive."),
        ("lock_timeout_positive", "CHECK(lock_timeout_seconds > 0)", "lock timeout must be positive."),
    ]

    def validate_definition(self):
        """Validate the durable workflow DSL before activation."""
        for flow in self:
            definition = json.loads(flow.definition_json or "{}")
            steps = definition.get("steps")
            if not isinstance(steps, list) or not steps:
                raise ValueError("Workflow must contain a non-empty steps list.")
            if len(steps) > 100:
                raise ValueError("Workflow cannot contain more than 100 steps.")
            if definition.get("schema_version", 1) not in (1,):
                raise ValueError("Unsupported workflow schema version.")
            allowed = {
                "audit", "activity", "event", "wait", "wait_until", "condition",
                "approval", "human_task", "notify", "branch", "tool", "escalate", "noop",
            }
            for index, step in enumerate(steps):
                if not isinstance(step, dict):
                    raise ValueError(f"Workflow step {index} must be an object.")
                action = step.get("action")
                if action not in allowed:
                    raise ValueError(f"Unsupported workflow action: {action}")
                if action == "wait":
                    seconds = int(step.get("seconds", step.get("wait", 0)) or 0)
                    if seconds < 0 or seconds > 31_536_000:
                        raise ValueError(f"Invalid wait at step {index}")
                if action == "wait_until" and not step.get("datetime"):
                    raise ValueError(f"wait_until step {index} requires datetime.")
                if action in {"condition", "branch"} and not isinstance(step.get("if"), dict):
                    raise ValueError(f"{action} step {index} requires an 'if' object.")
                if action == "branch":
                    for key in ("then", "else"):
                        if key in step:
                            try:
                                jump = int(step[key])
                            except (TypeError, ValueError):
                                raise ValueError(f"branch {key} at step {index} must be an integer")
                            if jump <= index or jump >= len(steps):
                                raise ValueError(f"branch {key} at step {index} must jump forward within the workflow")
                if action == "tool":
                    if not isinstance(step.get("tool") or step.get("tool_name"), str):
                        raise ValueError(f"tool step {index} requires a tool name")
                    if not isinstance(step.get("args", {}), dict) or len(step.get("args", {})) > 32:
                        raise ValueError(f"tool args at step {index} must be an object with at most 32 keys")
                if action == "approval" and not (step.get("approval_code") or step.get("name")):
                    raise ValueError(f"Approval step {index} requires approval_code.")
        return True

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ("definition_json", "state", "trigger_event", "active")):
            for flow in self:
                if flow.state == "active" and flow.active:
                    flow.validate_definition()
        return res


class AiWorkflowApproval(models.Model):
    _name = "ai.workflow.approval"
    _description = "Durable Workflow Human Approval"
    _order = "id desc"

    run_id = fields.Many2one("ai.workflow.run", required=True, ondelete="cascade", index=True)
    step_index = fields.Integer(required=True)
    code = fields.Char(required=True, index=True)
    state = fields.Selection([
        ("pending", "Pending"), ("approved", "Approved"),
        ("rejected", "Rejected"), ("cancelled", "Cancelled"), ("timed_out", "Timed Out"),
    ], default="pending", index=True)
    requested_by = fields.Many2one("res.users", required=True, default=lambda s: s.env.user)
    approver_user_id = fields.Many2one("res.users", index=True)
    approver_group_id = fields.Many2one("res.groups", index=True)
    timeout_at = fields.Datetime(index=True)
    decision_at = fields.Datetime()
    comment = fields.Text()
    idempotency_key = fields.Char(required=True, index=True)

    _sql_constraints = [
        ("approval_unique", "unique(idempotency_key)", "Workflow approval already exists."),
    ]

    def decide(self, decision, comment=None):
        self.ensure_one()
        if decision not in ("approved", "rejected", "cancelled", "timed_out"):
            raise ValueError("Invalid approval decision.")
        if self.state != "pending":
            return self
        # Authorization is evaluated at decision time. A group requirement is
        # intentionally enforced here instead of trusting the requester.
        if self.approver_user_id and self.approver_user_id != self.env.user:
            raise PermissionError("Only the assigned approver may decide this approval.")
        if self.approver_group_id:
            xmlid = self.env["ir.model.data"].sudo().search([
                ("model", "=", "res.groups"), ("res_id", "=", self.approver_group_id.id)
            ], limit=1)
            if not xmlid or not self.env.user.has_group(f"{xmlid.module}.{xmlid.name}"):
                raise PermissionError("Current user is not an approved workflow approver.")
        self.write({
            "state": decision, "decision_at": fields.Datetime.now(),
            "comment": comment or False, "approver_user_id": self.env.user.id,
        })
        return self


class AiWorkflowRun(models.Model):
    _name = "ai.workflow.run"
    _description = "Durable AI Workflow Run"
    _order = "id desc"

    workflow_id = fields.Many2one("ai.workflow", required=True, ondelete="restrict", index=True)
    event_id = fields.Many2one("ai.control.event", index=True, ondelete="set null")
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company, index=True)
    state = fields.Selection([
        ("queued", "Queued"), ("running", "Running"), ("waiting", "Waiting"),
        ("completed", "Completed"), ("failed", "Failed"), ("dead_letter", "Dead Letter"), ("cancelled", "Cancelled"),
    ], default="queued", index=True)
    step_index = fields.Integer(default=0)
    attempts = fields.Integer(default=0)
    max_attempts = fields.Integer(related="workflow_id.max_attempts", store=True, readonly=True)
    next_run_at = fields.Datetime(default=fields.Datetime.now, index=True)
    waiting_until = fields.Datetime(index=True)
    waiting_reason = fields.Char()
    context_json = fields.Text(default="{}")
    error = fields.Text()
    idempotency_key = fields.Char(required=True, index=True)
    correlation_id = fields.Char(index=True)
    causation_id = fields.Char(index=True)
    locked_at = fields.Datetime(index=True)
    locked_by = fields.Char(index=True)
    completed_at = fields.Datetime()
    failed_at = fields.Datetime()
    compensation_started = fields.Boolean(default=False)

    _sql_constraints = [
        ("idempotency_unique", "unique(idempotency_key)", "Workflow run already exists."),
    ]

    @api.model
    def enqueue_for_event(self, event):
        flows = self.env["ai.workflow"].sudo().search([
            ("active", "=", True), ("state", "=", "active"),
            ("trigger_event", "=", event.event_type),
        ])
        created = []
        for flow in flows:
            flow.validate_definition()
            key = f"{flow.id}:{event.event_key}"
            existing = self.search([("idempotency_key", "=", key)], limit=1)
            if existing:
                continue
            vals = {
                "workflow_id": flow.id,
                "event_id": event.id,
                "company_id": event.company_id.id,
                "idempotency_key": key,
                "context_json": event.payload_json or "{}",
                "correlation_id": event.correlation_id,
                "causation_id": event.event_key,
            }
            try:
                with self.env.cr.savepoint():
                    created.append(self.create(vals))
            except IntegrityError:
                continue
        return created

    def _context(self):
        self.ensure_one()
        value = json.loads(self.context_json or "{}")
        return value if isinstance(value, dict) else {}

    def _set_context(self, value):
        self.ensure_one()
        self.write({"context_json": json.dumps(value, ensure_ascii=False, default=str)})

    def _resolve_value(self, value, context):
        if isinstance(value, str) and value.startswith("$"):
            current = context
            for part in value[1:].split("."):
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    return None
            return current
        return value

    def _compare(self, left, operator, right):
        if operator == "eq": return left == right
        if operator == "ne": return left != right
        if operator == "in": return left in (right or [])
        if operator == "not_in": return left not in (right or [])
        if operator == "exists": return left is not None
        if operator == "truthy": return bool(left)
        if operator == "contains": return right in left if left is not None else False
        if operator == "gt": return left > right
        if operator == "gte": return left >= right
        if operator == "lt": return left < right
        if operator == "lte": return left <= right
        raise ValueError(f"Unsupported condition operator: {operator}")

    def _condition_matches(self, spec, context):
        if not isinstance(spec, dict):
            return False
        if "all" in spec:
            return all(self._condition_matches(x, context) for x in spec["all"])
        if "any" in spec:
            return any(self._condition_matches(x, context) for x in spec["any"])
        left = self._resolve_value(spec.get("value"), context)
        right = self._resolve_value(spec.get("compare"), context)
        return self._compare(left, spec.get("operator", "eq"), right)

    def _schedule_wait(self, seconds, reason=None, next_index=None):
        seconds = max(0, int(seconds))
        when = fields.Datetime.add(fields.Datetime.now(), seconds=seconds)
        vals = {
            "state": "waiting", "waiting_until": when, "waiting_reason": reason or "workflow wait",
            "next_run_at": when,
        }
        if next_index is not None:
            vals["step_index"] = next_index
        self.write(vals)

    def _execute_step(self, step, context):
        action = step.get("action")
        if action == "noop":
            return {"status": "ok"}

        if action == "audit":
            if "ai.gateway.audit.log" in self.env:
                self.env["ai.gateway.audit.log"].sudo().log(
                    user_id=self.event_id.user_id.id if self.event_id else self.env.user.id,
                    source="workflow", action=step.get("name", self.workflow_id.code),
                    payload={"workflow_run_id": self.id, **context},
                )
            return {"status": "audited"}

        if action == "activity":
            # Workflow must not mutate arbitrary ERP records with sudo().
            # Convert the request into a durable domain event; a dedicated
            # subscriber/tool can perform the named business action through
            # the normal Authorization/Risk/Approval gateway.
            model = step.get("model")
            rid = int(self._resolve_value(step.get("record_id"), context) or 0)
            if not model or not rid:
                raise ValueError("Invalid workflow activity target.")
            payload = dict(context)
            payload.update({
                "model": model,
                "record_id": rid,
                "summary": step.get("summary") or self.workflow_id.name,
                "note": step.get("note") or "Workflow activity request",
                "date_deadline": step.get("date_deadline") or False,
            })
            event = self.env["ai.control.event"].sudo().publish(
                "workflow.activity.requested",
                payload=payload,
                user=self.event_id.user_id if self.event_id else self.env.user,
                correlation_id=self.correlation_id,
                causation_id=self.event_id.event_key if self.event_id else False,
            )
            return {"status": "activity_requested", "event_id": event.id}

        if action == "event":
            event_type = step.get("event_type")
            if not event_type:
                raise ValueError("Event step requires event_type.")
            event = self.env["ai.control.event"].sudo().publish(
                event_type, payload=context,
                user=self.event_id.user_id if self.event_id else self.env.user,
                correlation_id=self.correlation_id,
                causation_id=self.event_id.event_key if self.event_id else False,
            )
            return {"status": "event_published", "event_id": event.id}

        if action == "notify":
            # Notifications are emitted through the durable Event Bus, never
            # synchronously to external providers.
            users = step.get("user_ids") or context.get("notify_user_ids") or []
            payload = dict(context)
            payload.update({
                "notify_user_ids": users,
                "summary": step.get("summary") or self.workflow_id.name,
                "message": step.get("message") or step.get("note") or self.workflow_id.name,
            })
            event = self.env["ai.control.event"].sudo().publish(
                "workflow.notification",
                payload=payload,
                user=self.event_id.user_id if self.event_id else self.env.user,
                correlation_id=self.correlation_id,
                causation_id=self.event_id.event_key if self.event_id else False,
            )
            return {"status": "notification_event", "event_id": event.id}

        if action == "condition":
            matched = self._condition_matches(step.get("if") or {}, context)
            if not matched:
                context["condition_false"] = True
            else:
                context["condition_true"] = True
            return {"status": "condition_evaluated", "matched": matched}

        if action == "branch":
            matched = self._condition_matches(step.get("if") or {}, context)
            jump = step.get("then") if matched else step.get("else")
            if jump is not None:
                return {"status": "branch", "jump": int(jump), "matched": matched}
            return {"status": "branch", "matched": matched}

        if action == "tool":
            tool_name = step.get("tool") or step.get("tool_name")
            if not tool_name or "ai.gateway.execution.gate" not in self.env:
                raise ValueError("tool step requires the central execution gate and tool name")
            raw_args = step.get("args") or {}
            if not isinstance(raw_args, dict):
                raise ValueError("workflow tool args must be an object")
            args = {k: self._resolve_value(v, context) for k, v in raw_args.items()}
            actor = self.event_id.user_id if self.event_id and self.event_id.user_id else self.env.user
            # Workflow tools always traverse the same central gateway used by
            # Hermes/API callers. No workflow step may invoke llm.tool or an
            # ERP adapter directly. Approval/Risk/Authorization therefore stay
            # mandatory at execution time.
            result = self.env["ai.gateway.execution.gate"].with_user(actor).execute(tool_name, args=args)
            # Tool output is untrusted document/business data. Scrub it
            # before it reaches durable workflow state or a later model/tool
            # decision; the execution gate remains authoritative for the
            # current call and the firewall prevents context poisoning/secrets
            # from surviving into the next call.
            from odoo.addons.ai_business_tools.models.context_firewall import scrub_value
            safe_result = scrub_value(result)
            # Keep the most recent result in the durable context for a
            # following condition/branch step, while retaining a keyed audit
            # trail for later steps and operators.
            context["last_tool_result"] = safe_result if isinstance(safe_result, dict) else {"value": safe_result}
            context.setdefault("tool_results", {})[tool_name] = safe_result
            return {"status": "tool_executed", "tool": tool_name}

        if action == "escalate":
            event_type = step.get("event_type") or "workflow.escalated"
            payload = dict(context)
            payload.update({"workflow_run_id": self.id, "workflow_code": self.workflow_id.code,
                            "reason": step.get("reason") or "workflow escalation"})
            self.env["ai.control.event"].sudo().publish(
                event_type, payload=payload,
                user=self.event_id.user_id if self.event_id else self.env.user,
                correlation_id=self.correlation_id,
                causation_id=self.event_id.event_key if self.event_id else False,
            )
            return {"status": "escalated", "event_type": event_type}

        if action == "approval":
            code = step.get("approval_code") or step.get("name") or f"{self.workflow_id.code}:{self.step_index}"
            key = f"{self.id}:{self.step_index}:{code}"
            Approval = self.env["ai.workflow.approval"].sudo()
            approval = Approval.search([("idempotency_key", "=", key)], limit=1)
            if not approval:
                approval = Approval.create({
                    "run_id": self.id, "step_index": self.step_index, "code": code,
                    "requested_by": self.event_id.user_id.id if self.event_id else self.env.user.id,
                    "approver_user_id": step.get("approver_user_id") or False,
                    "approver_group_id": step.get("approver_group_id") or False,
                    "timeout_at": fields.Datetime.add(fields.Datetime.now(), seconds=int(step.get("timeout_seconds") or 0)) if step.get("timeout_seconds") else False,
                    "idempotency_key": key,
                })
            if approval.state == "pending":
                if approval.timeout_at and approval.timeout_at <= fields.Datetime.now():
                    approval.sudo().write({"state": "timed_out", "decision_at": fields.Datetime.now(), "comment": "Workflow approval timed out."})
                    timeout_action = step.get("on_timeout", "fail")
                    if timeout_action == "continue":
                        return {"status": "timeout_continue", "approval_id": approval.id}
                    if timeout_action == "event":
                        self.env["ai.control.event"].sudo().publish(
                            step.get("timeout_event") or "workflow.approval.timeout",
                            payload=context, user=self.event_id.user_id if self.event_id else self.env.user,
                            correlation_id=self.correlation_id,
                            causation_id=self.event_id.event_key if self.event_id else False,
                        )
                    raise ValueError("Workflow approval timed out.")
                return {"status": "waiting_approval", "approval_id": approval.id}
            if approval.state != "approved":
                raise ValueError(f"Workflow approval {approval.state}.")
            context["approval_id"] = approval.id
            return {"status": "approved", "approval_id": approval.id}

        if action == "human_task":
            # Human tasks are emitted as durable domain events. The workflow
            # engine must never mutate mail.activity directly with sudo(),
            # otherwise it becomes a parallel ERP mutation path that can
            # bypass the central authorization/risk/approval boundary.
            user_id = int(self._resolve_value(step.get("user_id"), context) or 0)
            if not user_id:
                raise ValueError("human_task requires user_id.")
            payload = dict(context)
            payload.update({
                "workflow_run_id": self.id,
                "workflow_code": self.workflow_id.code,
                "user_id": user_id,
                "summary": step.get("summary") or self.workflow_id.name,
                "note": step.get("note") or "Workflow human task",
                "date_deadline": step.get("date_deadline") or False,
            })
            event = self.env["ai.control.event"].sudo().publish(
                "workflow.human_task.requested",
                payload=payload,
                user=self.event_id.user_id if self.event_id else self.env.user,
                correlation_id=self.correlation_id,
                causation_id=self.event_id.event_key if self.event_id else False,
            )
            return {"status": "human_task_requested", "event_id": event.id}

        if action == "wait":
            seconds = step.get("seconds", step.get("wait", 0))
            self._schedule_wait(seconds, step.get("reason"), self.step_index + 1)
            return {"status": "waiting"}

        if action == "wait_until":
            value = self._resolve_value(step.get("datetime"), context)
            if not value:
                raise ValueError("wait_until requires datetime.")
            self.write({
                "state": "waiting", "waiting_until": value, "next_run_at": value,
                "waiting_reason": step.get("reason") or "workflow wait until",
                "step_index": self.step_index + 1,
            })
            return {"status": "waiting"}

        raise ValueError(f"Unsupported workflow action: {action}")

    @api.model
    def _claim_due_runs(self, limit=50):
        now = fields.Datetime.now()
        stale = fields.Datetime.subtract(now, seconds=300)
        worker = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.env.cr.execute("""
            SELECT id FROM ai_workflow_run
             WHERE state IN ('queued','running','waiting')
               AND (next_run_at IS NULL OR next_run_at <= %s)
               AND (locked_at IS NULL OR locked_at < %s)
             ORDER BY id
             FOR UPDATE SKIP LOCKED LIMIT %s
        """, (now, stale, limit))
        ids = [x[0] for x in self.env.cr.fetchall()]
        if ids:
            self.env.cr.execute("""
                UPDATE ai_workflow_run
                   SET locked_at=%s, locked_by=%s, state='running', attempts=attempts+1
                 WHERE id=ANY(%s)
            """, (now, worker, ids))
        return self.sudo().browse(ids), worker

    def _release_lock(self):
        self.write({"locked_at": False, "locked_by": False})

    @api.model
    def process_due(self, limit=50):
        runs, worker = self._claim_due_runs(limit)
        count = 0
        for run in runs:
            try:
                definition = json.loads(run.workflow_id.definition_json or "{}")
                steps = definition.get("steps", [])
                context = run._context()

                # Waiting states are resumed only when their durable timestamp is due.
                if run.state == "waiting" and run.waiting_until and run.waiting_until > fields.Datetime.now():
                    run._release_lock()
                    continue

                run.write({"state": "running"})
                while run.step_index < len(steps):
                    step = steps[run.step_index]
                    result = run._execute_step(step, context)

                    if result.get("status") == "waiting_approval":
                        run.write({"state": "waiting", "waiting_reason": "approval", "next_run_at": fields.Datetime.add(fields.Datetime.now(), minutes=1)})
                        break

                    if result.get("status") == "waiting":
                        break
                    if result.get("status") == "timeout_continue":
                        run.write({"waiting_until": False, "waiting_reason": False})

                    jump = result.get("jump")
                    run.step_index = int(jump) if jump is not None else run.step_index + 1
                    run._set_context(context)
                    run.write({"step_index": run.step_index})

                else:
                    run.write({
                        "state": "completed", "completed_at": fields.Datetime.now(),
                        "waiting_until": False, "waiting_reason": False,
                        "error": False,
                    })
                run._release_lock()
                count += 1
            except Exception as exc:
                _logger.exception("Workflow %s failed", run.id)
                if run.attempts < run.workflow_id.max_attempts:
                    delay = min(3600, 2 ** max(0, run.attempts - 1))
                    run.write({
                        "state": "queued", "error": str(exc)[:10000],
                        "next_run_at": fields.Datetime.add(fields.Datetime.now(), seconds=delay),
                    })
                else:
                    run.write({
                        "state": "dead_letter", "error": str(exc)[:10000],
                        "failed_at": fields.Datetime.now(),
                    })
                    run._run_compensation()
                    if "ai.control.event" in run.env:
                        run.env["ai.control.event"].sudo().publish(
                            "workflow.dead_letter",
                            payload={"workflow_run_id": run.id, "workflow_code": run.workflow_id.code,
                                     "error": "workflow step exceeded maximum attempts"},
                            user=run.event_id.user_id if run.event_id else run.env.user,
                            correlation_id=run.correlation_id,
                            causation_id=run.event_id.event_key if run.event_id else False,
                        )
                run._release_lock()
        return count

    @api.model
    def recover_due(self, limit=100):
        """Recovery/deadline worker only. New runs are created and activated by Event Bus.

        This method deliberately does not poll for arbitrary business events; it only
        resumes durable waits/approvals and recovers crashed worker leases.
        """
        return self.process_due(limit=limit)

    def _run_compensation(self):
        self.ensure_one()
        if self.compensation_started:
            return
        self.write({"compensation_started": True})
        definition = json.loads(self.workflow_id.compensation_definition_json or "[]")
        if not isinstance(definition, list):
            return
        context = self._context()
        for step in definition:
            try:
                self._execute_step(step, context)
            except Exception:
                _logger.exception("Compensation failed for workflow run %s", self.id)
