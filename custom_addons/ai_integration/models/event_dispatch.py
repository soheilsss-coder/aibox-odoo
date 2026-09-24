import json
import logging
import os
import socket
import uuid
from datetime import timedelta

from psycopg2 import IntegrityError
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AiEventSubscription(models.Model):
    _name = "ai.integration.subscription"
    _description = "AI Event Bus Subscription"
    _order = "priority desc, id"

    event_type = fields.Char(required=True, index=True)
    target = fields.Selection([
        ("workflow", "Workflow"), ("notification", "Notification"),
        ("audit", "Audit"), ("buzz", "Buzz"), ("telegram", "Telegram"),
        ("memory", "Memory"), ("rag", "RAG"), ("calendar", "Calendar"), ("ai", "AI"),
    ], required=True)
    handler_key = fields.Char(help="Optional stable handler key for observability and idempotency.")
    # Optional first-class subscriber contract. The dispatcher only invokes
    # explicitly registered event handlers; arbitrary Python callables are not
    # accepted. Subscriber methods must be named _handle_event or _handle_event_<name>.
    subscriber_model = fields.Char(index=True, help="Odoo model implementing the subscriber contract.")
    subscriber_method = fields.Char(index=True, help="Subscriber method; must be _handle_event or _handle_event_<name>.")
    active = fields.Boolean(default=True, index=True)
    priority = fields.Integer(default=10, index=True)
    max_attempts = fields.Integer(default=8)
    retry_base_seconds = fields.Integer(default=5)
    description = fields.Text()

    @api.model
    def _validate_handler_contract(self, vals):
        model_name = vals.get("subscriber_model")
        method = vals.get("subscriber_method")
        if bool(model_name) != bool(method):
            raise ValueError("subscriber_model and subscriber_method must be provided together")
        if method and not (method == "_handle_event" or method.startswith("_handle_event_")):
            raise ValueError("event subscriber method must use the _handle_event* contract")
        if model_name and model_name not in self.env:
            raise ValueError("subscriber model is not installed: %s" % model_name)
        if model_name and not callable(getattr(self.env[model_name], method, None)):
            raise ValueError("subscriber handler does not exist: %s.%s" % (model_name, method))

    @api.model
    def create(self, vals):
        self._validate_handler_contract(vals)
        return super().create(vals)

    def write(self, vals):
        if any(k in vals for k in ("subscriber_model", "subscriber_method")):
            for rec in self:
                merged = {"subscriber_model": vals.get("subscriber_model", rec.subscriber_model),
                          "subscriber_method": vals.get("subscriber_method", rec.subscriber_method)}
                self._validate_handler_contract(merged)
        return super().write(vals)

    _sql_constraints = [
        ("subscription_unique", "unique(event_type,target,handler_key)",
         "The same event subscription already exists."),
    ]


class AiEventDelivery(models.Model):
    _name = "ai.integration.event.delivery"
    _description = "Durable Event Bus Delivery"
    _order = "id"

    event_id = fields.Many2one("ai.control.event", required=True, ondelete="cascade", index=True)
    event_type = fields.Char(required=True, index=True)
    target = fields.Selection(related="subscription_id.target", store=True, index=True)
    subscription_id = fields.Many2one("ai.integration.subscription", ondelete="cascade", index=True)
    handler_key = fields.Char(required=True, index=True)
    state = fields.Selection([
        ("queued", "Queued"), ("running", "Running"), ("succeeded", "Succeeded"),
        ("retry", "Retry"), ("dead_letter", "Dead Letter"),
    ], default="queued", index=True)
    attempts = fields.Integer(default=0)
    next_attempt_at = fields.Datetime(default=fields.Datetime.now, index=True)
    locked_at = fields.Datetime(index=True)
    locked_by = fields.Char(index=True)
    started_at = fields.Datetime()
    finished_at = fields.Datetime()
    error = fields.Text()
    result_json = fields.Text(default="{}")
    idempotency_key = fields.Char(required=True, index=True)

    _sql_constraints = [
        ("delivery_unique", "unique(idempotency_key)", "Event delivery already exists."),
    ]


