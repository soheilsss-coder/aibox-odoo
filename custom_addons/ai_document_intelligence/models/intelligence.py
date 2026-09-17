import base64,hashlib,json,mimetypes
from odoo import api,fields,models
from odoo.addons.ai_gateway.controllers.file_policy import validate_upload, MAX_UPLOAD_BYTES

class AiFileJob(models.Model):
    _name="ai.file.intelligence.job"; _description="Secure File Intelligence Job"; _order="id desc"
    name=fields.Char(required=True); attachment_id=fields.Many2one("ir.attachment",required=True,ondelete="cascade"); company_id=fields.Many2one("res.company",required=True,default=lambda s:s.env.company); requested_by=fields.Many2one("res.users",required=True,default=lambda s:s.env.user); state=fields.Selection([("queued","Queued"),("processing","Processing"),("done","Done"),("failed","Failed")],default="queued",index=True); mime_type=fields.Char(); sha256=fields.Char(index=True); result_json=fields.Text(default="{}"); error=fields.Text()

    @api.model
    def enqueue(self,attachment,question=""):
        if attachment.create_uid != self.env.user and not self.env.user.has_group("base.group_system"):
            # Respect normal attachment ACL; sudo is not a substitute for authorization.
            if not attachment.check_access_rights("read",raise_exception=False): raise PermissionError("file access denied")
        raw=base64.b64decode(attachment.datas or b"")
        validate_upload(attachment.name, raw, max_bytes=MAX_UPLOAD_BYTES)
        digest=hashlib.sha256(raw).hexdigest()
        return self.create({"name":attachment.name,"attachment_id":attachment.id,"mime_type":attachment.mimetype or mimetypes.guess_type(attachment.name)[0],"sha256":digest,"result_json":json.dumps({"question":str(question or "")[:4000]})})
