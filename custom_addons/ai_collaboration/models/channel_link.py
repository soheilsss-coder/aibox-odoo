import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class AiChannelLink(models.Model):
    """Explicit, per-channel opt-in for the assistant inside Odoo's
    native mail.channel (Discuss). A channel shows up in the assistant's
    reach ONLY when a channel member created an active ai.collab.channel
    link for it, and even then the assistant only reacts to messages that
    literally contain the configured trigger (name/mention) text.

    This keeps Buzz groups fully opt-in: no scanning of channels that
    were never opted in, no ambient listening on every channel."""
    _name = "ai.collab.channel.link"
    _description = "AI Channel Opt-in (mail.channel)"
    _order = "id desc"

    channel_id = fields.Many2one("mail.channel", required=True, ondelete="cascade",
                                 string="Discuss Channel")
    trigger_text = fields.Char(
        string="Trigger text", required=True,
        help="The assistant replies only to messages containing this "
             "text, e.g. '@assistant'. The trigger is the opt-in.")
    created_by_id = fields.Many2one("res.users", string="Opted in by",
                                    required=True, ondelete="set null",
                                    default=lambda self: self.env.user)
    last_seen_message_id = fields.Integer(string="Last scanned message", default=0)
    active = fields.Boolean(string="Active", default=True)

    _sql_constraints = [
        ("channel_optin_uniq", "UNIQUE(channel_id)", "A channel can be opted in only once."),
    ]

    def _cron_reply_to_mentions(self):
        """Scheduled listener (see data/cron_data.xml). Runs as the
        minimal service user; every read/write is limited to channels
        with an active opt-in link and guarded by the message id cursor,
        so it only ever looks at what was opted in."""
        if "mail.channel" not in self.env:
            return False
        links = self.sudo().search([("active", "=", True)])
        if not links:
            return 0
        replied = 0
        for link in links:
            channel = link.channel_id
            if not channel.exists():
                continue
            messages = self.env["mail.message"].sudo().search([
                ("model", "=", "mail.channel"),
                ("res_id", "=", channel.id),
                ("id", ">", link.last_seen_message_id),
            ], order="id asc", limit=200)
            for msg in messages:
                body = msg.body or ""
                if link.trigger_text and link.trigger_text in body:
                    if self._reply_to_channel_message(link, channel, msg):
                        replied += 1
                # Advance the durable cursor for every inspected message,
                # including non-trigger messages and failed attempts.  The
                # previous code re-scanned the same first 200 messages forever
                # whenever a channel contained ordinary traffic, creating a
                # needless DB/cron hot loop.
                link.write({"last_seen_message_id": max(link.last_seen_message_id, msg.id)})
        return replied

    def _reply_to_channel_message(self, link, channel, msg):
        author = msg.author_id
        if not author:
            return False
        user = self.env["res.users"].sudo().search(
            [("partner_id", "=", author.id), ("share", "=", False)], limit=1)
        if not user.exists():
            return False
        # Generate as the MENTIONING user (their tool privileges / thread
        # ownership), but post the reply with the assistant's own identity.
        try:
            from odoo.addons.ai_gateway.controllers.gateway import _run_chat_bounded  # noqa: PLC0415
            result = _run_chat_bounded(self.env(user=user.id), msg.body or "")
        except Exception as exc:  # noqa: BLE001
            _logger.warning("channel reply generation failed: %s", exc)
            return False
        reply = result.get("reply") if "error" not in result else None
        if not reply:
            return False
        agent = self.env.ref(
            "ai_business_tools.ai_automation_service_user",
            raise_if_not_found=False) or self.env.ref("base.user_admin")
        if agent.partner_id:
            channel.sudo().message_post(
                body=reply,
                author_id=agent.partner_id.id,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
        return True