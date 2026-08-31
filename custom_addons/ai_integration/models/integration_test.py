from odoo import api, fields, models


class AiIntegrationHealth(models.Model):
    _name = "ai.integration.health"
    _description = "AI Integration Health Check"
    _order = "checked_at desc"

    module_name = fields.Char(required=True, index=True)
    status = fields.Selection([("pass", "PASS"), ("fail", "FAIL"), ("warning", "WARNING")], required=True)
    checks_json = fields.Text(default="[]")
    error = fields.Text()
    checked_at = fields.Datetime(default=fields.Datetime.now)


class AiIntegrationTestRunner(models.AbstractModel):
    _name = "ai.integration.test.runner"
    _description = "Integration Test Runner"

    @api.model
    def run_for_module(self, module_name):
        checks=[]
        mod=self.env["ai.control.module"].sudo().search([("technical_name","=",module_name)],limit=1)
        checks.append({"name":"module_discovered","pass":bool(mod)})
        adapter=self.env["ai.integration.adapter"].sudo().for_module(module_name)
        checks.append({"name":"reviewed_adapter_or_discovery","pass":bool(adapter or (mod and mod.discovered_models))})
        caps=self.env["ai.control.capability"].sudo().search([("module_name","=",module_name),("active","=",True)])
        checks.append({"name":"capabilities_registered","pass":bool(caps)})
        ops=self.env["ai.integration.operation"].sudo().search([("module_name","=",module_name),("active","=",True)])
        reviewed_ops = ops.filtered(lambda op: op.source == "reviewed" and op.coverage == "reviewed_operational")
        checks.append({"name":"business_adapters_or_explicit_read_only","pass":bool(reviewed_ops or (ops and all(op.coverage in ("discovered_read", "reviewed_read") for op in ops)))})
        for op in ops:
            risk=self.env["ai.gateway.tool.risk"].sudo().search([("tool_name","=",op.tool_name)],limit=1)
            cap=self.env["ai.control.capability"].sudo().search([("name","=",op.capability_name),("active","=",True)],limit=1)
            handler=getattr(self.env["ai.integration.adapter.service"],"_handle_%s" % op.handler_key,None)
            checks.extend([
                {"name":"risk:%s"%op.tool_name,"pass":bool(risk and risk.capability_name==op.capability_name)},
                {"name":"capability:%s"%op.capability_name,"pass":bool(cap)},
                {"name":"handler:%s"%op.handler_key,"pass":bool(handler)},
            ])
        subs=self.env["ai.integration.subscription"].sudo().search([("active","=",True)])
        targets=set(subs.mapped("target"))
        checks.append({"name":"event_subscribers","pass":set(["workflow","ai","notification","calendar","buzz","telegram","memory","audit","rag"]).issubset(targets)})
        mappings = self.env["ai.integration.event.mapping"].sudo().search([("module_name", "=", module_name), ("active", "=", True)]) if "ai.integration.event.mapping" in self.env else None
        checks.append({"name":"event_mapping_baseline","pass":bool(mappings or not mod or not mod.discovered_models)})
        checks.append({"name":"change_outbox","pass":"ai.integration.change.outbox" in self.env})
        checks.append({"name":"frontend_capabilities","pass":"ai.control.capability" in self.env})
        checks.append({"name":"audit","pass":"ai.gateway.audit.log" in self.env})
        checks.append({"name":"rag_acl","pass":"ai.document.index.job" in self.env and "ai.document.chunk" in self.env})
        checks.append({"name":"authorization","pass":"ai.control.authorization" in self.env})
        passed=all(c["pass"] for c in checks)
        health=self.env["ai.integration.health"].sudo().create({"module_name":module_name,"status":"pass" if passed else "fail","checks_json":__import__("json").dumps(checks,ensure_ascii=False)})
        return {"module":module_name,"status":health.status,"checks":checks}

