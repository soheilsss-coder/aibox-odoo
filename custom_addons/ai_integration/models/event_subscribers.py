import json
from odoo import api, models


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
    event_id = models.Many2one("ai.control.event", required=True, ondelete="cascade", index=True)
    event_type = models.Char(required=True, index=True)
    payload_json = models.Text(default="{}", required=True)
    user_id = models.Many2one("res.users", ondelete="set null", index=True)
    state = models.Selection([("queued","Queued"),("consumed","Consumed"),("failed","Failed")], default="queued", index=True)
