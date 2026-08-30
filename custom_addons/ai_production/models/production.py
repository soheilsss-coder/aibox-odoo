from odoo import api,fields,models

class AiProductionCheck(models.Model):
    _name="ai.production.check"; _description="Production Certification Check"; _order="checked_at desc"
    name=fields.Char(required=True); category=fields.Selection([("security","Security"),("integration","Integration"),("workflow","Workflow"),("rag","RAG"),("voice","Voice"),("collaboration","Collaboration"),("deployment","Deployment"),("model","Model")],required=True); status=fields.Selection([("pass","PASS"),("fail","FAIL"),("skip","SKIP")],required=True); details=fields.Text(); checked_at=fields.Datetime(default=fields.Datetime.now)

class AiReleaseCertification(models.Model):
    _name="ai.release.certification"; _description="Release Certification"
    version=fields.Char(required=True); state=fields.Selection([("candidate","Candidate"),("certified","Certified"),("blocked","Blocked")],default="candidate"); summary_json=fields.Text(default="{}")
    @api.model
    def certify(self,version):
        checks=self.env["ai.production.check"].search([]); failed=checks.filtered(lambda c:c.status=="fail"); state="certified" if not failed and checks else "blocked"
        return self.create({"version":version,"state":state,"summary_json":"{}"})
