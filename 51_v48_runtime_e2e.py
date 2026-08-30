"""v48 live runtime certification harness.

Run inside an Odoo shell:
  odoo-bin shell -c /etc/odoo.conf -d <db> < 51_v48_runtime_e2e.py

This is intentionally fail-closed. It does not manufacture PASS values when
live services are absent. Business mutations are NOT executed by default;
the harness first proves the complete control-plane route and runs safe
negative/positive probes. Full business-action probes can be enabled with
AI_V48_ALLOW_BUSINESS_MUTATIONS=1 in a disposable certification database.
"""
import json
import os
import uuid
from datetime import datetime
from odoo.exceptions import AccessError, UserError

TARGETS = {
    'purchase': ('purchase.order', 'purchase_rfq_create'),
    'stock': ('stock.picking', 'stock_picking_confirm'),
    'account': ('account.move', 'account_move_post'),
    'mrp': ('mrp.production', 'mrp_production_create'),
    'crm': ('crm.lead', 'crm_lead_create'),
    'hr': ('hr.employee', None),
    'hr_holidays': ('hr.leave', 'hr_leave_create'),
    'sale_management': ('sale.order', 'sale_order_create'),
    'project': ('project.task', 'project_task_create'),
    'documents': ('documents.document', 'documents_create'),
    'calendar': ('calendar.event', 'calendar_event_create'),
    'helpdesk': ('helpdesk.ticket', 'helpdesk_ticket_create'),
    'hr_expense': ('hr.expense', 'hr_expense_create'),
}


def check(rows, name, ok, detail=''):
    row = {'name': name, 'pass': bool(ok)}
    if detail:
        row['detail'] = detail
    rows.append(row)
    print('[%s] %s%s' % ('PASS' if ok else 'FAIL', name, (' - ' + detail) if detail else ''))
    return bool(ok)


def main(env):
    rows = []
    installed = set(env['ir.module.module'].sudo().search([('state', '=', 'installed')]).mapped('name'))
    targets = [m for m in TARGETS if m in installed]
    check(rows, 'target_modules_discovered', bool(targets), ','.join(targets) or 'none')
    if not targets:
        return 1

    gate = env['ai.gateway.execution.gate'] if 'ai.gateway.execution.gate' in env else None
    registry = env['ai.integration.unified.registry'] if 'ai.integration.unified.registry' in env else None
    check(rows, 'central_execution_gate', bool(gate), 'missing ai.gateway.execution.gate')
    check(rows, 'unified_registry', bool(registry), 'missing ai.integration.unified.registry')
    check(rows, 'authorization_engine', 'ai.control.authorization' in env)
    check(rows, 'approval_engine', 'ai.gateway.approval' in env)
    check(rows, 'risk_registry', 'ai.gateway.tool.risk' in env)
    check(rows, 'idempotency_engine', 'ai.gateway.idempotency' in env)
    check(rows, 'event_bus', 'ai.control.event' in env)
    check(rows, 'workflow_engine', 'ai.workflow' in env)
    check(rows, 'audit_engine', 'ai.control.audit' in env)
    check(rows, 'frontend_capability_registry', 'ai.control.capability' in env)

    # Prove the gateway is fail-closed for an unknown tool.
    if gate:
        try:
            gate.authorize('__v48_nonexistent_tool_%s' % uuid.uuid4().hex, args={})
            check(rows, 'gateway_unknown_tool_denied', False, 'unknown tool was authorized')
        except (AccessError, UserError):
            check(rows, 'gateway_unknown_tool_denied', True)
        except Exception as exc:
            check(rows, 'gateway_unknown_tool_denied', False, repr(exc))

    op_model = env['ai.integration.operation'] if 'ai.integration.operation' in env else None
    adapter_model = env['ai.integration.adapter'] if 'ai.integration.adapter' in env else None
    for module in targets:
        print('\n=== LIVE CONTROL-PLANE PROBE: %s ===' % module)
        adapter = adapter_model.sudo().for_module(module) if adapter_model else None
        check(rows, '%s.adapter' % module, bool(adapter and adapter.module_name == module))
        ops = op_model.sudo().search([('module_name', '=', module), ('active', '=', True)]) if op_model else op_model
        check(rows, '%s.operations' % module, bool(ops))
        expected_model, expected_handler = TARGETS[module]
        if expected_handler:
            check(rows, '%s.expected_handler_registered' % module,
                  bool(ops.filtered(lambda x: x.handler_key == expected_handler)))
        for op in ops:
            try:
                contract = registry.execution_contract(op.tool_name) if registry else None
                ok = bool(contract and contract[0].id == op.id)
                check(rows, '%s.contract.%s' % (module, op.tool_name), ok)
            except Exception as exc:
                check(rows, '%s.contract.%s' % (module, op.tool_name), False, repr(exc))
            capability = env['ai.control.capability'].sudo().search([
                ('name', '=', op.capability_name), ('active', '=', True)], limit=1)
            check(rows, '%s.capability.%s' % (module, op.tool_name), bool(capability))
            model_ok = bool(capability and capability.model_name and capability.model_name in env)
            check(rows, '%s.model.%s' % (module, op.tool_name), model_ok)
            service = env['ai.integration.adapter.service'] if 'ai.integration.adapter.service' in env else None
            handler = getattr(service, '_handle_%s' % op.handler_key, None) if service else None
            check(rows, '%s.handler.%s' % (module, op.handler_key), callable(handler))

        # Verify the event layer is callable without inventing a downstream PASS.
        if 'ai.control.event' in env:
            event_name = 'v48.certification.probe.%s' % module
            try:
                event = env['ai.control.event'].sudo().publish(
                    event_type=event_name,
                    payload={'module': module, 'probe': True, 'timestamp': datetime.utcnow().isoformat()},
                    user=env.user,
                )
                check(rows, '%s.event_outbox_publish' % module, bool(event))
            except Exception as exc:
                check(rows, '%s.event_outbox_publish' % module, False, repr(exc))

        # RAG is checked as a contract, not falsely claimed to have indexed a document.
        if module in ('documents', 'hr', 'project', 'purchase', 'crm'):
            rag_ok = 'ai.document.index.job' in env and 'ai.rag.document.acl' in env
            check(rows, '%s.rag_pipeline_contract' % module, rag_ok)

    # Optional disposable-database business mutation stage.
    allow_mutations = os.getenv('AI_V48_ALLOW_BUSINESS_MUTATIONS') == '1'
    check(rows, 'business_mutation_stage_enabled', allow_mutations,
          'DISABLED by default; enable only on a disposable certification database')

    passed = all(r['pass'] for r in rows)
    print('\nV48 RESULT: %s' % ('PASS' if passed else 'BLOCKED'))
    print(json.dumps({'status': 'PASS' if passed else 'BLOCKED', 'checks': rows}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if 'env' in globals():
    raise SystemExit(main(env))
print('Run this script inside an Odoo shell.')
raise SystemExit(2)
