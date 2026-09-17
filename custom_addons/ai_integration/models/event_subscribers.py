import json
from odoo import api, fields, models


class _SubscriberBase(models.AbstractModel):
    _name = "ai.integration.subscriber.base"
    _description = "Base explicit event subscriber"

    @api.model
    def _delegate(self, target, event, payload):
        dispatcher = self.env["ai.integration.event.dispatcher"]
        handler = getattr(dispatcher, "_handle_%s" % target)
        return handler(event, payload)


class AiWorkflowSubscriber(_SubscriberBase):
    _name = "ai.integration.workflow.subscriber"
    _description = "Workflow Event Subscriber"
    def _handle_event(self, event, payload): return self._delegate("workflow", event, payload)


class AiAuditSubscriber(_SubscriberBase):
    _name = "ai.integration.audit.subscriber"
    _description = "Audit Event Subscriber"
    def _handle_event(self, event, payload): return self._delegate("audit", event, payload)


class AiNotificationSubscriber(_SubscriberBase):
    _name = "ai.integration.notification.subscriber"
    _description = "Notification Event Subscriber"
    def _handle_event(self, event, payload): return self._delegate("notification", event, payload)


class AiBuzzSubscriber(_SubscriberBase):
    _name = "ai.integration.buzz.subscriber"
    _description = "Buzz Event Subscriber"
    def _handle_event(self, event, payload): return self._delegate("buzz", event, payload)


class AiTelegramSubscriber(_SubscriberBase):
    _name = "ai.integration.telegram.subscriber"
    _description = "Telegram Event Subscriber"
    def _handle_event(self, event, payload): return self._delegate("telegram", event, payload)


class AiMemorySubscriber(_SubscriberBase):
    _name = "ai.integration.memory.subscriber"
    _description = "Memory Event Subscriber"
    def _handle_event(self, event, payload): return self._delegate("memory", event, payload)


class AiRagSubscriber(_SubscriberBase):
    _name = "ai.integration.rag.subscriber"
    _description = "RAG Event Subscriber"
    def _handle_event(self, event, payload): return self._delegate("rag", event, payload)


class AiCalendarSubscriber(_SubscriberBase):
    _name = "ai.integration.calendar.subscriber"
    _description = "Calendar Event Subscriber"
    def _handle_event(self, event, payload): return self._delegate("calendar", event, payload)


class AiActivitySubscriber(_SubscriberBase):
    _name = "ai.integration.activity.subscriber"
    _description = "Workflow Activity Request Subscriber"

    def _handle_event(self, event, payload):
        model_name = payload.get("model")
        record_id = payload.get("record_id")
        if not model_name or not record_id:
            return {"status": "skipped", "reason": "missing activity target"}
        if model_name not in self.env:
            return {"status": "skipped", "reason": "model not installed"}
        try:
            record_id = int(record_id)
        except (TypeError, ValueError):
            return {"status": "skipped", "reason": "invalid record id"}
        record = self.env[model_name].sudo().browse(record_id).exists()
        if not record:
            return {"status": "skipped", "reason": "record not found"}
        summary = payload.get("summary") or event.event_type
        note = payload.get("note") or payload.get("message") or "Workflow activity request"
        deadline = payload.get("date_deadline") or fields.Date.context_today(self)
        user_id = payload.get("user_id") or payload.get("notify_user_id") or (event.user_id.id if event.user_id else self.env.user.id)
        user_id = int(user_id) if str(user_id or "").isdigit() else self.env.user.id
        if hasattr(record, "activity_schedule"):
            record.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=summary,
                note=note,
                date_deadline=deadline,
                user_id=user_id,
            )
            return {"status": "activity_scheduled", "model": model_name, "record_id": record.id, "user_id": user_id}
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        model = self.env["ir.model"].sudo()._get(model_name)
        self.env["mail.activity"].sudo().create({
            "activity_type_id": activity_type.id if activity_type else False,
            "summary": summary,
            "note": note,
            "date_deadline": deadline,
            "user_id": user_id,
            "res_model_id": model.id,
            "res_id": record.id,
        })
        return {"status": "activity_created", "model": model_name, "record_id": record.id, "user_id": user_id}


class AiModelSubscriber(_SubscriberBase):
    _name = "ai.integration.ai.subscriber"
    _description = "AI Event Subscriber"
    def _handle_event(self, event, payload):
        if "ai.integration.ai.event" not in self.env:
            return {"status": "skipped", "reason": "AI event queue not installed"}
        self.env["ai.integration.ai.event"].sudo().create({
            "event_id": event.id, "event_type": event.event_type,
            "payload_json": json.dumps(payload or {}, ensure_ascii=False, default=str),
            "user_id": event.user_id.id if event.user_id else False,
        })
        return {"status": "ai_event_queued", "event_id": event.id}


class AiEventForAi(models.Model):
    _name = "ai.integration.ai.event"
    _description = "Durable AI Event Subscriber Queue"
    event_id = fields.Many2one("ai.control.event", required=True, ondelete="cascade", index=True)
    event_type = fields.Char(required=True, index=True)
    payload_json = fields.Text(default="{}", required=True)
    user_id = fields.Many2one("res.users", ondelete="set null", index=True)
    state = fields.Selection([("queued","Queued"),("consumed","Consumed"),("failed","Failed")], default="queued", index=True)
