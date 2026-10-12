import json
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class AiCustomerSetupRun(models.Model):
    """Durable lifecycle record for preparing one customer appliance.

    A setup run is evidence, not a browser progress flag. Long-running setup
    work can be retried or inspected after a session expires without guessing
    whether a module/profile operation actually completed.
    """

    _name = "ai.customer.setup.run"
    _description = "Customer Setup Run"
    _order = "started_at desc, id desc"

    run_key = fields.Char(
        required=True, readonly=True, index=True,
        default=lambda self: uuid.uuid4().hex,
    )
    company_id = fields.Many2one(
        "res.company", required=True, readonly=True, index=True,
        ondelete="restrict", default=lambda self: self.env.company,
    )
    requested_by_id = fields.Many2one(
        "res.users", required=True, readonly=True,
        default=lambda self: self.env.user,
    )
    state = fields.Selection([
        ("queued", "Queued"),
        ("running", "Running"),
        ("passed", "Passed"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ], required=True, default="queued", index=True)
    current_stage = fields.Selection([
        ("identity", "Company identity"),
        ("branding", "Branding"),
        ("modules", "Modules"),
        ("policies", "Policies"),
        ("profile", "Configuration profile"),
        ("integrations", "Integrations"),
        ("rag", "RAG"),
        ("certification", "Runtime certification"),
        ("handoff", "Handoff"),
    ], default="identity", required=True, index=True)
    result_json = fields.Text(default="{}", required=True)
    error_summary = fields.Text()
    release_commit = fields.Char(size=64, readonly=True)
    configuration_profile_id = fields.Many2one(
        "ai.customer.configuration.profile", readonly=True, ondelete="set null",
    )
    branding_version = fields.Integer(readonly=True)
    module_snapshot_hash = fields.Char(size=128, readonly=True)
    runtime_certification_state = fields.Selection([
        ("not_run", "Not run"),
        ("required", "Required"),
        ("passed", "Passed"),
        ("failed", "Failed"),
    ], default="not_run", required=True)
    backup_reference = fields.Char(size=500, readonly=True)
    rollback_reference = fields.Char(size=500, readonly=True)
    started_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    completed_at = fields.Datetime(readonly=True)

    _sql_constraints = [
        ("run_key_unique", "unique(run_key)", "Setup run key must be unique."),
    ]

    @api.constrains("result_json")
    def _check_result_json(self):
        for record in self:
            try:
                value = json.loads(record.result_json or "{}")
            except (TypeError, ValueError) as exc:
                raise ValidationError("Setup result must contain valid JSON.") from exc
            if not isinstance(value, dict):
                raise ValidationError("Setup result must be a JSON object.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("company_id", self.env.company.id)
            vals.setdefault("requested_by_id", self.env.user.id)
            vals.setdefault("runtime_certification_state", "not_run")
            vals.setdefault("result_json", "{}")
        return super().create(vals_list)

    def _transition(self, expected, target, stage=None, result=None, error_summary=None):
        for record in self:
            if record.state not in expected:
                raise UserError(
                    "Setup run %s cannot move from %s to %s."
                    % (record.run_key, record.state, target)
                )
            values = {"state": target}
            if stage:
                values["current_stage"] = stage
            if result is not None:
                if not isinstance(result, dict):
                    raise ValidationError("Setup result must be an object.")
                values["result_json"] = json.dumps(
                    result, sort_keys=True, ensure_ascii=False,
                )
            if error_summary is not None:
                values["error_summary"] = str(error_summary)[:4000] or False
            if target in ("passed", "failed", "cancelled"):
                values["completed_at"] = fields.Datetime.now()
            record.write(values)
        return True

    def action_start(self, stage="identity"):
        return self._transition(("queued",), "running", stage=stage)

    def action_advance(self, stage, result=None):
        return self._transition(("running",), "running", stage=stage, result=result)

    def action_pass(self, result=None):
        return self._transition(("running",), "passed", stage="handoff", result=result)

    def action_fail(self, error_summary, result=None):
        return self._transition(
            ("queued", "running"), "failed", result=result,
            error_summary=error_summary,
        )

    def action_cancel(self, reason="cancelled by administrator"):
        return self._transition(
            ("queued", "running"), "cancelled", error_summary=reason,
        )
