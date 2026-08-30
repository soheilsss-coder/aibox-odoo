from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool
from odoo.exceptions import AccessError, UserError


class LLMToolGenericRead(models.Model):
    """Safe generic READ adapter for newly installed Odoo modules.

    This is intentionally READ-only: no create/write/unlink, no method
    dispatch, no sudo, and no arbitrary SQL. The model must have a discovered
    <model>.read capability; the actual query then runs as the authenticated
    Odoo user so ACLs and record rules remain the second enforcement layer.
    """
    _inherit = "llm.tool"

    _SENSITIVE_FIELDS = {
        "password", "password_crypt", "api_key", "secret", "client_secret",
        "access_token", "refresh_token", "token", "private_key", "ssh_key",
        "database_password", "webhook_secret",
    }

    @llm_tool(read_only_hint=True)
    def generic_read(self, model: str, fields: str = "", domain: str = "[]", limit: int = 20) -> dict:
        if not model or model not in self.env:
            return {"error": "unknown_model"}
        Model = self.env[model]
        capability = f"{model}.read"
        if "ai.control.authorization" not in self.env:
            raise AccessError("read authorization service is unavailable")
        # Discovery must have registered this exact model before the AI can
        # query it. The tool never creates capabilities on demand.
        if not self.env["ai.control.capability"].sudo().search([("name", "=", capability), ("active", "=", True)], limit=1):
            raise AccessError("read capability is not registered for this model")
        self.env["ai.control.authorization"].require("odoo.generic.read")

        try:
            import ast
            parsed_domain = ast.literal_eval(domain or "[]")
        except (ValueError, SyntaxError) as exc:
            raise UserError("domain must be a Python literal list of Odoo search clauses") from exc
        if not isinstance(parsed_domain, list) or len(parsed_domain) > 20:
            raise UserError("domain must be a list with at most 20 clauses")
        limit = max(1, min(int(limit or 20), 100))

        requested = [x.strip() for x in (fields or "").split(",") if x.strip()]
        if not requested:
            requested = [f for f in Model._fields if f not in self._SENSITIVE_FIELDS and not f.endswith("_password")]
        requested = [f for f in requested if f in Model._fields and f not in self._SENSITIVE_FIELDS and not f.endswith("_password")]
        if not requested:
            raise UserError("no readable fields were requested")
        records = Model.search(parsed_domain, limit=limit)
        rows = records.read(requested)
        return {"model": model, "count": len(rows), "fields": requested, "records": rows}
