from urllib.request import urlopen

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


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
    priority = fields.Integer(default=100, index=True)
    max_new_tokens = fields.Integer(default=1024)
    temperature = fields.Float(default=0.2)
    supports_streaming = fields.Boolean(default=False)
    supports_tools = fields.Boolean(default=False)
    prompt_cache_enabled = fields.Boolean(default=True)
    health_state = fields.Selection([
        ("unknown", "Unknown"), ("healthy", "Healthy"),
        ("degraded", "Degraded"), ("offline", "Offline"),
    ], default="unknown", index=True)
    last_health_at = fields.Datetime(index=True)
    consecutive_failures = fields.Integer(default=0)
    promoted_at = fields.Datetime()

    _sql_constraints = [("model_unique", "unique(name, purpose)", "Model profile already exists for this purpose.")]

    def action_promote_from_benchmark(self, report, limits):
        """Promote only a measured, same-run benchmark after explicit checks.

        This method is intentionally admin-only and accepts an in-memory
        report so the server never reads an arbitrary path supplied by a
        model or browser. ``61_v58_capacity_gate.py`` performs the same
        threshold checks outside Odoo; this is the final registry transition
        used by the target's release operator after that gate passes.
        """
        self.ensure_one()
        if not self.env.user.has_group("base.group_system"):
            raise AccessError("Only a system administrator may promote a model.")
        if not isinstance(report, dict) or report.get("schema_version") != 1:
            raise UserError("benchmark report schema is invalid")
        if not isinstance(limits, dict):
            raise UserError("explicit benchmark limits are required")
        summary = report.get("summary") or {}
        evidence = report.get("system_evidence") or {}
        scenario = report.get("scenario")
        expected_purpose = scenario if scenario in ("vision", "embedding") else "chat"
        if (expected_purpose == "vision" and self.purpose != "vision") or (
            expected_purpose == "embedding" and self.purpose != "embedding"
        ) or (expected_purpose == "chat" and self.purpose not in ("chat", "reasoning")):
            raise UserError("benchmark scenario does not match the model purpose")
        try:
            ttft = float((summary.get("ttft_ms") or {}).get("p95"))
            e2e = float((summary.get("e2e_ms") or {}).get("p95"))
            error_rate = float(summary.get("error_rate"))
            completed = int(summary.get("completed"))
            max_ttft = float(limits["max_p95_ttft_ms"])
            max_e2e = float(limits["max_p95_e2e_ms"])
            max_error = float(limits["max_error_rate"])
            min_completed = int(limits["min_completed"])
            security_score = float(limits["security_score"])
            tool_calling_score = float(limits.get("tool_calling_score", 0.0))
            vision_score = float(limits.get("vision_score", 0.0))
        except (KeyError, TypeError, ValueError):
            raise UserError("benchmark report has incomplete numeric metrics")
        dimensions_ok = True
        if self.purpose == "embedding":
            dimensions = {
                item.get("embedding_dimension") for item in (report.get("results") or [])
                if item.get("ok")
            }
            dimensions_ok = dimensions == {1024}
        scores_ok = (
            0.0 <= security_score <= 1.0 and security_score >= 0.9
            and 0.0 <= tool_calling_score <= 1.0
            and 0.0 <= vision_score <= 1.0
            and (self.purpose not in ("chat", "reasoning") or tool_calling_score >= 0.8)
            and (self.purpose != "vision" or vision_score >= 0.8)
        )
        if (
            not all(evidence.get(key) for key in ("gpu_metrics", "queue_metrics", "db_redis_metrics"))
            or max_ttft <= 0 or max_e2e <= 0 or max_error < 0 or min_completed < 1
            or ttft < 0 or e2e < 0 or error_rate < 0 or error_rate > 1
            or ttft > max_ttft or e2e > max_e2e or error_rate > max_error
            or completed < min_completed or not scores_ok or not dimensions_ok
        ):
            raise UserError("benchmark did not satisfy the explicit promotion gate")
        self.write({
            "production": True,
            "health_state": "unknown",
            "promoted_at": fields.Datetime.now(),
            "benchmark_score": max(0.0, min(1.0, 1.0 - error_rate)),
            "security_score": security_score,
            "tool_calling_score": tool_calling_score,
            "vision_score": vision_score,
            "latency_ms": e2e,
        })
        return {"status": "promoted", "profile_id": self.id, "health_state": "unknown"}

    @api.model
    def cron_check_health(self):
        return self.env["ai.model.router"].cron_check_health()


class AiModelRouter(models.AbstractModel):
    _name = "ai.model.router"
    _description = "AI Model Router"

    @api.model
    def route(self, purpose="chat", requires_vision=False, complex_reasoning=False,
              latency_budget_ms=None, requires_tools=True):
        if requires_vision:
            purpose = "vision"
        elif complex_reasoning:
            purpose = "reasoning"
        domain = [
            ("purpose", "=", purpose), ("active", "=", True),
            ("production", "=", True), ("health_state", "=", "healthy"),
        ]
        # Production routing is benchmark-gated. Security/tool-calling are
        # mandatory for agentic models; vision models require a vision score.
        if purpose in ("chat", "reasoning"):
            domain += [("security_score", ">=", 0.9)]
            if requires_tools:
                domain.append(("tool_calling_score", ">=", 0.8))
        if purpose == "vision":
            domain += [("security_score", ">=", 0.9), ("vision_score", ">=", 0.8)]
        if latency_budget_ms:
            domain.append(("latency_ms", "<=", int(latency_budget_ms)))
        rec = self.env["ai.model.profile"].sudo().search(
            domain,
            order="priority asc, benchmark_score desc, latency_ms asc, id asc",
            limit=1,
        )
        if not rec:
            raise ValueError("No benchmark-certified production model is available for purpose=%s" % purpose)
        return rec

    @api.model
    def cron_check_health(self):
        """Probe production profiles without exposing endpoint details.

        Health is operational routing state, not certification. A profile is
        still not routable for production until benchmark/security scores are
        explicitly promoted.
        """
        for profile in self.env["ai.model.profile"].sudo().search([
            ("active", "=", True), ("production", "=", True),
        ]):
            healthy = False
            if profile.endpoint:
                try:
                    with urlopen(profile.endpoint.rstrip("/") + "/models", timeout=3) as response:
                        healthy = 200 <= response.status < 300
                except Exception:  # noqa: BLE001 - health must degrade, not break cron
                    healthy = False
            self.record_health(profile, healthy=healthy)
        return True

    @api.model
    def record_health(self, profile, healthy=True):
        """Update circuit state without exposing provider details to clients."""
        profile = profile.sudo().ensure_one()
        values = {
            "health_state": "healthy" if healthy else "degraded",
            "last_health_at": fields.Datetime.now(),
            "consecutive_failures": 0 if healthy else profile.consecutive_failures + 1,
        }
        if not healthy and values["consecutive_failures"] >= 3:
            values["health_state"] = "offline"
        profile.write(values)
        return values["health_state"]