class AiEventDispatcher(models.AbstractModel):
    _name = "ai.integration.event.dispatcher"
    _description = "Durable AI Event Bus Dispatcher"

    LEASE_SECONDS = 300
    EVENT_MAX_ATTEMPTS = 12

    @api.model
    def dispatch_pending(self, limit=100):
        """Drive the durable outbox in two phases:
        1) atomically claim outbox events and materialize durable deliveries;
        2) atomically claim deliveries and execute subscribers with retry/DLQ.

        PostgreSQL row locks + SKIP LOCKED make this safe across multiple Odoo
        workers/containers. No in-memory queue is authoritative.
        """
        worker = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._recover_stale_claims()
        self._materialize_events(limit=limit, worker=worker)
        return self._process_deliveries(limit=limit, worker=worker)

    @api.model
    def _recover_stale_claims(self):
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), seconds=self.LEASE_SECONDS)
        Event = self.env["ai.control.event"].sudo()
        Delivery = self.env["ai.integration.event.delivery"].sudo()
        Event.search([("state", "=", "dispatching"), ("locked_at", "<", cutoff)]).write({
            "state": "pending", "locked_at": False, "locked_by": False,
            "error": "dispatch lease expired; returned to outbox",
        })
        Delivery.search([("state", "=", "running"), ("locked_at", "<", cutoff)]).write({
            "state": "retry", "locked_at": False, "locked_by": False,
            "next_attempt_at": fields.Datetime.now(),
            "error": "delivery lease expired; returned to retry queue",
        })

    @api.model
    def _claim_events(self, limit, worker):
        now = fields.Datetime.now()
        self.env.cr.execute("""
            SELECT id
              FROM ai_control_event
             WHERE state IN ('pending','failed')
               AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
               AND (locked_at IS NULL OR locked_at < %s)
             ORDER BY id
             FOR UPDATE SKIP LOCKED
             LIMIT %s
        """, (now, fields.Datetime.subtract(now, seconds=self.LEASE_SECONDS), limit))
        ids = [row[0] for row in self.env.cr.fetchall()]
        if ids:
            self.env.cr.execute("""
                UPDATE ai_control_event
                   SET state='dispatching', locked_at=%s, locked_by=%s,
                       attempt_count=attempt_count+1
                 WHERE id = ANY(%s)
            """, (now, worker, ids))
        return self.env["ai.control.event"].sudo().browse(ids)

    @api.model
    def _materialize_events(self, limit=100, worker=None):
        worker = worker or str(uuid.uuid4())
        events = self._claim_events(limit, worker)
        Subscription = self.env["ai.integration.subscription"].sudo()
        Delivery = self.env["ai.integration.event.delivery"].sudo()
        for event in events:
            try:
                subs = Subscription.search([("active", "=", True)]).filtered(
                    lambda sub: sub.event_type in (event.event_type, "*") or
                    (sub.event_type.endswith(".*") and event.event_type.startswith(sub.event_type[:-1]))
                )
                for sub in subs:
                    self._ensure_delivery(event, sub, sub.handler_key or f"subscription:{sub.id}", Delivery)
                # Active workflows are a first-class subscriber even if no static
                # subscription row exists. This keeps workflow discovery dynamic.
                if "ai.workflow" in self.env:
                    flows = self.env["ai.workflow"].sudo().search([
                        ("active", "=", True), ("state", "=", "active"),
                        ("trigger_event", "=", event.event_type),
                    ])
                    for flow in flows:
                        self._ensure_delivery(event, None, f"workflow:{flow.id}", Delivery)
                event.mark_published()
            except Exception as exc:
                _logger.exception("Failed to materialize event %s", event.id)
                dead = event.attempt_count >= self.EVENT_MAX_ATTEMPTS
                event.mark_failed(exc, dead=dead)
        return len(events)

    @api.model
    def _ensure_delivery(self, event, subscription, handler_key, Delivery=None):
        Delivery = Delivery or self.env["ai.integration.event.delivery"].sudo()
        key = f"{event.event_key}:{handler_key}"
        vals = {
            "event_id": event.id,
            "event_type": event.event_type,
            "subscription_id": subscription.id if subscription else False,
            "handler_key": handler_key,
            "idempotency_key": key,
            "state": "queued",
            "next_attempt_at": fields.Datetime.now(),
        }
        try:
            with self.env.cr.savepoint():
                return Delivery.create(vals)
        except IntegrityError:
            return Delivery.search([("idempotency_key", "=", key)], limit=1)

    @api.model
    def _claim_deliveries(self, limit, worker):
        now = fields.Datetime.now()
        stale = fields.Datetime.subtract(now, seconds=self.LEASE_SECONDS)
        self.env.cr.execute("""
            SELECT id
              FROM ai_integration_event_delivery
             WHERE state IN ('queued','retry')
               AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
             ORDER BY id
             FOR UPDATE SKIP LOCKED
             LIMIT %s
        """, (now, limit))
        ids = [r[0] for r in self.env.cr.fetchall()]
        if ids:
            self.env.cr.execute("""
                UPDATE ai_integration_event_delivery
                   SET state='running', locked_at=%s, locked_by=%s,
                       attempts=attempts+1, started_at=%s
                 WHERE id = ANY(%s)
            """, (now, worker, now, ids))
        return self.env["ai.integration.event.delivery"].sudo().browse(ids)

    @api.model
    def _process_deliveries(self, limit=100, worker=None):
        worker = worker or str(uuid.uuid4())
        deliveries = self._claim_deliveries(limit, worker)
        for delivery in deliveries:
            try:
                result = self._dispatch_delivery(delivery)
                delivery.write({
                    "state": "succeeded", "finished_at": fields.Datetime.now(),
                    "locked_at": False, "locked_by": False,
                    "error": False, "result_json": json.dumps(result or {}, ensure_ascii=False, default=str),
                })
            except Exception as exc:
                _logger.exception("Event delivery %s failed", delivery.id)
                max_attempts = delivery.subscription_id.max_attempts if delivery.subscription_id else 8
                if delivery.attempts >= max_attempts:
                    delivery.write({
                        "state": "dead_letter", "finished_at": fields.Datetime.now(),
                        "locked_at": False, "locked_by": False, "error": str(exc)[:10000],
                    })
                else:
                    base = delivery.subscription_id.retry_base_seconds if delivery.subscription_id else 5
                    delay = min(3600, base * (2 ** max(0, delivery.attempts - 1)))
                    delivery.write({
                        "state": "retry", "next_attempt_at": fields.Datetime.add(fields.Datetime.now(), seconds=delay),
                        "locked_at": False, "locked_by": False, "error": str(exc)[:10000],
                    })
        return len(deliveries)

    @api.model
    def _dispatch_delivery(self, delivery):
        event = delivery.event_id
        payload = json.loads(event.payload_json or "{}")
        subscription = delivery.subscription_id
        target = subscription.target if subscription else "workflow"
        if subscription and subscription.subscriber_model and subscription.subscriber_method:
            model = self.env[subscription.subscriber_model].sudo()
            handler = getattr(model, subscription.subscriber_method, None)
            if not callable(handler):
                raise ValueError("subscriber handler disappeared: %s.%s" % (subscription.subscriber_model, subscription.subscriber_method))
            result = handler(event, payload)
            return result if isinstance(result, dict) else {"status": "handled", "result": result}
        if target == "workflow":
            if "ai.workflow.run" not in self.env:
                return {"status": "skipped", "reason": "workflow module not installed"}
            runs = self.env["ai.workflow.run"].sudo().enqueue_for_event(event)
            # Event-driven execution: the Event Bus is the trigger. The minute cron
            # is reserved for recovery/deadlines only. A durable DB row remains the
            # source of truth, so a crash before execution is recovered safely.
            processed = self.env["ai.workflow.run"].sudo().process_due(limit=max(1, len(runs))) if runs else 0
            return {"status": "triggered", "workflow_runs": len(runs), "processed": processed}
        handler = getattr(self, f"_handle_{target}", None)
        if not handler:
            raise ValueError(f"unsupported event bus target: {target}")
        return handler(event, payload)

    def _handle_audit(self, event, payload):
        if "ai.gateway.audit.log" not in self.env:
            return {"status": "skipped", "reason": "audit module not installed"}
        self.env["ai.gateway.audit.log"].sudo().log(
            user_id=event.user_id.id, source="event_bus", action=event.event_type,
            payload={"event_id": event.id, "event_key": event.event_key, **payload},
        )
        return {"status": "audited"}

    def _recipient_users(self, event, payload):
        ids = payload.get("notify_user_ids") or []
        one = payload.get("notify_user_id")
        if one:
            ids.append(one)
        return self.env["res.users"].sudo().browse(list({int(x) for x in ids if str(x).isdigit()})).exists()

    def _handle_notification(self, event, payload):
        users = self._recipient_users(event, payload)
        summary = payload.get("summary") or event.event_type
        note = payload.get("note") or payload.get("message") or "یک رویداد سازمانی جدید نیازمند توجه شماست."
        deadline = payload.get("date_deadline")
        aggregate = False
        if event.aggregate_model and event.aggregate_id and event.aggregate_model in self.env:
            aggregate = self.env[event.aggregate_model].sudo().browse(event.aggregate_id).exists()
        if not users:
            # Built-in resolution for common organizational events.
            if event.event_type == "leave.created" and aggregate and "employee_id" in aggregate._fields:
                manager = aggregate.employee_id.parent_id.user_id
                users = manager if manager else users
            elif event.event_type == "task.created" and aggregate and "user_ids" in aggregate._fields:
                users = aggregate.user_ids
        if aggregate and hasattr(aggregate, "activity_schedule"):
            for user in users:
                aggregate.activity_schedule("mail.mail_activity_data_todo", summary=summary, note=note, date_deadline=deadline, user_id=user.id)
        else:
            for user in users:
                self.env["mail.activity"].sudo().create({"summary": summary, "note": note, "user_id": user.id, "res_model_id": self.env["ir.model"].sudo()._get("res.users").id, "res_id": user.id})
        return {"status": "notified", "user_ids": users.ids}

    def _handle_buzz(self, event, payload):
        users = self._recipient_users(event, payload)
        body = payload.get("message") or f"{event.event_type}: {payload}"
        channel = payload.get("channel") or "ai_event_bus"
        for user in users:
            if "bus.bus" in self.env:
                self.env["bus.bus"]._sendone(user.partner_id, channel, {"event_id": event.id, "event_type": event.event_type, "message": body})
        return {"status": "buzz_published", "user_ids": users.ids}

    def _handle_telegram(self, event, payload):
        if "ai.gateway.telegram.link" not in self.env:
            return {"status": "skipped", "reason": "telegram bridge not installed"}
        users = self._recipient_users(event, payload)
        text = payload.get("message") or payload.get("note") or event.event_type
        sent = self.env["ai.gateway.telegram.link"].sudo().send_event_text(users.ids, text)
        return {"status": "telegram_sent", "count": sent}

    def _handle_memory(self, event, payload):
        if "ai.agent.memory.record" not in self.env:
            return {"status": "skipped", "reason": "memory module not installed"}
        user = event.user_id
        key = payload.get("memory_key")
        value = payload.get("memory_value")
        if not key or value is None:
            return {"status": "skipped", "reason": "no memory payload"}
        rec = self.env["ai.agent.memory.record"].sudo().create_memory(key, str(value), scope=payload.get("memory_scope", "personal"), user=user)
        return {"status": "memory_saved", "memory_id": rec.id}

    def _handle_rag(self, event, payload):
        if "ai.document.index.job" not in self.env:
            return {"status": "skipped", "reason": "rag module not installed"}
        if event.aggregate_model != "company.document" or not event.aggregate_id:
            return {"status": "skipped", "reason": "event has no company.document aggregate"}
        doc = self.env["company.document"].sudo().browse(event.aggregate_id).exists()
        if not doc:
            return {"status": "skipped", "reason": "document not found"}
        job = self.env["ai.document.index.job"].sudo().enqueue(doc)
        return {"status": "rag_queued", "job_id": job.id}

    def _handle_calendar(self, event, payload):
        if "calendar.event" not in self.env:
            return {"status": "skipped", "reason": "calendar module not installed"}
        spec = dict(payload.get("calendar_event") or {})
        aggregate = False
        if event.aggregate_model and event.aggregate_id and event.aggregate_model in self.env:
            aggregate = self.env[event.aggregate_model].sudo().browse(event.aggregate_id).exists()
        # Business events get real calendar automation even when the producer
        # did not manually construct a calendar_event payload.
        if not spec and event.event_type == "leave.approved" and aggregate and "date_from" in aggregate._fields:
            user = aggregate.employee_id.user_id if "employee_id" in aggregate._fields and aggregate.employee_id else False
            spec = {"name": "Leave: %s" % (aggregate.employee_id.name if aggregate.employee_id else ""),
                    "start": aggregate.date_from, "stop": aggregate.date_to, "allday": False,
                    "user_id": (user.id if user else False),
                    "partner_ids": [user.partner_id.id if user and user.partner_id else 0]}
        elif not spec and event.event_type == "task.created" and aggregate and "date_deadline" in aggregate._fields and aggregate.date_deadline:
            user = aggregate.user_ids[:1] if "user_ids" in aggregate._fields else False
            start = "%s 09:00:00" % aggregate.date_deadline
            stop = "%s 10:00:00" % aggregate.date_deadline
            spec = {"name": "Task deadline: %s" % aggregate.name, "start": start, "stop": stop, "allday": False,
                    "user_id": (user.id if user else False),
                    "partner_ids": [user.partner_id.id if user and user.partner_id else 0]}
        if not spec:
            return {"status": "skipped", "reason": "no calendar specification"}
        vals = {"name": spec.get("name") or event.event_type, "start": spec.get("start"), "stop": spec.get("stop"), "allday": bool(spec.get("allday"))}
        partners = []
        if spec.get("partner_ids"):
            partners = [int(x) for x in spec["partner_ids"] if int(x)]
        if spec.get("user_id"):
            # calendar.event.user_id is the organizer PARTNER (not a res.users row);
            # mapping it wrong leaves a dangling reference and a calendar the
            # assignee never sees. Resolve the real partner here.
            organizer = self.env["res.users"].sudo().browse(int(spec["user_id"]))
            if organizer.exists() and organizer.partner_id:
                vals["user_id"] = organizer.partner_id.id
                if organizer.partner_id.id not in partners:
                    partners.append(organizer.partner_id.id)
        if partners:
            vals["partner_ids"] = [(6, 0, partners)]
        rec = self.env["calendar.event"].sudo().create(vals)
        return {"status": "calendar_created", "event_id": rec.id}
