import json
from odoo import http
from odoo.http import request


def _response(payload, status=200):
    return request.make_response(
        json.dumps(payload, default=str),
        headers=[("Content-Type", "application/scim+json")],
        status=status,
    )


class AiScimController(http.Controller):
    """Minimal SCIM 2.0 provisioning surface.

    It is deliberately separate from the normal AI Gateway and authenticates
    only with a dedicated hashed SCIM bearer token. Tokens are company-scoped.
    """

    def _auth(self):
        header = request.httprequest.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        raw = header[7:].strip()
        token = request.env["ai.customer.scim.token"].sudo().authenticate(raw)
        return token if token else None

    def _user_json(self, user, base="/scim/v2/Users"):
        return {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "id": str(user.id),
            "userName": user.login,
            "active": bool(user.active),
            "name": {"formatted": user.name},
            "emails": [{"value": user.email, "primary": True}] if user.email else [],
            "meta": {"resourceType": "User", "location": f"{base}/{user.id}"},
        }

    @http.route("/scim/v2/Users", type="http", auth="none", csrf=False, methods=["GET", "POST"])
    def users(self, **kwargs):
        token = self._auth()
        if not token:
            return _response({"detail": "Unauthorized"}, 401)
        User = request.env["res.users"].sudo()
        if request.httprequest.method == "GET":
            domain = [("company_ids", "in", token.company_id.id)]
            total = User.search_count(domain)
            resources = [self._user_json(u) for u in User.search(domain, limit=100)]
            return _response({"schemas":["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
                              "totalResults":total,"startIndex":1,"itemsPerPage":len(resources),"Resources":resources})
        body = json.loads(request.httprequest.data.decode() or "{}")
        login = (body.get("userName") or "").strip()
        if not login:
            return _response({"detail":"userName is required"},400)
        if User.search([("login","=",login)], limit=1):
            return _response({"detail":"Conflict"},409)
        email = ((body.get("emails") or [{}])[0].get("value") or "").strip()
        user = User.create({"name": body.get("name",{}).get("formatted") or login,
                            "login": login, "email": email or False,
                            "company_id": token.company_id.id,
                            "company_ids": [(4, token.company_id.id)]})
        return _response(self._user_json(user),201)

    @http.route("/scim/v2/Users/<int:user_id>", type="http", auth="none", csrf=False,
                methods=["GET","PUT","PATCH","DELETE"])
    def user(self, user_id, **kwargs):
        token = self._auth()
        if not token:
            return _response({"detail":"Unauthorized"},401)
        user = request.env["res.users"].sudo().search(
            [("id","=",user_id),("company_ids","in",token.company_id.id)], limit=1)
        if not user:
            return _response({"detail":"Not found"},404)
        if request.httprequest.method == "GET":
            return _response(self._user_json(user))
        if request.httprequest.method == "DELETE":
            user.write({"active":False})
            return request.make_response("",status=204)
        body = json.loads(request.httprequest.data.decode() or "{}")
        if request.httprequest.method == "PATCH":
            for op in body.get("Operations", []):
                path, value = op.get("path"), op.get("value")
                if path == "active":
                    body["active"] = value
        vals = {}
        if "userName" in body: vals["login"] = body["userName"]
        if "active" in body: vals["active"] = bool(body["active"])
        if "name" in body and body["name"].get("formatted"): vals["name"] = body["name"]["formatted"]
        if body.get("emails"): vals["email"] = body["emails"][0].get("value")
        if vals: user.write(vals)
        return _response(self._user_json(user))


    def _mapped_group(self, token, group_id):
        mapping = request.env["ai.customer.scim.group"].sudo().search([
            ("company_id", "=", token.company_id.id),
            ("group_id", "=", int(group_id)),
            ("active", "=", True),
        ], limit=1)
        return mapping.group_id if mapping else request.env["res.groups"].browse()

    @http.route("/scim/v2/Groups", type="http", auth="none", csrf=False, methods=["GET", "POST"])
    def groups(self, **kwargs):
        token = self._auth()
        if not token:
            return _response({"detail": "Unauthorized"}, 401)
        Map = request.env["ai.customer.scim.group"].sudo()
        if request.httprequest.method == "GET":
            maps = Map.search([("company_id", "=", token.company_id.id), ("active", "=", True)], limit=100)
            resources = []
            for m in maps:
                g = m.group_id
                assigned = request.env["ai.customer.role.assignment"].sudo().search([("role_group_id","=",g.id),("company_id","=",token.company_id.id),("managed_by","=","scim"),("active","=",True)]).mapped("user_id")
                members = [{"value": str(u.id), "display": u.name} for u in assigned if token.company_id in u.company_ids]
                resources.append({"schemas":["urn:ietf:params:scim:schemas:core:2.0:Group"],
                                  "id":str(g.id),"displayName":g.name,"members":members})
            return _response({"schemas":["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
                              "totalResults":len(resources),"startIndex":1,"itemsPerPage":len(resources),"Resources":resources})
        body = json.loads(request.httprequest.data.decode() or "{}")
        name = (body.get("displayName") or "").strip()
        if not name:
            return _response({"detail":"displayName is required"},400)
        Group = request.env["res.groups"].sudo()
        # SCIM may only manage groups explicitly pre-provisioned by the
        # Customer Control Plane. It must never create arbitrary global
        # Odoo groups from an IdP request.
        group = Group.search([("name", "=", name)], limit=1)
        if not group:
            return _response({"detail":"Group is not pre-mapped for SCIM"},404)
        existing = Map.search([("company_id","=",token.company_id.id),("group_id","=",group.id)], limit=1)
        if existing:
            return _response({"detail":"Conflict"},409)
        Map.create({"name": name, "company_id": token.company_id.id, "group_id": group.id})
        return _response({"schemas":["urn:ietf:params:scim:schemas:core:2.0:Group"],
                          "id":str(group.id),"displayName":group.name,"members":[]},201)

    @http.route("/scim/v2/Groups/<int:group_id>", type="http", auth="none", csrf=False, methods=["GET","PUT","PATCH"])
    def group(self, group_id, **kwargs):
        token=self._auth()
        if not token:
            return _response({"detail":"Unauthorized"},401)
        group=self._mapped_group(token, group_id)
        if not group:
            return _response({"detail":"Not found"},404)
        if request.httprequest.method=="GET":
            return _response({"schemas":["urn:ietf:params:scim:schemas:core:2.0:Group"],
                              "id":str(group.id),"displayName":group.name,
                              "members":[{"value":str(u.id),"display":u.name} for u in request.env["ai.customer.role.assignment"].sudo().search([("role_group_id","=",group.id),("company_id","=",token.company_id.id),("managed_by","=","scim"),("active","=",True)]).mapped("user_id") if token.company_id in u.company_ids]})
        body=json.loads(request.httprequest.data.decode() or "{}")
        # displayName is informational in this endpoint. Never rename the
        # underlying Odoo role/group from an external IdP request.
        operations=body.get("Operations",[])
        for op in operations:
            if op.get("path")=="members":
                members=op.get("value") or []
                user_ids=[int(m["value"]) for m in members if str(m.get("value","")).isdigit()]
                users=request.env["res.users"].sudo().search([("id","in",user_ids),("company_ids","in",token.company_id.id)])
                Assignment=request.env["ai.customer.role.assignment"].sudo()
                Assignment.search([("role_group_id","=",group.id),("company_id","=",token.company_id.id),("managed_by","=","scim")]).unlink()
                Assignment.create([{"user_id":u.id,"role_group_id":group.id,"source":"direct","company_id":token.company_id.id,"managed_by":"scim","reason":"SCIM group membership"} for u in users])
        return _response({"schemas":["urn:ietf:params:scim:schemas:core:2.0:Group"],
                          "id":str(group.id),"displayName":group.name,
                          "members":[{"value":str(u.id),"display":u.name} for u in group.users if token.company_id in u.company_ids]})
