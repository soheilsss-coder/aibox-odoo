import json
import logging

from odoo import api, fields, models

from .context_firewall import scrub_value

_logger = logging.getLogger(__name__)


class AiGatewayAuditLog(models.Model):
    """Append-only record of every AI-driven action: who (real Odoo
    user, never the AI itself), what (tool name or rpc model+operation),
    with what parameters, and whether it succeeded.

    This is the piece that makes "no one can bypass access control"
    checkable rather than just hoped-for: even if something slips past
    the allowlist or an ACL is misconfigured, there is a full trail of
    who asked the assistant to do what, and Odoo's own access control
    result (success/AccessError) for it.
    """

    _name = "ai.gateway.audit.log"
    _description = "AI Gateway Audit Log"
    _order = "create_date desc"
    _log_access = False  # this model must never call itself recursively

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    source = fields.Selection(
        [
            ("tool", "AI Tool Call"),
            ("rpc", "Gateway RPC"),
            ("chat", "Gateway Chat"),
            ("execution_gate", "Execution Gate"),
            ("authorization", "Authorization"),
            ("customer_control_plane", "Customer Control Plane"),
            ("event_bus", "Event Bus"),
            ("workflow", "Workflow"),
        ],
        required=True, index=True,
    )
    action = fields.Char(required=True, index=True, help="Tool name, or 'model.operation' for rpc")
    payload = fields.Text(help="JSON-encoded parameters, truncated to 2000 chars")
    success = fields.Boolean(default=True, index=True)
    error_message = fields.Text()
    duration_ms = fields.Integer(
        help="Wall-clock time the call took, in milliseconds - only populated for "
             "'rpc'/'chat' (measured in the gateway controller); tool calls made "
             "from inside the chat loop don't have a clean single measurement "
             "point, so this stays empty for source='tool' (roadmap #48)."
    )
    token_count = fields.Integer(
        index=True,
        help="Estimated token footprint of the conversation turn, used for the "
             "usage report. The odoo-llm framework doesn't surface provider "
             "usage through thread.generate(), so this is a documented estimate "
             "(chars/4) recorded by the gateway - labelled as such in the report."
    )
    create_date = fields.Datetime(readonly=True, index=True)
    request_id = fields.Char(index=True)
    trace_id = fields.Char(index=True)
    tenant_id = fields.Many2one("res.company", index=True, ondelete="restrict")
    agent_id = fields.Many2one("ai.gateway.agent.identity", index=True, ondelete="set null")
    tool_id = fields.Many2one("llm.tool", index=True, ondelete="set null")
    model_version = fields.Char(index=True)
    approval_id = fields.Integer(index=True)
    before_state = fields.Text()
    after_state = fields.Text()
    prev_hash = fields.Char(index=True)
    entry_hash = fields.Char(index=True)

    @api.model
    def log(self, user_id, source, action, payload=None, success=True, error_message=None, duration_ms=None, token_count=None, context=None):
        # Context Firewall (roadmap #28): scrub before it ever touches
        # the database, not just before it goes back to the model - a
        # tool that carelessly puts a password/token/raw financial
        # value into its own audit payload must not leave it sitting
        # in this table forever either.
        try:
            payload = scrub_value(payload) if payload else payload
        except Exception:  # noqa: BLE001
            pass
        try:
            payload_str = json.dumps(payload, ensure_ascii=False, default=str)[:2000] if payload else False
        except Exception:  # noqa: BLE001
            payload_str = str(payload)[:2000]
        try:
            context = context or {}
            tenant_id = context.get("tenant_id") or self.env.company.id
            # Serialize hash-chain writes in PostgreSQL so concurrent workers
            # cannot both observe the same previous hash. The audit row and
            # the business transaction remain in the same DB transaction.
            self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext('ai_gateway_audit_chain'))")
            prev = self.sudo().search([], order="id desc", limit=1).entry_hash or "GENESIS"
            material = json.dumps({"prev_hash": prev, "user_id": user_id, "source": source, "action": action, "payload": payload_str, "success": success, "request_id": context.get("request_id"), "trace_id": context.get("trace_id"), "token_count": token_count}, sort_keys=True, ensure_ascii=False, default=str)
            entry_hash = __import__("hashlib").sha256(material.encode("utf-8")).hexdigest()
            self.sudo().create({
                "user_id": user_id, "source": source, "action": action, "payload": payload_str,
                "success": success, "error_message": (error_message or "")[:2000] or False,
                "duration_ms": duration_ms, "request_id": context.get("request_id"),
                "trace_id": context.get("trace_id"), "tenant_id": tenant_id,
                "token_count": token_count or 0,
                "agent_id": context.get("agent_id") or False, "tool_id": context.get("tool_id") or False,
                "policy_id": context.get("policy_id") or False, "model_version": context.get("model_version") or False,
                "approval_id": context.get("approval_id") or False, "workflow_id": context.get("workflow_id") or False,
                "before_state": context.get("before_state") and json.dumps(scrub_value(context.get("before_state")), ensure_ascii=False, default=str)[:10000] or False,
                "after_state": context.get("after_state") and json.dumps(scrub_value(context.get("after_state")), ensure_ascii=False, default=str)[:10000] or False,
                "prev_hash": prev, "entry_hash": entry_hash,
            })
        except Exception:  # noqa: BLE001
            # Logging must NEVER be the reason a legitimate action fails.
            _logger.exception("ai.gateway.audit.log: failed to write audit entry")

    @api.model
    def calls_in_last_seconds(self, user_id, seconds=60):
        self.env.cr.execute(
            "SELECT COUNT(*) FROM ai_gateway_audit_log "
            "WHERE user_id = %s AND create_date >= (now() - interval %s)",
            (user_id, f"{seconds} seconds"),
        )
        return self.env.cr.fetchone()[0]

    # -----------------------------------------------------------------
    # Observability (roadmap #48). Deliberately plain SQL, not an ORM
    # read_group pyramid - the roadmap item itself says "even a single
    # SQL query on the audit log is enough"; a fancier metrics store
    # would be solving a problem this project doesn't have yet.
    # -----------------------------------------------------------------
    @api.model
    def observability_snapshot(self):
        """One dict with the handful of numbers that answer 'is the
        system alive, and roughly how busy/healthy is it' - used by
        both GET /api/metrics and 12_observability_report.py so the
        two never drift apart."""
        self.env.cr.execute("""
            SELECT
                count(*) FILTER (WHERE create_date >= now() - interval '1 hour') AS last_hour,
                count(*) FILTER (WHERE create_date >= now() - interval '24 hours') AS last_24h,
                count(*) FILTER (WHERE create_date >= now() - interval '24 hours' AND success = false) AS errors_24h,
                avg(duration_ms) FILTER (WHERE create_date >= now() - interval '24 hours' AND duration_ms IS NOT NULL) AS avg_duration_ms_24h,
                sum(token_count) FILTER (WHERE create_date >= now() - interval '24 hours') AS tokens_24h,
                max(create_date) AS last_call_at
            FROM ai_gateway_audit_log
        """)
        row = self.env.cr.dictfetchone() or {}

        self.env.cr.execute("""
            SELECT action, count(*) AS calls
            FROM ai_gateway_audit_log
            WHERE create_date >= now() - interval '24 hours'
            GROUP BY action
            ORDER BY calls DESC
            LIMIT 5
        """)
        top_actions = self.env.cr.dictfetchall()

        last_24h = row.get("last_24h") or 0
        errors_24h = row.get("errors_24h") or 0
        return {
            "requests_last_hour": row.get("last_hour") or 0,
            "requests_last_24h": last_24h,
            "errors_last_24h": errors_24h,
            "error_rate_24h": round(errors_24h / last_24h, 4) if last_24h else 0.0,
            "avg_duration_ms_24h": round(row["avg_duration_ms_24h"], 1) if row.get("avg_duration_ms_24h") else None,
            "tokens_24h": row.get("tokens_24h") or 0,
            "last_call_at": row.get("last_call_at"),
            "top_actions_24h": top_actions,
        }

    @api.model
    def token_usage_report(self, days=30):
        """Token usage grouped by day, user, and company over the last
        `days` (default 30). token_count is an ESTIMATE (chars/4) recorded
        by the gateway, not provider-reported usage - the report says so
        explicitly so the number is never mistaken for exact billing."""
        self.env.cr.execute("""
            SELECT
                date_trunc('day', create_date)::date AS day,
                (SELECT name FROM res_users u WHERE u.id = ag.user_id) AS user_name,
                (SELECT name FROM res_company c WHERE c.id = ag.tenant_id) AS company_name,
                count(*) AS turns,
                coalesce(sum(ag.token_count), 0) AS tokens_estimated
            FROM ai_gateway_audit_log ag
            WHERE create_date >= now() - (interval '1 day' * %s)
              AND ag.source = 'chat'
            GROUP BY 1, 2, 3
            ORDER BY day DESC, tokens_estimated DESC
            LIMIT 500
        """, (int(days),))
        return {
            "label": "estimated tokens (chars/4, not provider-reported)",
            "days": int(days),
            "rows": [
                {
                    "day": str(r[0]),
                    "user": r[1],
                    "company": r[2],
                    "turns": r[3],
                    "tokens_estimated": r[4],
                }
                for r in self.env.cr.fetchall()
            ],
        }
