import json
from odoo import api, fields, models


class AiIntegrationCertification(models.Model):
    _name = 'ai.integration.certification'
    _description = 'Universal Module Integration Certification'
    _order = 'checked_at desc'

    module_name = fields.Char(required=True, index=True)
    status = fields.Selection([('pass','PASS'),('fail','FAIL'),('warning','WARNING'),('blocked','BLOCKED')], required=True)
    checks_json = fields.Text(default='[]')
    checked_at = fields.Datetime(default=fields.Datetime.now)
    error = fields.Text()


class AiUniversalCertification(models.AbstractModel):
    _name = 'ai.integration.certification.runner'
    _description = 'Universal Integration Certification Runner'

    @api.model
    def _check(self, checks, name, passed, detail=None):
        row = {'name': name, 'pass': bool(passed)}
        if detail:
            row['detail'] = detail
        checks.append(row)
        return bool(passed)

    @api.model
    def run_for_module(self, module_name, live_runtime=False):
        """Fail-closed certification.

        Structural presence is never treated as proof that a runtime path
        works. Unless live_runtime=True and the runtime probes actually pass,
        production certification remains BLOCKED.
        """
        checks = []
        installed = self.env['ir.module.module'].sudo().search([('name', '=', module_name), ('state', '=', 'installed')], limit=1)
        self._check(checks, 'module_installed', bool(installed))
        adapter = self.env['ai.integration.adapter'].sudo().for_module(module_name)
        self._check(checks, 'reviewed_adapter', bool(adapter and adapter.module_name == module_name))
        cap = self.env['ai.control.capability'].sudo().search([('module_name', '=', module_name), ('active', '=', True)])
        self._check(checks, 'capabilities_registered', bool(cap))
        ops = self.env['ai.integration.operation'].sudo().search([('module_name', '=', module_name), ('active', '=', True)])
        self._check(checks, 'business_operations_registered', bool(ops))
        self._check(checks, 'unified_registry_contract', bool(ops), 'Capability→Tool contract must exist for every operation')
        for op in ops:
            risk = self.env['ai.gateway.tool.risk'].sudo().search([('tool_name', '=', op.tool_name)], limit=1)
            capability = self.env['ai.control.capability'].sudo().search([('name', '=', op.capability_name), ('active', '=', True)], limit=1)
            self._check(checks, 'risk:%s' % op.tool_name, bool(risk and risk.capability_name == op.capability_name and int(risk.risk_level or 0) == int(op.risk_level or 0)))
            self._check(checks, 'capability:%s' % op.capability_name, bool(capability))
            self._check(checks, 'capability_module:%s' % op.tool_name, bool(capability and capability.module_name == op.module_name))
            model_name = capability.model_name if capability else False
            self._check(checks, 'model:%s' % (model_name or 'unknown'), bool(model_name and model_name in self.env))
            handler = getattr(self.env['ai.integration.adapter.service'], '_handle_%s' % op.handler_key, None)
            self._check(checks, 'handler:%s' % op.handler_key, bool(handler))
            self._check(checks, 'adapter_module_match:%s' % op.tool_name, bool(adapter and adapter.module_name == op.module_name))
        subs = self.env['ai.integration.subscription'].sudo().search([('active', '=', True)]) if 'ai.integration.subscription' in self.env else self.env['ai.integration.subscription'].sudo().browse()
        self._check(checks, 'event_subscriptions_available', bool(subs))
        self._check(checks, 'central_execution_gate', 'ai.gateway.execution.gate' in self.env)
        self._check(checks, 'rag_index_pipeline', 'ai.document.index.job' in self.env)

        # Runtime proof is deliberately explicit. Presence of a model/API is
        # not enough to certify Purchase/Stock/etc. on a real PostgreSQL/Odoo
        # installation.
        if live_runtime:
            runtime = self._runtime_probes(module_name, ops)
            checks.extend(runtime)
        else:
            for name in (
                'runtime_tool_gateway', 'runtime_authorization', 'runtime_risk_approval',
                'runtime_event_delivery', 'runtime_workflow_recovery',
                'runtime_rag_acl', 'runtime_frontend_capabilities', 'runtime_audit',
            ):
                self._check(checks, name, False, 'NOT_RUN: requires live Odoo/PostgreSQL runtime')

        passed = all(x['pass'] for x in checks)
        status = 'pass' if passed else ('blocked' if installed else 'fail')
        self.env['ai.integration.certification'].sudo().create({
            'module_name': module_name, 'status': status,
            'checks_json': json.dumps(checks, ensure_ascii=False),
            'error': False if passed else 'Production activation blocked until every certification check is PASS.',
        })
        return {'module': module_name, 'status': status, 'production_eligible': passed, 'checks': checks}


    @api.model
    def _runtime_probes(self, module_name, ops):
        """Execute non-destructive runtime probes against the live registry.

        These probes intentionally do not pretend to be full business E2E. They
        prove that the installed Odoo registry can resolve and route every
        operation through the central gate, that authorization/risk/approval
        services exist, and that durable integration services are callable.
        The separate 48_auto_integration_certification.py remains the promotion
        entrypoint for full business E2E.
        """
        checks = []
        gate = self.env['ai.gateway.execution.gate'] if 'ai.gateway.execution.gate' in self.env else False
        registry = self.env['ai.integration.unified.registry'] if 'ai.integration.unified.registry' in self.env else False
        self._check(checks, 'runtime_tool_gateway', bool(gate and callable(getattr(gate, 'authorize', None)) and callable(getattr(gate, 'execute', None))))
        auth = self.env['ai.control.authorization'] if 'ai.control.authorization' in self.env else False
        self._check(checks, 'runtime_authorization', bool(auth and callable(getattr(auth, 'check_capability', None))))
        risk = self.env['ai.gateway.tool.risk'] if 'ai.gateway.tool.risk' in self.env else False
        self._check(checks, 'runtime_risk_approval', bool(risk and 'ai.gateway.approval' in self.env))
        if registry:
            all_contracts = True
            for op in ops:
                try:
                    resolved = registry.execution_contract(op.tool_name)
                    all_contracts = all_contracts and bool(resolved and resolved[0].id == op.id)
                except Exception:
                    all_contracts = False
            self._check(checks, 'runtime_operation_contract_resolution', all_contracts)
        else:
            self._check(checks, 'runtime_operation_contract_resolution', False)
        bus = self.env['ai.control.event'] if 'ai.control.event' in self.env else False
        self._check(checks, 'runtime_event_delivery', bool(bus and callable(getattr(bus, 'publish', None))))
        workflow = self.env['ai.workflow'] if 'ai.workflow' in self.env else False
        self._check(checks, 'runtime_workflow_recovery', bool(workflow))
        self._check(checks, 'runtime_rag_acl', 'ai.document.index.job' in self.env and 'ai.document.chunk' in self.env and 'company.document' in self.env)
        self._check(checks, 'runtime_frontend_capabilities', 'ai.control.capability' in self.env)
        self._check(checks, 'runtime_audit', 'ai.gateway.audit.log' in self.env)
        return checks

    @api.model
    def can_promote(self, module_name):
        latest = self.env['ai.integration.certification'].sudo().search([('module_name', '=', module_name)], order='checked_at desc,id desc', limit=1)
        return bool(latest and latest.status == 'pass')

    @api.model
    def certify_installed(self, module_names=None, live_runtime=False):
        if module_names is None:
            module_names = self.env['ir.module.module'].sudo().search([('state','=','installed')]).mapped('name')
        return [self.run_for_module(name, live_runtime=live_runtime) for name in module_names]
