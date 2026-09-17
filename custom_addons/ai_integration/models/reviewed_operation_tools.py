import json

from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool
from odoo.exceptions import UserError


class LLMToolReviewedOperation(models.Model):
    """Expose reviewed ERP adapters to the assistant without generic ORM.

    The operation name is resolved only against ``ai.integration.operation``;
    the adapter, capability, risk and approval checks remain in the central
    execution gate. The JSON argument envelope is deliberately bounded and
    must be an object, so free-form model text is never executed as code.
    """

    _inherit = "llm.tool"

    @llm_tool(destructive_hint=True)
    def run_reviewed_operation(self, operation: str, arguments_json: str = "{}") -> dict:
        """Execute one source-reviewed ERP operation through the guarded registry.

        The operation must already be registered and authorized; arguments are
        accepted only as a bounded JSON object and are audited by the execution
        gate before the adapter mutates business data.
        """
        operation = str(operation or "").strip()
        if not operation or len(operation) > 160:
            raise UserError("a reviewed operation name is required")
        if len(str(arguments_json or "{}")) > 12000:
            raise UserError("operation arguments are too large")
        try:
            arguments = json.loads(arguments_json or "{}")
        except (TypeError, ValueError) as exc:
            raise UserError("operation arguments must be valid JSON") from exc
        if not isinstance(arguments, dict):
            raise UserError("operation arguments must be a JSON object")
        if "ai.gateway.execution.gate" not in self.env:
            raise UserError("secure operation service is unavailable")
        self.env["ai.gateway.execution.gate"].authorize(
            "run_reviewed_operation",
            args={"operation": operation, "arguments_json": arguments_json or "{}"},
            context_label="assistant-reviewed-operation",
        )
        registry = self.env["ai.integration.unified.registry"]
        if not registry.resolve(operation):
            raise UserError("reviewed operation is unavailable")
        result = registry.execute(operation, arguments)
        return {"status": "completed", "result": result}
