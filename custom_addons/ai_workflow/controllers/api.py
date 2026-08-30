import json
from odoo import http, fields
from odoo.http import request
from odoo.addons.ai_semantic_api.controllers.semantic_api import _require_auth, _json_response
from odoo.addons.ai_gateway.controllers.gateway import _cors_preflight_response


class AiWorkflowApi(http.Controller):
    @http.route("/api/workflows/runs", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def runs(self, **kw):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        rows = env["ai.workflow.run"].search([("company_id", "=", env.company.id)], order="id desc", limit=100)
        return _json_response({"runs": [{
            "id": r.id, "workflow": r.workflow_id.name, "state": r.state,
            "step_index": r.step_index, "attempts": r.attempts,
            "waiting_reason": r.waiting_reason or "",
            "next_run_at": str(r.next_run_at or ""),
            "error": r.error or "",
        } for r in rows]})

    @http.route("/api/workflows/approvals/<int:approval_id>", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"])
    def decide_approval(self, approval_id, **kw):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        body = request.httprequest.get_json(silent=True) or {}
        decision = body.get("decision")
        approval = env["ai.workflow.approval"].sudo().browse(approval_id).exists()
        if not approval or approval.run_id.company_id != env.company:
            return _json_response({"error": "approval_not_found"}, status=404)
        try:
            approval.with_user(env.user).decide(decision, body.get("comment"))
        except (PermissionError, ValueError):
            return _json_response({"error": "decision rejected: insufficient permission or invalid decision"}, status=403)
        approval.run_id.sudo().write({
            "state": "queued", "next_run_at": fields.Datetime.now(),
            "waiting_until": False, "waiting_reason": False,
        })
        return _json_response({"ok": True, "state": approval.state})
