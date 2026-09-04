import logging

# Canonical persistence contract: odoo-orm-canonical. Memory is stored and
# filtered through the Odoo ORM model, never a parallel external memory store.
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
        return {"status": "saved", "key": rec.key, "scope": rec.scope, "memory_id": rec.id}

    @llm_tool(read_only_hint=True)
    def recall_memory(self, query: str = "") -> dict:
        Memory = self.env["ai.agent.memory.record"]
        # The common no-query path reads only the newest ten records. A
        # bounded scan is used for encrypted-value search so a runaway memory
        # table cannot add unbounded decryption latency to a chat turn.
        try:
            records = Memory.visible_for(
                self.env.user,
                limit=10 if not query else 500,
                query=query if query else "",
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("memory search unavailable: %s", exc)
            return {"error": "memory is temporarily unavailable"}
        if query:
            q = query.casefold().strip()
            # Rows created before the token index migration have no digest;
            # bounded fallback keeps upgrades usable while the migration is
            # completed, without returning unverified memory content.
            if not records:
                records = Memory.visible_for(self.env.user, limit=500)
            matched = []
            for record in records:
                if q in (record.key or "").casefold() or q in (Memory._decrypt(record.value) or "").casefold():
                    matched.append(record)
            records = Memory.browse([record.id for record in matched[:10]])
        result = {"memories": [{"key": r.key, "value": Memory._decrypt(r.value), "saved_at": r.created_at, "scope": r.scope, "source": r.source} for r in records]}
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
