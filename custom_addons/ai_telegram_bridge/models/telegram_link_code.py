import secrets

from odoo import api, fields, models

CODE_TTL_MINUTES = 10


class AiGatewayTelegramLinkCode(models.Model):
    """Short-lived one-time codes so a user proves they ARE the Odoo
    user they claim to be when linking a Telegram chat - without this,
    anyone who finds the bot's username could message it and claim to
    be any employee. Flow: user clicks "Generate Telegram Link Code"
    inside Odoo (wizard/telegram_link_wizard.py) while already logged
    in as themselves, gets an 8-character code good for 10 minutes,
    sends `/link <code>` to the bot on Telegram. The webhook controller
    is the only thing that ever reads/consumes these - a normal user
    only ever creates their own (ir.rule) and never lists anyone
    else's.
    """

    _name = "ai.gateway.telegram.link.code"
    _description = "AI Gateway Telegram Link Code"

    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True,
                               default=lambda self: self.env.user.id)
    code = fields.Char(required=True, index=True, copy=False,
                        default=lambda self: secrets.token_hex(4).upper())
    create_date = fields.Datetime(readonly=True)
    used = fields.Boolean(default=False)

    @api.model
    def generate_for_current_user(self):
        """Invalidate any earlier unused codes for this user first -
        only the most recent code is ever valid, so an old code
        leaked/forgotten in a chat window can't be used later."""
        self.env.cr.execute(
            f"SELECT id FROM {self._table} WHERE user_id=%s AND used=FALSE FOR UPDATE",
            (self.env.user.id,),
        )
        ids = [r[0] for r in self.env.cr.fetchall()]
        if ids:
            self.sudo().browse(ids).write({"used": True})
        return self.create({"user_id": self.env.user.id})

    @api.model
    def consume(self, code):
        """sudo() here is the same infra-lookup category as
        telegram_link.find_by_chat_id() - called from the unauthenticated
        webhook, checking the gateway's own linking table, not business
        data. Returns the res.users record the code belonged to, or
        False if the code is unknown/already used/expired."""
        # Serialize consumption in PostgreSQL. A plain search()+write() lets
        # two webhook workers consume the same one-time code concurrently.
        self.env.cr.execute(
            f"SELECT id FROM {self._table} WHERE code=%s AND used=FALSE FOR UPDATE",
            (code.strip().upper(),),
        )
        row = self.env.cr.fetchone()
        if not row:
            return False
        rec = self.sudo().browse(row[0])
        age_minutes = (fields.Datetime.now() - rec.create_date).total_seconds() / 60.0
        if age_minutes > CODE_TTL_MINUTES:
            rec.write({"used": True})
            return False
        rec.write({"used": True})
        return rec.user_id
