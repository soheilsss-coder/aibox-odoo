import json
from odoo import http
from odoo.http import request
from odoo.addons.ai_semantic_api.controllers.semantic_api import _require_auth,_json_response
from odoo.addons.ai_gateway.controllers.gateway import _cors_preflight_response
class AiCorrespondenceApi(http.Controller):
 @http.route("/api/correspondence/templates",type="http",auth="none",csrf=False,methods=["GET","OPTIONS"])
 def templates(self,**kw):
  if request.httprequest.method=="OPTIONS":return _cors_preflight_response()
  env,err=_require_auth();
  if err:return err
  rows=[]
  for t in env["ai.correspondence.template"].search([("active","=",True)]):
   if t.group_ids and not (set(t.group_ids.ids)&set(env.user.groups_id.ids)): continue
   rows.append({"id":t.id,"name":t.name,"code":t.code,"required_fields":json.loads(t.required_fields_json or "[]")})
  return _json_response({"templates":rows})
 @http.route("/api/correspondence/validate",type="http",auth="none",csrf=False,methods=["POST","OPTIONS"])
 def validate(self,**kw):
  if request.httprequest.method=="OPTIONS":return _cors_preflight_response()
  env,err=_require_auth();
  if err:return err
  p=json.loads(request.httprequest.data or b"{}"); t=env["ai.correspondence.template"].browse(int(p.get("template_id"))).exists()
  if not t:return _json_response({"error":"template not found"},404)
  if t.group_ids and not(set(t.group_ids.ids)&set(env.user.groups_id.ids)):return _json_response({"error":"template access denied"},403)
  missing=env["ai.correspondence"].validate_values(t,p.get("values") or {}); return _json_response({"valid":not missing,"missing":missing})
