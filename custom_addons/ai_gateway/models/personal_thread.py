from odoo import fields, models


class LLMThreadPersonalAgent(models.Model):
    """Persist the user's personal workspace identity on each chat thread.

    The thread still points to the single Company Assistant through the
    framework's assistant_id. This relation only records the user-facing
    personal workspace/profile that owns the conversation; it never grants
    tools or broadens the caller's permissions.
    """

    _inherit = "llm.thread"

    personal_agent_identity_id = fields.Many2one(
        "ai.gateway.agent.identity",
        string="Personal assistant identity",
        index=True,
        copy=False,
        ondelete="set null",
        readonly=True,
    )
