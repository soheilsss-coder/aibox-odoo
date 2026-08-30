from odoo import api, fields, models


class AiGatewayTelegramLink(models.Model):
    """One row per linked (Odoo user <-> Telegram chat) pair - mirrors
    roadmap #19 (Agent Identity): one Hermes/Company-Assistant identity
    per Odoo user, never a shared chat/bot used by several employees.
    Created only through the linking flow (telegram_link_code.py +
    the webhook's /link handler) - never directly editable by a normal
    user, so a user can't casually re-point their own link at someone
    else's chat_id.

    thread_id is deliberately stored here (not derived) so a Telegram
    conversation continues the SAME llm.thread across messages, exactly
    like the thread_id round-trip the React frontend and the Buzz
    bridge (buzz_bridge/hermes_gateway_mcp_server.py) both already do
    against /api/chat - this is not a new pattern, just the same one
    applied to a third channel.
    """

    _name = "ai.gateway.telegram.link"
    _description = "AI Gateway Telegram Link"
    _rec_name = "user_id"

    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    chat_id = fields.Char(required=True, index=True,
                           help="Telegram chat.id from the webhook update - stored as text, "
                                "not int, since Telegram chat ids can exceed a 32-bit range.")
    thread_id = fields.Integer(
        help="llm.thread id this Telegram chat is currently continuing - set after the "
             "first /api/chat call, sent back on every later call so the assistant keeps "
             "context across messages instead of starting a new thread each time.")
    active = fields.Boolean(default=True)
    linked_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    last_message_date = fields.Datetime(readonly=True)

    _sql_constraints = [
        ("chat_id_unique", "unique(chat_id)",
         "This Telegram chat is already linked to an Odoo user."),
        ("user_id_unique", "unique(user_id)",
         "This Odoo user already has a linked Telegram chat - unlink it first "
         "(roadmap #19: one identity, one chat, never shared)."),
    ]

    @api.model
    def find_by_chat_id(self, chat_id):
        """sudo() is required here: the webhook controller runs with
        auth='none' (no logged-in Odoo session - Telegram is calling
        us, not an authenticated employee), so there is no env.user to
        check ir.rule against yet. This is the same category of sudo()
        already documented and reviewed under roadmap #22 (Commit-Time
        Authorization): infrastructure lookup on the gateway's own
        linking table, not a business-data read on the caller's
        behalf. Nothing about which Odoo records the eventual message
        can touch is decided here - that's entirely re-checked by
        Odoo's normal ACL once the forwarded /api/chat call executes
        as the real linked user."""
        return self.sudo().search([("chat_id", "=", str(chat_id)), ("active", "=", True)], limit=1)

    def touch(self, thread_id=None):
        self.ensure_one()
        vals = {"last_message_date": fields.Datetime.now()}
        if thread_id:
            vals["thread_id"] = thread_id
        self.sudo().write(vals)

    @api.model
    def send_event_text(self, user_ids, text):
        """Durable event-bus entry point. It sends only to chats already
        cryptographically linked to the supplied Odoo identities; callers do
        not pass arbitrary chat_ids. Failures are raised so the event delivery
        queue retries them instead of silently losing a notification."""
        import os
        import requests
        token = self.env["ir.config_parameter"].sudo().get_param("ai_telegram_bridge.bot_token")
        if not token:
            raise ValueError("Telegram bot token is not configured")
        links = self.sudo().search([("user_id", "in", [int(x) for x in user_ids]), ("active", "=", True)])
        sent = 0
        for link in links:
            chunks = [str(text or "") [i:i + 4000] for i in range(0, len(str(text or "")), 4000)] or [""]
            for chunk in chunks:
                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": link.chat_id, "text": chunk},
                    timeout=15,
                )
                if response.status_code >= 300:
                    raise ValueError(f"Telegram send failed: HTTP {response.status_code}")
            link.touch()
            sent += 1
        return sent
