import uuid

from odoo import fields, models


class AiModuleInstallRequest(models.Model):
    """Durable audit record for a customer appliance module installation.

    Module installation is intentionally delegated to the platform's own
    ``ir.module.module`` installer by the controller.  This model records who
    requested it and the outcome, so the customer setup screen never has to
    infer success from a browser timeout or from a checkbox state.
    """

    _name = "ai.module.install.request"
    _description = "Customer Module Installation Request"
    _order = "requested_at desc, id desc"

    request_key = fields.Char(
        required=True, readonly=True, index=True,
        default=lambda self: uuid.uuid4().hex,
    )
    module_id = fields.Many2one("ir.module.module", required=True, readonly=True, index=True, ondelete="cascade")
    module_name = fields.Char(required=True, readonly=True, index=True)
    module_label = fields.Char(required=True, readonly=True)
    company_id = fields.Many2one(
        "res.company", required=True, readonly=True, index=True,
        ondelete="restrict", default=lambda self: self.env.company,
    )
    requested_by_id = fields.Many2one(
        "res.users", required=True, readonly=True,
        ondelete="restrict", default=lambda self: self.env.user,
    )
    state = fields.Selection([
        ("queued", "Queued"),
        ("installing", "Installing"),
        ("installed", "Installed"),
        ("failed", "Failed"),
    ], required=True, default="queued", index=True)
    error = fields.Text(readonly=True)
    requested_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)
    completed_at = fields.Datetime(readonly=True)
