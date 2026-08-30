from odoo import api, fields, models

class AiBuzzIdentity(models.Model):
    _name = "ai.collab.buzz.identity"
    _description = "Buzz External Identity mapped to Odoo User/Agent"
    external_subject = fields.Char(required=True, index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    agent_id = fields.Many2one("ai.gateway.agent.identity", ondelete="set null", index=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company, index=True)
    active = fields.Boolean(default=True)
    _sql_constraints=[("subject_company_unique","unique(external_subject,company_id)","Buzz identity already mapped for this company.")]

    @api.model
    def resolve(self, external_subject, company=None):
        return self.sudo().search([("external_subject","=",external_subject),("company_id","=",(company or self.env.company).id),("active","=",True)],limit=1)
