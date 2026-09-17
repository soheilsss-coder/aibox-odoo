import logging

from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LLMToolRagSearch(models.Model):
    _inherit = "llm.tool"

    @llm_tool(read_only_hint=True)
    def search_documents_semantic(self, query: str = "", top_k: int = 5) -> dict:
        """Semantic (meaning-based) search across company documents the
        CURRENT user is allowed to see - use this instead of
        list_documents when the user asks a question ABOUT the
        content of documents ("what does our leave policy say about
        unused vacation days") rather than browsing by name. Returns
        short excerpts with a similarity score, not whole files - call
        get_document for full metadata on a specific result if the
        user wants more.

        Access control note: results are already restricted to
        documents this user is entitled to see (same rule as
        list_documents/get_document) - never mention or reveal that a
        document with a higher access level exists just because a
        search term matched it for someone else.

        Parameters:
            query: The user's question or topic, in their own words -
                do not reduce it to keywords, this is a semantic
                search, not a keyword search.
            top_k: How many excerpts to return (default 5, max 10).
        """
        if not query:
            return {"error": "missing_required_field", "missing_fields": ["query"]}
        try:
            top_k = max(1, min(int(top_k or 5), 10))
        except (TypeError, ValueError):
            return {"error": "top_k must be a bounded integer"}

        try:
            results = self.env["ai.document.chunk"].search_similar(query, top_k=top_k)
        except UserError as exc:
            self.env["ai.gateway.audit.log"].sudo().log(
                user_id=self.env.user.id, source="tool", action="search_documents_semantic",
                payload={"query": query}, success=False, error_message=str(exc),
            )
            return {"error": "semantic search failed, check server logs for details"}
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Semantic document search failed: %s", exc)
            self.env["ai.gateway.audit.log"].sudo().log(
                user_id=self.env.user.id, source="tool", action="search_documents_semantic",
                payload={"query": query}, success=False, error_message="unexpected_search_failure",
            )
            return {"error": "semantic search failed, check server logs for details"}

        result = {
            "count": len(results),
            "results": results,
            "answerability": "supported_context" if results else "insufficient_context",
            "instruction": (
                "Use only these excerpts and cite their document names."
                if results else
                "No sufficiently relevant authorized excerpt was found; do not invent an answer and say that the documents do not establish it."
            ),
        }
        if hasattr(self, "_context_firewall"):
            result = self._context_firewall(result)

        self.env["ai.gateway.audit.log"].sudo().log(
            user_id=self.env.user.id, source="tool", action="search_documents_semantic",
            payload={"query": query, "result_count": len(results)}, success=True,
        )
        return result
