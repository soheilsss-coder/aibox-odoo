import json
from odoo import http
from odoo.http import request
from odoo.addons.ai_gateway.controllers.gateway import (
    _authenticate as _gw_authenticate,
    _check_rate_limit as _gw_check_rate_limit,
    _json_response,
    _cors_preflight_response,
)


def _gw_require_auth():
    """(env, error) helper - same contract as ai_semantic_api's, built on
    the gateway's own _authenticate so header-key login works here too."""
    from odoo.http import request as _req

    user, api_key, ip_blocked = _gw_authenticate()
    if ip_blocked:
        return None, _json_response({"error": "too many failed authentication attempts from this address, try again shortly"}, status=429)
    if not user:
        return None, _json_response({"error": "invalid or missing API key"}, status=401)
    if not _gw_check_rate_limit(api_key):
        return None, _json_response({"error": "rate limit exceeded, try again shortly"}, status=429)
    return _req.env(user=user.id), None
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
    @http.route("/api/admin/control-plane", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"])
    def overview(self, **kw):
        # type="json" broke the Nova console (its GET carried no JSON-RPC
        # envelope -> Odoo answered plain 400). Same auth/rate-limit/CORS
        # contract as every other /api/* route, so the bundled UI - which
        # authenticates via X-API-Key from /api/login - can load it.
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _gw_require_auth()
        if err:
            return err
        if "ai.control.authorization" in env:
            try:
                env["ai.control.authorization"].require("customer.config.manage", user=env.user)
            except Exception as exc:
                from odoo.exceptions import AccessError as _AE

                if isinstance(exc, _AE):
                    return _json_response({"error": str(exc)}, status=403)
                raise
        else:
            if not env.user.has_group("base.group_system"):
                return _json_response({"error": "access denied: customer.config.manage"}, status=403)
        company=request.env.company
        designers=env["ai.customer.designer"].sudo().search_count([("company_id","=",company.id)])
        profiles=env["ai.customer.configuration.profile"].sudo().search([("company_id","=",company.id)])
        reviews=env["ai.customer.access.review"].sudo().search_count([("scope_company_id","=",company.id)])
        sso=env["ai.customer.sso.provider"].sudo().search([("company_id","=",company.id)])
        scim=env["ai.customer.scim.token"].sudo().search_count([("company_id","=",company.id),("active","=",True)])
        departments=env["hr.department"].sudo().search_count([])
        positions=env["hr.job"].sudo().search_count([])
        return _json_response({"users": env["res.users"].sudo().search_count([("company_ids","in",company.id)]),
                "departments": departments, "positions": positions,
                "designers": designers, "access_reviews": reviews,
                "configuration_profiles": [{"id":p.id,"name":p.name,"state":p.state,"version":p.version} for p in profiles],
                "sso": [{"name":p.name,"protocol":p.protocol,"active":p.active,"enforce_for_company":p.enforce_for_company} for p in sso],
                "scim_active_tokens": scim,
                "sections":["Users","Departments","Positions","Role Designer","Permission Designer","Policy Designer","Workflow Designer","Approval Matrix Designer","Document Policy Designer","Agent Configuration","Tool Configuration","Excel Import UI","SSO/SCIM","Access Review","Temporary Access","Delegation","Configuration Profile","Deployment Wizard"]})
