import json
import os
import re

from odoo import http
from odoo.http import request

from odoo.addons.ai_gateway.controllers.rate_limit import allow


_SCIM_RATE_LIMIT = int(os.environ.get("AI_SCIM_RATE_LIMIT", "300"))
SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


def _response(payload, status=200):
    return request.make_response(
        json.dumps(payload, default=str),
        headers=[("Content-Type", "application/scim+json")],
        status=status,
    )


def _error(detail, status=400, scim_type=None):
    payload = {"schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"], "detail": detail}
    if scim_type:
        payload["scimType"] = scim_type
    return _response(payload, status)


class AiScimController(http.Controller):
    """Tenant-scoped SCIM 2.0 provisioning surface.

    Only the explicitly mapped product roles can be managed.  Native role
    membership is never mutated by an IdP request; managed assignments remain
    attributable to SCIM and can be reconciled without deleting admin roles.
    """

    def _auth(self):
        # SCIM is an M2M surface, so bound it before parsing/provisioning. The
        # shared limiter is Redis-backed in production and fails closed when
        # the distributed limiter is unavailable.
        ip = request.httprequest.remote_addr or ""
        if not allow(ip, _SCIM_RATE_LIMIT, prefix="ai:scim:ip"):
            return None
        header = request.httprequest.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        raw = header[7:].strip()
        token = request.env["ai.customer.scim.token"].sudo().authenticate(raw)
        return token if token else None

    def _body(self):
        try:
            body = json.loads(request.httprequest.data.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("invalid JSON")
        if not isinstance(body, dict):
            raise ValueError("JSON body must be an object")
        return body

    def _paging(self):
        try:
            start = int(request.params.get("startIndex") or 1)
            count = int(request.params.get("count") or 100)
        except (TypeError, ValueError):
            raise ValueError("startIndex and count must be integers")
        start = max(start, 1)
        count = max(count, 0)
        return start, min(count, 1000)

    def _user_json(self, user, base="/scim/v2/Users"):
        return {
            "schemas": [SCIM_USER_SCHEMA],
            "id": str(user.id),
            "externalId": str(user.id),
            "userName": user.login,
            "active": bool(user.active),
            "name": {"formatted": user.name},
            "emails": [{"value": user.email, "primary": True}] if user.email else [],
            "meta": {"resourceType": "User", "location": f"{base}/{user.id}"},
        }

    def _user_domain(self, token):
        domain = [("company_ids", "in", token.company_id.id)]
        expression = (request.params.get("filter") or "").strip()
        if not expression:
            return domain
        match = re.fullmatch(r"(userName|id|externalId)\s+eq\s+\"([^\"]*)\"", expression, re.I)
        if not match:
            raise ValueError("unsupported SCIM filter")
        attribute, value = match.groups()
        if attribute.lower() == "username":
            domain.append(("login", "=", value))
        elif attribute.lower() == "id":
            if not value.isdigit():
                domain.append(("id", "=", 0))
            else:
                domain.append(("id", "=", int(value)))
        else:
            # externalId is the stable local numeric identifier exposed by the
            # serializer.  It is intentionally not an arbitrary database query.
            domain.append(("id", "=", int(value) if value.isdigit() else 0))
        return domain

    def _list_response(self, resources, total, start, count):
        return _response({
            "schemas": [SCIM_LIST_SCHEMA],
            "totalResults": total,
            "startIndex": start,
            "itemsPerPage": len(resources) if count else 0,
            "Resources": resources,
        })

    def _find_user(self, token, user_id):
        return request.env["res.users"].sudo().search(
            [("id", "=", user_id), ("company_ids", "in", token.company_id.id)], limit=1)

    def _validate_login(self, login, current_id=None):
        if not login or not str(login).strip():
            raise ValueError("userName is required")
        domain = [("login", "=", str(login).strip())]
        if current_id:
            domain.append(("id", "!=", current_id))
        if request.env["res.users"].sudo().search(domain, limit=1):
            raise LookupError("userName is already in use")
        return str(login).strip()

    def _values_from_body(self, body, replace=False, current=None):
        current = current or request.env["res.users"].browse()
        login = body.get("userName")
        if replace or login is not None:
            login = self._validate_login(login or (current.login if current else ""), current.id if current else None)
        vals = {"login": login} if login else {}
        if replace or "active" in body:
            vals["active"] = bool(body.get("active", True))
        if replace or "name" in body:
            raw_name = body.get("name") or {}
            name = (raw_name.get("formatted") if isinstance(raw_name, dict) else str(raw_name)) or login
            vals["name"] = name or (current.name if current else "SCIM user")
        if replace or "emails" in body:
            emails = body.get("emails") or []
            if not isinstance(emails, list):
                raise ValueError("emails must be a list")
            first = emails[0] if emails else {}
            vals["email"] = ((first or {}).get("value") or False) if isinstance(first, dict) else False
        return vals

    def _patch_values(self, body, user):
        if body.get("schemas") and SCIM_PATCH_SCHEMA not in body["schemas"]:
            raise ValueError("invalid PATCH schema")
        vals = {}
        operations = body.get("Operations", [])
        if not isinstance(operations, list):
            raise ValueError("Operations must be a list")
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError("each PATCH operation must be an object")
            op = (operation.get("op") or "replace").lower()
            path = (operation.get("path") or "").lower()
            value = operation.get("value")
            if op not in {"add", "replace", "remove"}:
                raise ValueError("unsupported PATCH operation")
            if path in {"username", "externalid"}:
                if op == "remove":
                    raise ValueError("userName is immutable and required")
                vals["login"] = self._validate_login(value, user.id)
            elif path in {"active"}:
                vals["active"] = False if op == "remove" else bool(value)
            elif path in {"name", "name.formatted"}:
                if op == "remove":
                    vals["name"] = user.login
                elif isinstance(value, dict):
                    vals["name"] = value.get("formatted") or user.login
                else:
                    vals["name"] = str(value)
            elif path in {"emails", "emails.value", "emails[type eq \"work\"].value"}:
                if op == "remove":
                    vals["email"] = False
                elif isinstance(value, list):
                    vals["email"] = ((value[0] or {}).get("value") or False) if value else False
                elif isinstance(value, dict):
                    vals["email"] = value.get("value") or False
                else:
                    vals["email"] = str(value)
            else:
                raise ValueError("unsupported PATCH path")
        return vals

    @http.route("/scim/v2/ServiceProviderConfig", type="http", auth="none", csrf=False, methods=["GET"])
    def service_provider_config(self, **kwargs):
        token = self._auth()
        if not token:
            return _error("Unauthorized", 401)
        return _response({
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
            "patch": {"supported": True},
            "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": True, "maxResults": 1000},
            "changePassword": {"supported": False},
            "sort": {"supported": False},
            "etag": {"supported": False},
        })

    @http.route("/scim/v2/Users", type="http", auth="none", csrf=False, methods=["GET", "POST"])
    def users(self, **kwargs):
        token = self._auth()
        if not token:
            return _error("Unauthorized", 401)
        User = request.env["res.users"].sudo()
        if request.httprequest.method == "GET":
            try:
                start, count = self._paging()
                domain = self._user_domain(token)
            except ValueError as exc:
                return _error(str(exc), 400, "invalidFilter")
            total = User.search_count(domain)
            users = User.search(domain, offset=start - 1, limit=count, order="id") if count else User.browse()
            return self._list_response([self._user_json(u) for u in users], total, start, count)
        try:
            body = self._body()
            login = self._validate_login((body.get("userName") or "").strip())
        except json.JSONDecodeError:
            return _error("invalid JSON", 400, "invalidSyntax")
        except (ValueError, LookupError) as exc:
            return _error(str(exc), 409 if isinstance(exc, LookupError) else 400,
                          "uniqueness" if isinstance(exc, LookupError) else None)
        try:
            vals = self._values_from_body(dict(body, userName=login), replace=True)
            vals.update({"company_id": token.company_id.id, "company_ids": [(4, token.company_id.id)]})
            user = User.create(vals)
        except Exception:
            return _error("user could not be provisioned", 409)
        return _response(self._user_json(user), 201)

    @http.route("/scim/v2/Users/<int:user_id>", type="http", auth="none", csrf=False,
                methods=["GET", "PUT", "PATCH", "DELETE"])
    def user(self, user_id, **kwargs):
        token = self._auth()
        if not token:
            return _error("Unauthorized", 401)
        user = self._find_user(token, user_id)
        if not user:
            return _error("Not found", 404)
        if request.httprequest.method == "GET":
            return _response(self._user_json(user))
        if request.httprequest.method == "DELETE":
            user.write({"active": False})
            return request.make_response("", status=204)
        try:
            body = self._body()
            vals = self._values_from_body(body, replace=request.httprequest.method == "PUT", current=user)
            if request.httprequest.method == "PATCH":
                vals = self._patch_values(body, user)
        except json.JSONDecodeError:
            return _error("invalid JSON", 400, "invalidSyntax")
        except (ValueError, LookupError) as exc:
            return _error(str(exc), 409 if isinstance(exc, LookupError) else 400,
                          "uniqueness" if isinstance(exc, LookupError) else None)
        user.write(vals)
        return _response(self._user_json(user))

    def _product_group_by_name(self, name):
        groups = request.env["res.groups"].sudo().search([("name", "=", name)])
        product_groups = []
        for group in groups:
            external_ids = set(group.get_external_id().values())
            if any(xmlid.startswith("ai_business_tools.role_") for xmlid in external_ids):
                product_groups.append(group)
        return product_groups

    def _mapped_group(self, token, group_id):
        mapping = request.env["ai.customer.scim.group"].sudo().search([
            ("company_id", "=", token.company_id.id),
            ("group_id", "=", int(group_id)),
            ("active", "=", True),
        ], limit=1)
        return mapping.group_id if mapping else request.env["res.groups"].browse()

    def _group_json(self, token, group):
        assignments = request.env["ai.customer.role.assignment"].sudo().search([
            ("role_group_id", "=", group.id),
            ("company_id", "=", token.company_id.id),
            ("managed_by", "=", "scim"),
            ("active", "=", True),
        ]).mapped("user_id")
        members = [{"value": str(u.id), "display": u.name} for u in assignments
                   if token.company_id in u.company_ids]
        return {"schemas": [SCIM_GROUP_SCHEMA], "id": str(group.id),
                "displayName": group.name, "members": members}

    def _member_ids(self, token, members):
        if not isinstance(members, list):
            raise ValueError("members must be a list")
        values = []
        for member in members:
            value = str((member or {}).get("value", ""))
            if not value.isdigit():
                raise ValueError("member value must be a local user id")
            values.append(int(value))
        users = request.env["res.users"].sudo().search([
            ("id", "in", values), ("company_ids", "in", token.company_id.id)])
        if len(users) != len(set(values)):
            raise ValueError("one or more members do not belong to this company")
        return users

    def _replace_members(self, token, group, users):
        Assignment = request.env["ai.customer.role.assignment"].sudo()
        Assignment.search([
            ("role_group_id", "=", group.id), ("company_id", "=", token.company_id.id),
            ("managed_by", "=", "scim"),
        ]).unlink()
        if users:
            Assignment.create([{
                "user_id": user.id, "role_group_id": group.id, "source": "direct",
                "company_id": token.company_id.id, "managed_by": "scim",
                "reason": "SCIM group membership",
            } for user in users])

    @http.route("/scim/v2/Groups", type="http", auth="none", csrf=False, methods=["GET", "POST"])
    def groups(self, **kwargs):
        token = self._auth()
        if not token:
            return _error("Unauthorized", 401)
        Map = request.env["ai.customer.scim.group"].sudo()
        if request.httprequest.method == "GET":
            try:
                start, count = self._paging()
            except ValueError as exc:
                return _error(str(exc), 400, "invalidFilter")
            domain = [("company_id", "=", token.company_id.id), ("active", "=", True)]
            expression = (request.params.get("filter") or "").strip()
            if expression:
                match = re.fullmatch(r"displayName\s+eq\s+\"([^\"]*)\"", expression, re.I)
                if not match:
                    return _error("unsupported SCIM filter", 400, "invalidFilter")
                domain.append(("name", "=", match.group(1)))
            total = Map.search_count(domain)
            maps = Map.search(domain, offset=start - 1, limit=count, order="id") if count else Map.browse()
            return self._list_response([self._group_json(token, m.group_id) for m in maps], total, start, count)
        try:
            body = self._body()
            name = (body.get("displayName") or "").strip()
            if not name:
                return _error("displayName is required", 400)
            matches = self._product_group_by_name(name)
            if len(matches) != 1:
                return _error("Group name is not uniquely mapped to a product role", 409, "uniqueness")
            group = matches[0]
            existing = Map.search([("company_id", "=", token.company_id.id), ("group_id", "=", group.id)], limit=1)
            if existing:
                return _error("Conflict", 409, "uniqueness")
            # Validate the complete member set before creating the mapping so
            # malformed SCIM requests cannot leave a half-provisioned record.
            users = self._member_ids(token, body.get("members") or [])
            mapping = Map.create({"name": name, "company_id": token.company_id.id, "group_id": group.id})
            self._replace_members(token, group, users)
        except json.JSONDecodeError:
            return _error("invalid JSON", 400, "invalidSyntax")
        except ValueError as exc:
            return _error(str(exc), 400)
        return _response(self._group_json(token, mapping.group_id), 201)

    @http.route("/scim/v2/Groups/<int:group_id>", type="http", auth="none", csrf=False,
                methods=["GET", "PUT", "PATCH", "DELETE"])
    def group(self, group_id, **kwargs):
        token = self._auth()
        if not token:
            return _error("Unauthorized", 401)
        group = self._mapped_group(token, group_id)
        if not group:
            return _error("Not found", 404)
        if request.httprequest.method == "GET":
            return _response(self._group_json(token, group))
        if request.httprequest.method == "DELETE":
            request.env["ai.customer.scim.group"].sudo().search([
                ("company_id", "=", token.company_id.id), ("group_id", "=", group.id)
            ]).write({"active": False})
            request.env["ai.customer.role.assignment"].sudo().search([
                ("role_group_id", "=", group.id), ("company_id", "=", token.company_id.id),
                ("managed_by", "=", "scim"),
            ]).unlink()
            return request.make_response("", status=204)
        try:
            body = self._body()
            if request.httprequest.method == "PUT":
                users = self._member_ids(token, body.get("members") or [])
                self._replace_members(token, group, users)
            else:
                if body.get("schemas") and SCIM_PATCH_SCHEMA not in body["schemas"]:
                    raise ValueError("invalid PATCH schema")
                operations = body.get("Operations", [])
                if not isinstance(operations, list):
                    raise ValueError("Operations must be a list")
                validated = []
                for operation in operations:
                    if not isinstance(operation, dict):
                        raise ValueError("each PATCH operation must be an object")
                    op = (operation.get("op") or "replace").lower()
                    path = (operation.get("path") or "").lower()
                    if path != "members" or op not in {"add", "replace", "remove"}:
                        raise ValueError("only members add/replace/remove is supported")
                    users = self._member_ids(token, operation.get("value") or [])
                    validated.append((op, users))
                Assignment = request.env["ai.customer.role.assignment"].sudo()
                for op, users in validated:
                    if op == "replace":
                        self._replace_members(token, group, users)
                        continue
                    domain = [("role_group_id", "=", group.id), ("company_id", "=", token.company_id.id),
                              ("managed_by", "=", "scim"), ("user_id", "in", users.ids)]
                    if op == "remove":
                        Assignment.search(domain).unlink()
                    else:
                        existing = set(Assignment.search(domain).mapped("user_id").ids)
                        Assignment.create([{
                            "user_id": user.id, "role_group_id": group.id, "source": "direct",
                            "company_id": token.company_id.id, "managed_by": "scim",
                            "reason": "SCIM group membership",
                        } for user in users if user.id not in existing])
        except json.JSONDecodeError:
            return _error("invalid JSON", 400, "invalidSyntax")
        except ValueError as exc:
            return _error(str(exc), 400)
        return _response(self._group_json(token, group))
