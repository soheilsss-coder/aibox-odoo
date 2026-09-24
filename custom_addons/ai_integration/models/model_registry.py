from odoo import api, fields, models


class AiModelProfile(models.Model):
    _name = "ai.model.profile"
    _description = "AI Model Registry"
    _order = "purpose, name"

    name = fields.Char(required=True)
    provider = fields.Char(required=True)
    endpoint = fields.Char()
    model_id = fields.Char(required=True)
    purpose = fields.Selection([
        ("chat", "Chat"), ("reasoning", "Reasoning"), ("vision", "Vision"),
        ("embedding", "Embedding"), ("rerank", "Rerank"),
    ], required=True)
    quantization = fields.Char()
    context_length = fields.Integer()
    vram_gb = fields.Float()
    latency_ms = fields.Float()
    cost_per_1k = fields.Float()
    version = fields.Char()
    active = fields.Boolean(default=True)
    production = fields.Boolean(default=False)
    metadata_json = fields.Text(default="{}")
    capabilities_json = fields.Text(default="[]")
    benchmark_score = fields.Float(default=0.0)
    security_score = fields.Float(default=0.0)
    tool_calling_score = fields.Float(default=0.0)
    rag_score = fields.Float(default=0.0)
    vision_score = fields.Float(default=0.0)
    canary_percent = fields.Integer(default=0)
    promoted_at = fields.Datetime()

    _sql_constraints = [("model_unique", "unique(name, purpose)", "Model profile already exists for this purpose.")]


class AiModelRouter(models.AbstractModel):
    _name = "ai.model.router"
    _description = "AI Model Router"

    @api.model
    def route(self, purpose="chat", requires_vision=False, complex_reasoning=False):
        if requires_vision:
            purpose = "vision"
        elif complex_reasoning:
            purpose = "reasoning"
        domain = [("purpose", "=", purpose), ("active", "=", True), ("production", "=", True)]
        # Production routing is benchmark-gated. Security/tool-calling are
        # mandatory for agentic models; vision models require a vision score.
        if purpose in ("chat", "reasoning"):
            domain += [("security_score", ">=", 0.9), ("tool_calling_score", ">=", 0.8)]
        if purpose == "vision":
            domain += [("security_score", ">=", 0.9), ("vision_score", ">=", 0.8)]
        rec = self.env["ai.model.profile"].sudo().search(domain, order="benchmark_score desc, latency_ms asc, id asc", limit=1)
        if not rec:
            raise ValueError("No benchmark-certified production model is available for purpose=%s" % purpose)
        return rec
