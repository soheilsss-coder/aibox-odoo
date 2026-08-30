from odoo import api, fields, models

class AiWorkspace(models.Model):
    _name="ai.collab.workspace"; _description="AI Collaboration Workspace"
    name=fields.Char(required=True); kind=fields.Selection([("private","Private"),("team","Team"),("department","Department"),("company","Company")],required=True,default="team"); company_id=fields.Many2one("res.company",required=True,default=lambda s:s.env.company); department_id=fields.Many2one("hr.department"); member_ids=fields.Many2many("res.users",string="Members"); agent_name=fields.Char(); active=fields.Boolean(default=True)

class AiWorkspaceMessage(models.Model):
    _name="ai.collab.message"; _description="AI Collaboration Message"; _order="id desc"
    workspace_id=fields.Many2one("ai.collab.workspace",required=True,ondelete="cascade",index=True); author_id=fields.Many2one("res.users",required=True,default=lambda s:s.env.user); body=fields.Text(required=True); message_type=fields.Selection([("user","User"),("agent","Agent"),("system","System")],default="user"); attachment_ids=fields.Many2many("ir.attachment"); created_at=fields.Datetime(default=fields.Datetime.now,index=True)

    @api.model
    def post(self,workspace,body,message_type="user"):
        if self.env.user not in workspace.member_ids and not self.env.user.has_group("base.group_system"):
            raise PermissionError("workspace access denied")
        return self.create({"workspace_id":workspace.id,"body":body,"message_type":message_type})
