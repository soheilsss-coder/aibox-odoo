from odoo import api, fields, models


class AiGatewayTelegramLinkWizard(models.TransientModel):
    """Opened from the 'Generate Telegram Link Code' action - creates a
    fresh code for env.user (never lets you generate one for someone
    else) and just displays it with the instructions to send it to the
    bot. No business logic lives here; telegram_link_code.py owns the
    actual expiry/consumption rules."""

    _name = "ai.gateway.telegram.link.wizard"
    _description = "Generate Telegram Link Code"

    code = fields.Char(readonly=True)
    bot_username = fields.Char(readonly=True)
    already_linked_chat_id = fields.Char(readonly=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        existing_link = self.env["ai.gateway.telegram.link"].sudo().search(
            [("user_id", "=", self.env.user.id)], limit=1
        )
        if existing_link:
            vals["already_linked_chat_id"] = existing_link.chat_id
        else:
            code_rec = self.env["ai.gateway.telegram.link.code"].generate_for_current_user()
            vals["code"] = code_rec.code
        vals["bot_username"] = self.env["ir.config_parameter"].sudo().get_param(
            "ai_telegram_bridge.bot_username", "your_company_bot"
        )
        return vals
