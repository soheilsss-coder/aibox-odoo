import logging
from odoo import api, models
from odoo.addons.llm_tool.decorators import llm_tool

_logger = logging.getLogger(__name__)


class LLMToolAgentMemory(models.Model):
    _inherit = "llm.tool"

    @llm_tool(destructive_hint=True)
    def save_memory(self, key: str, value: str, scope: str = "personal") -> dict:
        if "ai.gateway.tool.risk" in self.env:
            self.env["ai.gateway.execution.gate"].authorize("save_memory")
        if scope not in ("personal", "department", "company"):
            scope = "personal"
        try:
            rec = self.env["ai.agent.memory.record"].create_memory(key, value, scope=scope, user=self.env.user)
        except Exception as exc:
            _logger.warning("save_memory failed: %s", exc)
            return {"error": "memory_save_failed"}
        if "ai.gateway.audit.log" in self.env:
            self.env["ai.gateway.audit.log"].sudo().log(user_id=self.env.user.id, source="tool", action="save_memory", payload={"key": key, "scope": scope})
        return {"status": "saved", "key": rec.key, "scope": rec.scope, "memory_id": rec.id, "provider": "odoo-orm-canonical"}

    @llm_tool(read_only_hint=True)
    def recall_memory(self, query: str = "") -> dict:
        records = self.env["ai.agent.memory.record"].visible_for(self.env.user)
        if query:
            q = query.lower()
            records = records.filtered(lambda r: q in (r.key or "").lower() or q in (self.env["ai.agent.memory.record"]._decrypt(r.value) or "").lower())
        records = records[:10]
        result = {"memories": [{"key": r.key, "value": self.env["ai.agent.memory.record"]._decrypt(r.value), "saved_at": r.created_at, "scope": r.scope, "source": r.source} for r in records]}
        if not result["memories"]:
            return {"error": "No matching memories found."}
        if hasattr(self, "_context_firewall"):
            result = self._context_firewall(result)
        return result


class AiMemoryCleanup(models.AbstractModel):
    _name = "ai.memory.cleanup"
    _description = "Memory Retention Cleanup"

    @api.model
    def cron_cleanup(self):
        if "ai.agent.memory.record" in self.env:
            return self.env["ai.agent.memory.record"].cleanup_expired()
        return 0
