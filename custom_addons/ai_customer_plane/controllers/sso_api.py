import json
import os
import secrets
from urllib.parse import urlencode, urlparse

import requests
from authlib.jose import JsonWebKey, jwt
from odoo import http
from odoo.http import request

from odoo.addons.ai_gateway.controllers.rate_limit import allow

_SSO_RATE_LIMIT = int(os.environ.get("AI_SSO_RATE_LIMIT", "60"))


def _json(payload, status=200):
    return request.make_response(
        json.dumps(payload, default=str),
        headers=[("Content-Type", "application/json")],
        status=status,
    )


def _provider_url(value, field):
    parsed = urlparse((value or "").strip())
    if parsed.scheme == "https" and parsed.netloc:
        return value.strip()
    if os.environ.get("AI_GATEWAY_ENV") == "production":
        raise ValueError("SSO provider URLs must use HTTPS in production")
    # Plain HTTP is only acceptable for an explicitly local development IdP.
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return value.strip()
    raise ValueError("SSO %s must use HTTPS (or a local development endpoint)" % field)


def _sso_allowed():
    return allow(request.httprequest.remote_addr or "", _SSO_RATE_LIMIT, prefix="ai:sso:ip")


class CustomerSsoController(http.Controller):
    def _redirect_uri(self, provider):
        configured = (provider.redirect_uri or "").strip()
        if configured.startswith(("https://", "http://")):
            return _provider_url(configured, "redirect_uri")
        base = (os.environ.get("AI_SSO_PUBLIC_BASE_URL") or
                request.httprequest.url_root.rstrip("/"))
        if not base.startswith("https://") and os.environ.get("AI_GATEWAY_ENV") == "production":
            raise ValueError("AI_SSO_PUBLIC_BASE_URL must be HTTPS in production")
        return base.rstrip("/") + "/" + configured.lstrip("/")

    def _validate_oidc_provider(self, provider):
        for field in ("authorization_url", "token_url", "jwks_url"):
            _provider_url(getattr(provider, field, ""), field)
        return provider

    def _validate_saml_provider(self, provider):
        for field in ("authorization_url", "saml_metadata_url"):
            value = getattr(provider, field, "")
            if value:
                _provider_url(value, field)
        return provider
    def _provider(self, name=None, company_id=None, provider_id=None):
        Provider = request.env["ai.customer.sso.provider"].sudo()
        if provider_id:
            try:
                provider_id = int(provider_id)
            except (TypeError, ValueError):
                return Provider.browse()
            return Provider.search([("id", "=", provider_id), ("active", "=", True)], limit=1)
        if not name:
            return Provider.browse()
        domain = [("name", "=", name), ("active", "=", True)]
        if company_id:
            try:
                domain.append(("company_id", "=", int(company_id)))
            except (TypeError, ValueError):
                return Provider.browse()
        providers = Provider.search(domain)
        # Provider names are unique per company, not globally. Never choose
        # an arbitrary tenant when the public identifier is ambiguous.
        return providers if len(providers) == 1 else Provider.browse()

    def _assert_company_binding(self, provider, company_id):
        if not provider.enforce_for_company:
            return True
        try:
            return int(company_id or 0) == provider.company_id.id
        except (TypeError, ValueError):
            return False

    def _claim_values(self, claims, claim_name):
        value = claims.get(claim_name or "groups", []) if isinstance(claims, dict) else []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (tuple, list, set)):
            return [str(item) for item in value if item not in (None, "")]
        return []

    def _sync_claim_groups(self, provider, user, claims):
        """Apply only explicitly configured IdP→product-role mappings.

        Existing assignments managed by this provider are replaced atomically;
        admin, Excel, SCIM and department assignments are never touched.
        """
        raw_mapping = provider.claim_group_mapping_json or "{}"
        try:
            mapping = json.loads(raw_mapping)
        except (TypeError, ValueError):
            raise ValueError("SSO group mapping is invalid")
        if not isinstance(mapping, dict):
            raise ValueError("SSO group mapping must be an object")
        claim_groups = self._claim_values(claims, provider.claim_groups)
        target_xmlids = []
        for claim_group in claim_groups:
            target = mapping.get(claim_group)
            if isinstance(target, str):
                target = [target]
            if isinstance(target, list):
                target_xmlids.extend(str(item) for item in target)
        groups = []
        for xmlid in sorted(set(target_xmlids)):
            group = request.env.ref(xmlid, raise_if_not_found=False)
            external = group.get_external_id().get(group.id, "") if group else ""
            if not group or not external.startswith("ai_business_tools.role_"):
                raise ValueError("SSO group mapping contains an unknown product role")
            groups.append(group)
        Assignment = request.env["ai.customer.role.assignment"].sudo()
        Assignment.search([
            ("user_id", "=", user.id), ("company_id", "=", provider.company_id.id),
            ("managed_by", "=", "sso"),
        ]).unlink()
        Assignment.create([{
            "user_id": user.id,
            "role_group_id": group.id,
            "source": "direct",
            "company_id": provider.company_id.id,
            "managed_by": "sso",
            "reason": "SSO claim group synchronization",
        } for group in groups])

    def _issue_session(self, provider, user):
        raw, expires = request.env["ai.gateway.session"].sudo().issue(
            user, user_agent=request.httprequest.headers.get("User-Agent"))
        response = _json({
            "authenticated": True,
            "user": {"id": user.id, "name": user.name, "login": user.login},
            "expires_at": expires,
            "company_id": provider.company_id.id,
        })
        response.set_cookie(
            "ai_session", raw, max_age=8 * 3600, httponly=True,
            secure=True, samesite="None", path="/",
        )
        return response

    @http.route("/api/sso/oidc/start", type="http", auth="none", csrf=False, methods=["GET"])
    def oidc_start(self, provider, company_id=None):
        if not _sso_allowed():
            return _json({"error": "sso_rate_limited"}, 429)
        p = self._provider(provider, company_id=company_id)
        if not p or p.protocol != "oidc" or not p.authorization_url or not p.client_id:
            return _json({"error": "oidc_provider_not_configured"}, 400)
        if not self._assert_company_binding(p, company_id):
            return _json({"error": "sso_company_binding_required"}, 403)
        try:
            self._validate_oidc_provider(p)
            redirect_uri = self._redirect_uri(p)
        except ValueError:
            return _json({"error": "oidc_provider_url_invalid"}, 400)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        request.session["oidc_state"] = state
        request.session["oidc_nonce"] = nonce
        request.session["oidc_provider_id"] = p.id
        request.session["oidc_company_id"] = p.company_id.id
        q = urlencode({
            "response_type": "code", "client_id": p.client_id,
            "redirect_uri": redirect_uri, "scope": "openid profile email",
            "state": state, "nonce": nonce,
        })
        return request.redirect(p.authorization_url + ("&" if "?" in p.authorization_url else "?") + q)

    @http.route("/api/sso/oidc/callback", type="http", auth="none", csrf=False, methods=["GET"])
    def oidc_callback(self, code=None, state=None, provider=None, **kwargs):
        if not _sso_allowed():
            return _json({"error": "sso_rate_limited"}, 429)
        expected_state = request.session.pop("oidc_state", None)
        nonce = request.session.pop("oidc_nonce", None)
        provider_id = request.session.pop("oidc_provider_id", None)
        company_id = request.session.pop("oidc_company_id", None)
        p = self._provider(provider_id=provider_id)
        if provider and (not p or provider != p.name):
            return _json({"error": "invalid_sso_provider"}, 400)
        if not p or not code or state != expected_state or not self._assert_company_binding(p, company_id):
            return _json({"error": "invalid_sso_state"}, 400)
        try:
            self._validate_oidc_provider(p)
            redirect_uri = self._redirect_uri(p)
        except ValueError:
            return _json({"error": "oidc_provider_url_invalid"}, 400)
        secret_ref = p.client_secret_ref or ""
        secret = os.environ.get(secret_ref[6:], "") if secret_ref.startswith("env://") else ""
        if not secret:
            return _json({"error": "oidc_secret_not_configured"}, 503)
        try:
            token = requests.post(
                p.token_url,
                data={"grant_type": "authorization_code", "code": code,
                      "redirect_uri": redirect_uri, "client_id": p.client_id,
                      "client_secret": secret},
                timeout=10,
            )
            token.raise_for_status()
            data = token.json()
            id_token = data.get("id_token")
            if not id_token or not p.jwks_url:
                return _json({"error": "oidc_id_token_missing"}, 502)
            keys = requests.get(p.jwks_url, timeout=10)
            keys.raise_for_status()
            audience = p.audience or p.client_id
            claims = jwt.decode(
                id_token,
                JsonWebKey.import_key_set(keys.json()),
                claims_options={
                    "iss": {"essential": True, "value": p.issuer},
                    "aud": {"essential": True, "value": audience},
                    "nonce": {"essential": True, "value": nonce},
                },
            )
            claims.validate()
            subject = str(claims.get(p.claim_user_id or "sub"))
            email = claims.get(p.claim_email or "email")
            user = request.env["ai.customer.external.identity"].sudo().map_identity(
                p, subject, email, claims.get("name"))
            self._sync_claim_groups(p, user, claims)
            return self._issue_session(p, user)
        except ValueError as exc:
            return _json({"error": str(exc)}, 403)
        except Exception:
            return _json({"error": "oidc_validation_failed"}, 502)

    @http.route("/api/sso/saml/metadata", type="http", auth="none", csrf=False, methods=["GET"])
    def saml_metadata(self, provider, company_id=None):
        p = self._provider(provider, company_id=company_id)
        if not p or p.protocol != "saml" or not self._assert_company_binding(p, company_id):
            return _json({"error": "saml_provider_not_configured"}, 404)
        return _json({
            "provider": p.name, "company_id": p.company_id.id,
            "entity_id": p.saml_entity_id or p.issuer,
            "acs": "/api/sso/saml/acs", "metadata_url": p.saml_metadata_url,
        })

    @http.route("/api/sso/saml/acs", type="http", auth="none", csrf=False, methods=["POST"])
    def saml_acs(self, provider=None, company_id=None, **kwargs):
        if not _sso_allowed():
            return _json({"error": "sso_rate_limited"}, 429)
        p = self._provider(provider, company_id=company_id)
        if not p or p.protocol != "saml" or not self._assert_company_binding(p, company_id):
            return _json({"error": "saml_provider_not_configured"}, 404)
        try:
            _provider_url(p.authorization_url, "authorization_url")
            public_base = (os.environ.get("AI_SSO_PUBLIC_BASE_URL") or
                           request.httprequest.url_root).rstrip("/")
            if os.environ.get("AI_GATEWAY_ENV") == "production" and not public_base.startswith("https://"):
                raise ValueError("AI_SSO_PUBLIC_BASE_URL must be HTTPS in production")
            from onelogin.saml2.auth import OneLogin_Saml2_Auth
            form = request.httprequest.form.to_dict(flat=False)
            settings = {
                "sp": {
                    "entityId": p.saml_entity_id or "enterprise-ai",
                    "assertionConsumerService": {
                        "url": public_base + "/api/sso/saml/acs"
                    },
                },
                "idp": {
                    "entityId": p.issuer,
                    "singleSignOnService": {"url": p.authorization_url},
                    "x509cert": os.environ.get((p.client_secret_ref or "").replace("env://", ""), ""),
                },
            }
            auth = OneLogin_Saml2_Auth(request.httprequest.environ, old_settings=settings)
            auth.process_response({key: value[-1] for key, value in form.items()})
            if not auth.is_authenticated():
                return _json({"error": "saml_authentication_failed"}, 401)
            attrs = auth.get_attributes()
            subject = auth.get_nameid()
            email = (attrs.get(p.claim_email or "email") or [None])[0]
            display_name = (attrs.get("name") or [email])[0] if email else subject
            user = request.env["ai.customer.external.identity"].sudo().map_identity(
                p, subject, email, display_name)
            self._sync_claim_groups(p, user, attrs)
            return self._issue_session(p, user)
        except ValueError as exc:
            return _json({"error": str(exc)}, 403)
        except Exception:
            return _json({"error": "saml_validation_failed"}, 502)
