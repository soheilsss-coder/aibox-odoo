from odoo import api,fields,models

class AiCorrespondenceTemplate(models.Model):
    _name="ai.correspondence.template"; _description="Official Correspondence Template"
    name=fields.Char(required=True); code=fields.Char(required=True,index=True); body_html=fields.Html(required=True); required_fields_json=fields.Text(default="[]"); group_ids=fields.Many2many("res.groups"); active=fields.Boolean(default=True)
    _sql_constraints=[("code_unique","unique(code)","Template code must be unique.")]

class AiCorrespondence(models.Model):
    _name="ai.correspondence"; _description="Generated Official Correspondence"; _order="id desc"
    name=fields.Char(required=True); template_id=fields.Many2one("ai.correspondence.template",required=True); requester_id=fields.Many2one("res.users",required=True,default=lambda s:s.env.user); state=fields.Selection([("draft","Draft"),("pending_approval","Pending Approval"),("approved","Approved"),("rejected","Rejected"),("issued","Issued")],default="draft",index=True); values_json=fields.Text(default="{}"); attachment_id=fields.Many2one("ir.attachment")

    @api.model
    def validate_values(self,template,values):
        import json
        required=json.loads(template.required_fields_json or "[]")
        missing=[x for x in required if not values.get(x)]
        return missing
