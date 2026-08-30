import json, secrets, os
from urllib.parse import urlencode
import requests
from authlib.jose import JsonWebKey, jwt
from odoo import http
from odoo.http import request

def _json(payload,status=200): return request.make_response(json.dumps(payload,default=str),headers=[("Content-Type","application/json")],status=status)
class CustomerSsoController(http.Controller):
    def _provider(self,name): return request.env["ai.customer.sso.provider"].sudo().search([("name","=",name),("active","=",True)],limit=1)
    @http.route("/api/sso/oidc/start",type="http",auth="none",csrf=False,methods=["GET"])
    def oidc_start(self,provider):
        p=self._provider(provider)
        if not p or p.protocol!="oidc" or not p.authorization_url or not p.client_id: return _json({"error":"oidc_provider_not_configured"},400)
        state=secrets.token_urlsafe(32); nonce=secrets.token_urlsafe(32); request.session[f"oidc_state:{provider}"]=state; request.session[f"oidc_nonce:{provider}"]=nonce
        q=urlencode({"response_type":"code","client_id":p.client_id,"redirect_uri":p.redirect_uri,"scope":"openid profile email","state":state,"nonce":nonce})
        return request.redirect(p.authorization_url+("&" if "?" in p.authorization_url else "?")+q)
    @http.route("/api/sso/oidc/callback",type="http",auth="none",csrf=False,methods=["GET"])
    def oidc_callback(self,code=None,state=None,provider=None,**kwargs):
        p=self._provider(provider)
        if not p or not code or state!=request.session.pop(f"oidc_state:{provider}",None): return _json({"error":"invalid_sso_state"},400)
        nonce=request.session.pop(f"oidc_nonce:{provider}",None)
        secret_ref=p.client_secret_ref or ""
        secret=os.environ.get(secret_ref[6:],"") if secret_ref.startswith("env://") else ""
        if not secret: return _json({"error":"oidc_secret_not_configured"},503)
        token=requests.post(p.token_url,data={"grant_type":"authorization_code","code":code,"redirect_uri":p.redirect_uri,"client_id":p.client_id,"client_secret":secret},timeout=10); token.raise_for_status(); data=token.json(); id_token=data.get("id_token")
        if not id_token or not p.jwks_url: return _json({"error":"oidc_id_token_missing"},502)
        keys=requests.get(p.jwks_url,timeout=10); keys.raise_for_status(); claims=jwt.decode(id_token,JsonWebKey.import_key_set(keys.json()),claims_options={"iss":{"essential":True,"value":p.issuer},"aud":{"essential":True,"value":p.client_id},"nonce":{"essential":True,"value":nonce}}); claims.validate()
        subject=str(claims.get(p.claim_user_id or "sub")); email=claims.get(p.claim_email or "email"); user=request.env["ai.customer.external.identity"].sudo().map_identity(p,subject,email,claims.get("name")); raw,expires=request.env["ai.gateway.session"].sudo().issue(user,user_agent=request.httprequest.headers.get("User-Agent")); response=_json({"authenticated":True,"user":{"id":user.id,"name":user.name,"login":user.login},"expires_at":expires}); response.set_cookie("ai_session",raw,max_age=8*3600,httponly=True,secure=True,samesite="None",path="/"); return response
    @http.route("/api/sso/saml/metadata",type="http",auth="none",csrf=False,methods=["GET"])
    def saml_metadata(self,provider):
        p=self._provider(provider)
        if not p or p.protocol!="saml": return _json({"error":"saml_provider_not_configured"},404)
        return _json({"provider":p.name,"entity_id":p.saml_entity_id or p.issuer,"acs":"/api/sso/saml/acs","metadata_url":p.saml_metadata_url})
    @http.route("/api/sso/saml/acs",type="http",auth="none",csrf=False,methods=["POST"])
    def saml_acs(self,provider=None,**kwargs):
        p=self._provider(provider)
        if not p or p.protocol!="saml": return _json({"error":"saml_provider_not_configured"},404)
        try:
            from onelogin.saml2.auth import OneLogin_Saml2_Auth
            form=request.httprequest.form.to_dict(flat=False)
            settings={"sp":{"entityId":p.saml_entity_id or "odoo-ai","assertionConsumerService":{"url":request.httprequest.host_url.rstrip("/")+"/api/sso/saml/acs"}},"idp":{"entityId":p.issuer,"singleSignOnService":{"url":p.authorization_url},"x509cert":os.environ.get((p.client_secret_ref or "").replace("env://",""),"")}}
            auth=OneLogin_Saml2_Auth(request.httprequest.environ,old_settings=settings); auth.process_response({k:v[-1] for k,v in form.items()})
            if not auth.is_authenticated(): return _json({"error":"saml_authentication_failed"},401)
            attrs=auth.get_attributes(); subject=auth.get_nameid(); email=(attrs.get(p.claim_email or "email") or [None])[0]; user=request.env["ai.customer.external.identity"].sudo().map_identity(p,subject,email,(attrs.get("name") or [email])[0] if email else subject); raw,expires=request.env["ai.gateway.session"].sudo().issue(user,user_agent=request.httprequest.headers.get("User-Agent")); response=_json({"authenticated":True,"user":{"id":user.id,"name":user.name,"login":user.login},"expires_at":expires}); response.set_cookie("ai_session",raw,max_age=8*3600,httponly=True,secure=True,samesite="None",path="/"); return response
        except Exception:
            return _json({"error":"saml_validation_failed"},502)
