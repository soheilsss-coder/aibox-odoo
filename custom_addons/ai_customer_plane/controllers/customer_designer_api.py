import json
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError

class CustomerDesignerApi(http.Controller):
    def _check(self):
        if not request.env.user or request.env.user._is_public(): raise AccessError("authentication_required")
        request.env["ai.control.authorization"].require("customer.config.manage", user=request.env.user)

    @http.route("/api/customer/designers", type="json", auth="user", methods=["POST"], csrf=False)
    def create(self, kind=None, name=None, definition=None, **kw):
        self._check(); definition=definition or {}
        rec=request.env["ai.customer.designer"].create({"kind":kind,"name":name,"definition_json":json.dumps(definition, ensure_ascii=False)})
        return {"id":rec.id,"kind":rec.kind,"name":rec.name,"version":rec.version,"definition":definition}

    @http.route("/api/customer/designers", type="json", auth="user", methods=["GET"], csrf=False)
    def list(self, kind=None, **kw):
        self._check(); domain=[("company_id","=",request.env.company.id)]
        if kind: domain.append(("kind","=",kind))
        rows=request.env["ai.customer.designer"].search(domain)
        return {"items":[{"id":r.id,"kind":r.kind,"name":r.name,"version":r.version,"active":r.active,"definition":json.loads(r.definition_json or "{}")} for r in rows]}

    @http.route("/api/customer/designers/<int:designer_id>", type="json", auth="user", methods=["PATCH"], csrf=False)
    def update(self, designer_id, definition=None, active=None, **kw):
        self._check(); r=request.env["ai.customer.designer"].search([("id","=",designer_id),("company_id","=",request.env.company.id)], limit=1)
        if not r: return {"error":"not_found"}
        vals={}
        if definition is not None: vals["definition_json"]=json.dumps(definition, ensure_ascii=False)
        if active is not None: vals["active"]=bool(active)
        r.write(vals)
        return {"id":r.id,"version":r.version,"definition":json.loads(r.definition_json or "{}"),"active":r.active}

class CustomerControlPlaneApi(http.Controller):
    @http.route("/api/admin/control-plane", type="json", auth="user", methods=["GET"], csrf=False)
    def overview(self, **kw):
        if not request.env.user or request.env.user._is_public():
            raise AccessError("authentication_required")
        request.env["ai.control.authorization"].require("customer.config.manage", user=request.env.user)
        company=request.env.company
        designers=request.env["ai.customer.designer"].search_count([("company_id","=",company.id)])
        profiles=request.env["ai.customer.configuration.profile"].search([("company_id","=",company.id)])
        reviews=request.env["ai.customer.access.review"].search_count([("scope_company_id","=",company.id)])
        sso=request.env["ai.customer.sso.provider"].search([("company_id","=",company.id)])
        scim=request.env["ai.customer.scim.token"].search_count([("company_id","=",company.id),("active","=",True)])
        departments=request.env["hr.department"].search_count([])
        positions=request.env["hr.job"].search_count([])
        return {"users": request.env["res.users"].search_count([("company_ids","in",company.id)]),
                "departments": departments, "positions": positions,
                "designers": designers, "access_reviews": reviews,
                "configuration_profiles": [{"id":p.id,"name":p.name,"state":p.state,"version":p.version} for p in profiles],
                "sso": [{"name":p.name,"protocol":p.protocol,"active":p.active,"enforce_for_company":p.enforce_for_company} for p in sso],
                "scim_active_tokens": scim,
                "sections":["Users","Departments","Positions","Role Designer","Permission Designer","Policy Designer","Workflow Designer","Approval Matrix Designer","Document Policy Designer","Agent Configuration","Tool Configuration","Excel Import UI","SSO/SCIM","Access Review","Temporary Access","Delegation","Configuration Profile","Deployment Wizard"]}
