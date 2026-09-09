import logging

# Canonical persistence contract: odoo-orm-canonical. Memory is stored and
# filtered through the Odoo ORM model, never a parallel external memory store.
from odoo import api, models
from odoo.addons.llm_tool.decorators import llm_tool

_logger = logging.getLogger(__name__)


class LLMToolAgentMemory(models.Model):
    _inherit = "llm.tool"

    @api.model
    def _current_source_message_id(self):
        source_id = self.env.context.get("memory_source_message_id")
        if source_id:
            return source_id
        thread_id = self.env.context.get("memory_source_thread_id")
        if not thread_id or "mail.message" not in self.env:
            return None
        message = self.env["mail.message"].sudo().search([
            ("model", "=", "llm.thread"), ("res_id", "=", int(thread_id)),
            ("author_id", "=", self.env.user.partner_id.id),
        ], order="id desc", limit=1)
        return message.id if message else None

    @llm_tool(destructive_hint=True)
    def save_memory(self, key: str, value: str, scope: str = "personal") -> dict:
        """Save a user-approved memory value in personal, department or company scope.

        The write is audited and still goes through the execution gate; invalid
        scopes fall back to personal so the assistant cannot widen access by
        inventing a scope name.
        """
        if "ai.gateway.tool.risk" in self.env:
            self.env["ai.gateway.execution.gate"].authorize("save_memory")
        if scope not in ("personal", "department", "company"):
            scope = "personal"
        try:
            rec = self.env["ai.agent.memory.record"].create_memory(key, value, scope=scope, user=self.env.user)
        except Exception as exc:
            _logger.warning("save_memory failed: %s", exc)
            return {"error": "memory_save_failed"}
        fact_id = None
        # Explicit save_memory is a user assertion, so mirror it into the
        # structured fact layer when installed. Legacy storage remains the
        # compatibility source and a fact failure must not lose the save.
        if "ai.agent.memory.fact" in self.env:
            source_message_id = self._current_source_message_id()
            if source_message_id:
                try:
                    fact = self.env["ai.agent.memory.fact"].create_fact(
                        subject="user:%s" % self.env.user.id,
                        predicate=key,
                        object_value=value,
                        scope=scope,
                        user=self.env.user,
                        confirmed=True,
                        confidence=1.0,
                        source_type="explicit_user",
                        source_message_id=source_message_id,
                        source_thread_id=self.env.context.get("memory_source_thread_id"),
                        source_quote=value,
                    )
                    fact_id = fact.id
                except Exception:  # noqa: BLE001
                    _logger.info("structured fact mirror unavailable", exc_info=True)
            else:
                _logger.debug("structured fact mirror skipped: no source message in context")
        if "ai.gateway.audit.log" in self.env:
            self.env["ai.gateway.audit.log"].sudo().log(user_id=self.env.user.id, source="tool", action="save_memory", payload={"key": key, "scope": scope})
        return {"status": "saved", "key": rec.key, "scope": rec.scope, "memory_id": rec.id, "fact_id": fact_id}

    @llm_tool(destructive_hint=True)
    def save_memory_fact(
        self, subject: str, predicate: str, value: str, scope: str = "personal",
        source_message_id: int = 0, source_quote: str = "",
        valid_from: str = "", valid_to: str = "", confidence: float = 1.0,
    ) -> dict:
        """Persist an explicit, source-linked fact with immutable history.

        This tool represents an explicit user-approved assertion. Automatic
        extraction must create candidate facts through a worker and may not
        mark them confirmed without confirmation.
        """
        if "ai.gateway.tool.risk" in self.env:
            self.env["ai.gateway.execution.gate"].authorize("save_memory_fact")
        try:
            fact = self.env["ai.agent.memory.fact"].create_fact(
                subject, predicate, value, scope=scope, user=self.env.user,
                confirmed=True, confidence=confidence,
                source_message_id=source_message_id or self._current_source_message_id(),
                source_thread_id=self.env.context.get("memory_source_thread_id"),
                source_quote=source_quote or value,
                valid_from=valid_from or None, valid_to=valid_to or None,
                source_type="explicit_user",
            )
            return {
                "status": "saved", "fact_id": fact.id, "subject": fact.subject,
                "predicate": fact.predicate, "scope": fact.scope,
                "embedding_state": fact.embedding_state,
            }
        except Exception as exc:  # noqa: BLE001
            _logger.warning("save_memory_fact failed: %s", exc)
            return {"error": "structured memory fact save failed"}

    @llm_tool(destructive_hint=True)
    def confirm_memory_fact(self, fact_id: int) -> dict:
        """Explicitly promote one owned extraction candidate to confirmed."""
        if "ai.gateway.tool.risk" in self.env:
            self.env["ai.gateway.execution.gate"].authorize("confirm_memory_fact")
        try:
            fact = self.env["ai.agent.memory.fact"].confirm_fact(
                fact_id, user=self.env.user,
            )
            if "ai.gateway.audit.log" in self.env:
                self.env["ai.gateway.audit.log"].sudo().log(
                    user_id=self.env.user.id, source="tool", action="confirm_memory_fact",
                    payload={"fact_id": fact.id}, success=True,
                )
            return {"status": "confirmed", "fact_id": fact.id}
        except Exception as exc:  # noqa: BLE001
            _logger.warning("confirm_memory_fact failed: %s", exc)
            return {"error": "memory candidate confirmation failed"}

    @llm_tool(read_only_hint=True)
    def recall_memory_facts(self, query: str = "", include_history: bool = False) -> dict:
        """Recall confirmed structured facts with temporal source citations."""
        try:
            facts = self.env["ai.agent.memory.fact"].search_facts(
                query, user=self.env.user, limit=8, include_history=bool(include_history)
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("structured memory fact search failed: %s", exc)
            return {"error": "structured memory is temporarily unavailable"}
        if not facts:
            return {"error": "No matching structured memories found."}
        result = {"count": len(facts), "facts": facts}
        if hasattr(self, "_context_firewall"):
            result = self._context_firewall(result)
        return result

    @llm_tool(read_only_hint=True)
    def recall_memory(self, query: str = "") -> dict:
        """Return visible legacy memory records, optionally filtered by text query.

        Results are restricted by the memory model's user/company/department
        visibility rules before any decrypted value is returned to the model.
        """
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
