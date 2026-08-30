from odoo import http
from odoo.http import request
from odoo.addons.ai_semantic_api.controllers.semantic_api import _require_privileged,_json_response
from odoo.addons.ai_gateway.controllers.gateway import _cors_preflight_response
class AiProductionApi(http.Controller):
 @http.route("/api/admin/release/certify",type="http",auth="none",csrf=False,methods=["POST","OPTIONS"])
 def certify(self,**kw):
  if request.httprequest.method=="OPTIONS":return _cors_preflight_response()
  env,err=_require_privileged();
  if err:return err
  import json
  p=json.loads(request.httprequest.data or b"{}"); r=env["ai.release.certification"].certify(p.get("version") or "candidate"); return _json_response({"id":r.id,"state":r.state,"version":r.version})
