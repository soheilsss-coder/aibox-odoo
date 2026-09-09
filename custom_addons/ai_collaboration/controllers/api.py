import json
import re

from odoo import http
from odoo.http import request

from odoo.addons.ai_gateway.controllers.gateway import _cors_preflight_response
from odoo.addons.ai_semantic_api.controllers.semantic_api import _json_response, _require_auth


_MAX_CHANNEL_MESSAGE = 12000
_MAX_CHANNEL_MESSAGES = 200


def _plain(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()


class AiCollabApi(http.Controller):
    def _channel_for_user(self, env, channel_id):
        channel = env["discuss.channel"].browse(int(channel_id or 0)).exists()
        if not channel:
            return None, _json_response({"error": "channel not found"}, 404)
        partner_ids = set(channel.channel_member_ids.mapped("partner_id").ids)
        if env.user.partner_id.id not in partner_ids and not env.user.has_group("base.group_system"):
            return None, _json_response({"error": "you are not a member of this channel"}, 403)
        return channel, None

    def _channel_row(self, env, channel, links):
        link = links.filtered(lambda item: item.channel_id.id == channel.id)[:1]
        return {
            "id": channel.id,
            "name": channel.name,
            "member_count": len(channel.channel_member_ids),
            "opted_in": bool(link and link.active),
            "trigger": link.trigger_text if link else None,
            "agent": link.agent_name if link else "Buzz",
        }

    @http.route("/api/collaboration/workspaces", type="http", auth="none", csrf=False,
                methods=["GET", "POST", "OPTIONS"])
    def workspaces(self, **kw):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        model = env["ai.collab.workspace"]
        if request.httprequest.method == "POST":
            payload = json.loads(request.httprequest.data or b"{}")
            name = str(payload.get("name") or "Workspace").strip()[:200]
            kind = payload.get("kind") or "team"
            if kind not in {"private", "team", "department", "company"}:
                return _json_response({"error": "invalid workspace kind"}, 400)
            members = {env.user.id}
            for member_id in payload.get("member_ids") or []:
                try:
                    members.add(int(member_id))
                except (TypeError, ValueError):
                    return _json_response({"error": "member_ids must contain integers"}, 400)
            users = env["res.users"].search([
                ("id", "in", list(members)),
                ("company_ids", "in", env.company.id),
                ("active", "=", True),
            ])
            if set(users.ids) != members:
                return _json_response({"error": "all workspace members must belong to this company"}, 400)
            workspace = model.create({
                "name": name or "Workspace",
                "kind": kind,
                "company_id": env.company.id,
                "department_id": payload.get("department_id") or False,
                "member_ids": [(6, 0, sorted(members))],
                "agent_name": str(payload.get("agent_name") or "Company Assistant").strip()[:100],
            })
            return _json_response({"id": workspace.id, "name": workspace.name}, 201)
        workspaces = model.search([
            ("company_id", "=", env.company.id),
            ("member_ids", "in", env.user.id),
            ("active", "=", True),
        ])
        return _json_response({"workspaces": [{
            "id": workspace.id,
            "name": workspace.name,
            "kind": workspace.kind,
            "agent": workspace.agent_name,
            "member_count": len(workspace.member_ids),
        } for workspace in workspaces]})

    @http.route("/api/collaboration/messages", type="http", auth="none", csrf=False,
                methods=["GET", "POST", "OPTIONS"])
    def messages(self, **kw):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        model = env["ai.collab.message"]
        if request.httprequest.method == "POST":
            payload = json.loads(request.httprequest.data or b"{}")
            workspace = env["ai.collab.workspace"].browse(int(payload.get("workspace_id") or 0)).exists()
            if not workspace or workspace.company_id != env.company or (
                env.user not in workspace.member_ids and not env.user.has_group("base.group_system")
            ):
                return _json_response({"error": "workspace access denied"}, 403)
            body = str(payload.get("body") or "").strip()
            if not body or len(body) > _MAX_CHANNEL_MESSAGE:
                return _json_response({"error": "message body is required and must be bounded"}, 400)
            message = model.create({"workspace_id": workspace.id, "body": body, "message_type": "user"})
            return _json_response({"id": message.id, "created_at": str(message.created_at)}, 201)
        workspace = env["ai.collab.workspace"].browse(int(request.params.get("workspace_id") or 0)).exists()
        if not workspace or workspace.company_id != env.company or (
            env.user not in workspace.member_ids and not env.user.has_group("base.group_system")
        ):
            return _json_response({"error": "workspace access denied"}, 403)
        messages = model.search([("workspace_id", "=", workspace.id)], order="id desc", limit=200)
        return _json_response({"messages": [{
            "id": item.id,
            "author": item.author_id.name,
            "body": item.body,
            "type": item.message_type,
            "created_at": str(item.created_at),
        } for item in reversed(messages)]})

    @http.route("/api/collaboration/channels", type="http", auth="none", csrf=False,
                methods=["GET", "POST", "OPTIONS"])
    def channels(self, **kw):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        channel_model = env["discuss.channel"]
        member_channels = channel_model.search([]).filtered(
            lambda channel: env.user.partner_id in channel.channel_member_ids.mapped("partner_id")
        )
        links = env["ai.collab.channel.link"].sudo().search([
            ("channel_id", "in", member_channels.ids),
        ]) if member_channels else env["ai.collab.channel.link"].sudo().browse()
        if request.httprequest.method == "POST":
            payload = json.loads(request.httprequest.data or b"{}")
            channel, response = self._channel_for_user(env, payload.get("channel_id"))
            if response:
                return response
            trigger = str(payload.get("trigger") or "@buzz").strip()[:80]
            agent_name = str(payload.get("agent_name") or "Buzz").strip()[:100]
            if not trigger:
                return _json_response({"error": "trigger text is required"}, 400)
            link = env["ai.collab.channel.link"].sudo().search([
                ("channel_id", "=", channel.id),
            ], limit=1)
            if link and link.created_by_id != env.user and not env.user.has_group("base.group_system"):
                return _json_response({"error": "only the opt-in owner can change this channel"}, 403)
            latest = env["mail.message"].sudo().search([
                ("model", "=", "discuss.channel"),
                ("res_id", "=", channel.id),
            ], order="id desc", limit=1)
            values = {
                "channel_id": channel.id,
                "trigger_text": trigger,
                "agent_name": agent_name or "Buzz",
                "created_by_id": env.user.id,
                "last_seen_message_id": latest.id if latest else 0,
                "active": True,
            }
            if link:
                link.write(values)
            else:
                env["ai.collab.channel.link"].create(values)
            return _json_response({
                "status": "opted_in", "channel_id": channel.id,
                "trigger": trigger, "agent": agent_name or "Buzz",
            })
        return _json_response({"channels": [self._channel_row(env, channel, links) for channel in member_channels]})

    @http.route("/api/collaboration/channels/<int:channel_id>/messages", type="http",
                auth="none", csrf=False, methods=["GET", "POST", "OPTIONS"])
    def channel_messages(self, channel_id, **kw):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        channel, response = self._channel_for_user(env, channel_id)
        if response:
            return response
        message_model = env["mail.message"].sudo()
        if request.httprequest.method == "POST":
            payload = json.loads(request.httprequest.data or b"{}")
            body = str(payload.get("body") or "").strip()
            if not body or len(body) > _MAX_CHANNEL_MESSAGE:
                return _json_response({"error": "message body is required and must be bounded"}, 400)
            message = channel.sudo().message_post(
                body=body,
                author_id=env.user.partner_id.id,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
            link = env["ai.collab.channel.link"].sudo().search([
                ("channel_id", "=", channel.id), ("active", "=", True),
            ], limit=1)
            agent_replied = False
            if link:
                if link.trigger_text and link.trigger_text in body:
                    # Fast path makes the group chat feel conversational. The
                    # cron remains a recovery path for timeouts/failures.
                    agent_replied = bool(link._reply_to_channel_message(link, channel, message))
                    if agent_replied:
                        link.write({"last_seen_message_id": message.id})
                else:
                    link.write({"last_seen_message_id": max(link.last_seen_message_id, message.id)})
            return _json_response({"id": message.id, "agent_replied": agent_replied}, 201)
        try:
            after = max(0, int(request.params.get("after") or 0))
        except (TypeError, ValueError):
            return _json_response({"error": "after must be an integer"}, 400)
        try:
            limit = min(_MAX_CHANNEL_MESSAGES, max(1, int(request.params.get("limit") or 100)))
        except (TypeError, ValueError):
            return _json_response({"error": "limit must be an integer"}, 400)
        domain = [("model", "=", "discuss.channel"), ("res_id", "=", channel.id)]
        if after:
            domain.append(("id", ">", after))
        messages = message_model.search(domain, order="id desc", limit=limit)
        agent = env.ref("ai_business_tools.ai_automation_service_user", raise_if_not_found=False)
        agent = agent or env.ref("base.user_admin", raise_if_not_found=False)
        agent_partner_id = agent.partner_id.id if agent and agent.partner_id else 0
        return _json_response({"messages": [{
            "id": item.id,
            "author": item.author_id.name or "عضو گروه",
            "body": _plain(item.body),
            "type": "agent" if item.author_id.id == agent_partner_id else "user",
            "created_at": str(item.create_date),
        } for item in reversed(messages)]})

    @http.route("/api/collaboration/channels/optout", type="http", auth="none", csrf=False,
                methods=["POST", "OPTIONS"])
    def channel_optout(self, **kw):
        if request.httprequest.method == "OPTIONS":
            return _cors_preflight_response()
        env, err = _require_auth()
        if err:
            return err
        payload = json.loads(request.httprequest.data or b"{}")
        channel, response = self._channel_for_user(env, payload.get("channel_id"))
        if response:
            return response
        link = env["ai.collab.channel.link"].sudo().search([("channel_id", "=", channel.id)], limit=1)
        if not link:
            return _json_response({"error": "channel was not opted in"}, 404)
        if link.created_by_id != env.user and not env.user.has_group("base.group_system"):
            return _json_response({"error": "you are not the opt-in owner"}, 403)
        link.write({"active": False})
        return _json_response({"status": "opted_out", "channel_id": channel.id})
