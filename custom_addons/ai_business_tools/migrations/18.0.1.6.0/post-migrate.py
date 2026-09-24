"""Re-seal legacy approval snapshots after adding the company dimension."""

import hashlib
import json

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    for approval in env["ai.gateway.approval"].sudo().search([]):
        snapshot = {
            "name": approval.name,
            "company_id": approval.company_id.id,
            "requested_by_id": approval.requested_by_id.id,
            "approver_group_id": approval.approver_group_id.id,
            "action_model": approval.action_model,
            "action_res_id": approval.action_res_id,
        }
        payload = {
            **snapshot,
            "tool_name": approval.tool_name,
            "tool_args": approval.tool_args,
            "capability_name": approval.capability_name,
        }
        cr.execute(
            """
            UPDATE ai_gateway_approval
               SET policy_snapshot = %s,
                   approval_hash = %s,
                   approval_payload_hash = %s
             WHERE id = %s
            """,
            [
                json.dumps(payload, sort_keys=True, default=str),
                hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest(),
                hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest(),
                approval.id,
            ],
        )
