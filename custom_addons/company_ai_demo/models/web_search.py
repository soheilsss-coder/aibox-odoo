import logging

from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool

_logger = logging.getLogger(__name__)


class LLMToolWebSearch(models.Model):
    _inherit = "llm.tool"

    @llm_tool(read_only_hint=True)
    def search_internet(self, query: str, max_results: int = 5, recent_only: bool = True) -> dict:
        """Search the public internet. Always cite the actual titles/URLs
        returned - never answer from training knowledge for time-sensitive
        topics. ALWAYS call get_current_datetime first for news/current
        events questions to know the real year before building the query.

        Parameters:
            query: A clear, specific search query (include the real year
                for time-sensitive topics).
            max_results: How many results to return (default 5, max 10).
            recent_only: If True, restrict to results from the past month.
        """
        if not str(query or "").strip():
            return {"error": "missing_required_field", "missing_fields": ["query"]}
        try:
            max_results = max(1, min(int(max_results), 10))
        except (TypeError, ValueError):
            return {"error": "max_results must be a bounded integer"}
        try:
            from ddgs import DDGS
            kwargs = {"max_results": max_results}
            if recent_only:
                kwargs["timelimit"] = "m"
            results = list(DDGS().text(query, **kwargs))
            if not results:
                return {"error": "No results found."}
            formatted = [
                {"title": r.get("title", ""), "snippet": r.get("body", ""), "url": r.get("href", "")}
                for r in results
            ]
            result = {"query": query, "results": formatted}
            if hasattr(self, "_context_firewall"):
                result = self._context_firewall(result)
            return result
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Web search failed: %s", exc)
            return {"error": "Search failed, try again shortly"}
