import json
from odoo import http
from odoo.http import request
from odoo.addons.ai_semantic_api.controllers.semantic_api import _require_auth,_json_response
from odoo.addons.ai_gateway.controllers.gateway import _cors_preflight_response
class AiCollabApi(http.Controller):
 @http.route("/api/collaboration/workspaces",type="http",auth="none",csrf=False,methods=["GET","POST","OPTIONS"])
 def workspaces(self,**kw):
  if request.httprequest.method=="OPTIONS": return _cors_preflight_response()
  env,err=_require_auth();
  if err:return err
  m=env["ai.collab.workspace"]
  if request.httprequest.method=="POST":
   p=json.loads(request.httprequest.data or b"{}"); members=set(p.get("member_ids") or [])|{env.user.id}; w=m.create({"name":p.get("name") or "Workspace","kind":p.get("kind") or "team","department_id":p.get("department_id"),"member_ids":[(6,0,list(members))],"agent_name":p.get("agent_name") or "Company Assistant"}); return _json_response({"id":w.id,"name":w.name},201)
  ws=m.search([("member_ids","in",env.user.id)])
  return _json_response({"workspaces":[{"id":w.id,"name":w.name,"kind":w.kind,"agent":w.agent_name} for w in ws]})
 @http.route("/api/collaboration/messages",type="http",auth="none",csrf=False,methods=["GET","POST","OPTIONS"])
 def messages(self,**kw):
  if request.httprequest.method=="OPTIONS":return _cors_preflight_response()
  env,err=_require_auth();
  if err:return err
  m=env["ai.collab.message"]
  if request.httprequest.method=="POST":
   p=json.loads(request.httprequest.data or b"{}"); w=env["ai.collab.workspace"].browse(int(p.get("workspace_id"))).exists()
   if not w or (env.user not in w.member_ids and not env.user.has_group("base.group_system")): return _json_response({"error":"workspace access denied"},403)
   msg=m.create({"workspace_id":w.id,"body":p.get("body") or "","message_type":"user"}); return _json_response({"id":msg.id,"created_at":str(msg.created_at)},201)
  wid=int(request.params.get("workspace_id") or 0); w=env["ai.collab.workspace"].browse(wid).exists();
  if not w or (env.user not in w.member_ids and not env.user.has_group("base.group_system")): return _json_response({"error":"workspace access denied"},403)
  msgs=m.search([("workspace_id","=",w.id)],order="id",limit=200); return _json_response({"messages":[{"id":x.id,"author":x.author_id.name,"body":x.body,"type":x.message_type,"created_at":str(x.created_at)} for x in reversed(msgs)]})
 @http.route("/api/collaboration/channels",type="http",auth="none",csrf=False,methods=["GET","POST","OPTIONS"])
 def channels(self,**kw):
  if request.httprequest.method=="OPTIONS":return _cors_preflight_response()
  env,err=_require_auth();
  if err:return err
  channel_model=env["mail.channel"]
  if request.httprequest.method=="POST":
   p=json.loads(request.httprequest.data or b"{}")
   channel_id=int(p.get("channel_id") or 0)
   channel=channel_model.browse(channel_id).exists()
   if not channel: return _json_response({"error":"channel not found"},404)
   member_of = any(m.partner_id.id==env.user.partner_id.id for m in channel.channel_member_ids)
   if not member_of and not env.user.has_group("base.group_system"): return _json_response({"error":"you are not a member of this channel"},403)
   trigger=(p.get("trigger") or "").strip()
   if not trigger: return _json_response({"error":"'trigger' text is required"},400)
   link=env["ai.collab.channel.link"].search([("channel_id","=",channel.id)],limit=1)
   vals={"channel_id":channel.id,"trigger_text":trigger,"created_by_id":env.user.id}
   if link: link.write(vals); link.write({"active":True})
   else: env["ai.collab.channel.link"].create(vals)
   return _json_response({"status":"opted_in","channel_id":channel.id,"trigger":trigger})
  links=env["ai.collab.channel.link"].sudo().search([])
  member_channels=channel_model.search([]).filtered(lambda c: any(m.partner_id.id==env.user.partner_id.id for m in c.channel_member_ids))
  link_map={l.channel_id.id:l for l in links}
  return _json_response({"channels":[{"id":c.id,"name":c.name,
      "opted_in":c.id in link_map and link_map[c.id].active,
      "trigger":link_map[c.id].trigger_text if c.id in link_map else None} for c in member_channels]})
 @http.route("/api/collaboration/channels/optout",type="http",auth="none",csrf=False,methods=["POST","OPTIONS"])
 def channel_optout(self,**kw):
  if request.httprequest.method=="OPTIONS":return _cors_preflight_response()
  env,err=_require_auth();
  if err:return err
  p=json.loads(request.httprequest.data or b"{}")
  channel_id=int(p.get("channel_id") or 0)
  link=env["ai.collab.channel.link"].sudo().search([("channel_id","=",channel_id)],limit=1)
  if not link: return _json_response({"error":"channel was not opted in"},404)
  if link.created_by_id.id!=env.user.id and not env.user.has_group("base.group_system"):
   return _json_response({"error":"you are not the opt-in owner"},403)
  link.write({"active":False})
  return _json_response({"status":"opted_out","channel_id":channel_id})
