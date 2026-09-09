from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool
from odoo.exceptions import AccessError, UserError


class LLMToolGenericRead(models.Model):
    """Conservative read fallback for an automatically discovered module.

    Discovery is an inventory/control-plane operation, not permission to
    expose the ERP ORM to an employee or to the model.  This fallback is
    intentionally limited to system administrators, requires a discovered
    model capability, permits only a small non-relational display contract,
    and removes record ids/technical field metadata from the AI result.
    Source-reviewed business adapters remain the normal user-facing path.
    """
    _inherit = "llm.tool"

    _SAFE_FIELDS = {
        "display_name", "name", "ref", "code", "state", "active",
        "date", "date_start", "date_end", "write_date",
    }
    _SAFE_OPERATORS = {"=", "!=", "ilike", "not ilike", "in", "not in", ">", "<", ">=", "<="}
    _FORBIDDEN_FIELD_PARTS = {
        "password", "secret", "token", "key", "salary", "wage", "bank",
        "iban", "birth", "identification", "passport", "ssn", "national",
        "phone", "email", "street", "address", "zip", "vat", "tax",
        "amount", "price", "cost", "debit", "credit", "margin", "body",
        "description", "note", "comment", "content", "attachment", "file",
    }

    @classmethod
    def _field_allowed(cls, name, field):
        lowered = name.lower()
        return (
            name in cls._SAFE_FIELDS
            and not any(part in lowered for part in cls._FORBIDDEN_FIELD_PARTS)
            and field.type not in {"binary", "html", "one2many", "many2many", "many2one"}
        )

    @classmethod
    def _validated_domain(cls, value, Model):
        try:
            import ast
            parsed = ast.literal_eval(value or "[]")
        except (ValueError, SyntaxError) as exc:
            raise UserError("domain must be a Python literal list of safe search clauses") from exc
        if not isinstance(parsed, list) or len(parsed) > 20:
            raise UserError("domain must be a list with at most 20 clauses")
        validated = []
        logical = {"&", "|", "!"}
        for clause in parsed:
            if isinstance(clause, str) and clause in logical:
                validated.append(clause)
                continue
            if not isinstance(clause, (tuple, list)) or len(clause) != 3:
                raise UserError("domain contains an invalid clause")
            field_name, operator, operand = clause
            if not isinstance(field_name, str) or "." in field_name:
                raise UserError("domain may not traverse relations")
            field = Model._fields.get(field_name)
            if not field or not cls._field_allowed(field_name, field):
                raise UserError("domain field is not in the safe read contract")
            if operator not in cls._SAFE_OPERATORS:
                raise UserError("domain operator is not allowed")
            if isinstance(operand, str) and len(operand) > 200:
                raise UserError("domain value is too long")
            if isinstance(operand, (list, tuple)) and len(operand) > 20:
                raise UserError("domain list is too long")
            validated.append((field_name, operator, operand))
        return validated

    @llm_tool(read_only_hint=True)
    def generic_read(self, model: str, fields: str = "", domain: str = "[]", limit: int = 20) -> dict:
        """Read a small safe-field projection from a discovered model.

        This is an administrator-only fallback for modules without a reviewed
        adapter. It rejects relation traversal and sensitive field names before
        using Odoo record rules to read bounded rows.
        """
        if not model or model not in self.env:
            return {"error": "unknown_model"}
        Model = self.env[model]
        capability = f"{model}.read"
        if "ai.control.authorization" not in self.env:
            raise AccessError("read authorization service is unavailable")
        if not self.env["ai.control.capability"].sudo().search([
            ("name", "=", capability), ("active", "=", True),
        ], limit=1):
            raise AccessError("read capability is not registered for this model")
        # Generic discovery is a privileged fallback.  Ordinary employees
        # must use a source-reviewed operation with an explicit role contract.
        self.env["ai.control.authorization"].require("odoo.generic.read")

        requested = [x.strip() for x in (fields or "").split(",") if x.strip()]
        if not requested:
            requested = [name for name, field in Model._fields.items() if self._field_allowed(name, field)]
        requested = [
            name for name in requested
            if name in Model._fields and self._field_allowed(name, Model._fields[name])
        ]
        if not requested:
            raise UserError("no safe display fields were requested")
        parsed_domain = self._validated_domain(domain, Model)
        try:
            bounded_limit = max(1, min(int(limit or 20), 100))
        except (TypeError, ValueError) as exc:
            raise UserError("limit must be an integer") from exc
        records = Model.search(parsed_domain, limit=bounded_limit)
        raw_rows = records.read(requested)
        # Odoo includes the local id in read payloads even when it is not
        # requested.  It is intentionally removed from the AI-facing result.
        rows = [{key: value for key, value in row.items() if key != "id"} for row in raw_rows]
        return {"count": len(rows), "records": rows}
