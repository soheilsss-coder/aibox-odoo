from odoo import fields, models
from odoo.exceptions import AccessError
from odoo.addons.llm_tool.decorators import llm_tool


def _audit(env, action, payload, success=True, error_message=None):
    env["ai.gateway.audit.log"].sudo().log(
        user_id=env.user.id, source="tool", action=action,
        payload=payload, success=success, error_message=error_message,
    )


class CompanyDocument(models.Model):
    """A file with an explicit access level. Visibility is enforced by
    the record rule in security/document_rules.xml, not by this model's
    Python code - so it applies identically whether the document is
    opened from the web client, the gateway, or an AI tool call."""

    _name = "company.document"
    _description = "Company Document"
    _order = "create_date desc"

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True, ondelete="restrict",
        default=lambda self: self.env.company,
        help="Tenant boundary for every document and its derived chunks.",
    )
    file = fields.Binary(attachment=True)
    file_name = fields.Char()
    description = fields.Text()
    access_level = fields.Selection(
        [("company", "کل سازمان"), ("group", "گروه محدود"),
         ("team", "تیم محدود"), ("department", "دپارتمان محدود"),
         ("personal", "شخصی"), ("restricted", "محرمانه"), ("confidential", "خیلی محرمانه")],
        required=True, default="company",
    )
    group_id = fields.Many2one(
        "res.groups", string="Restricted To Group",
        help="Only used when access_level = group",
    )
    # Roadmap item #2 (Department): same access-level pattern as
    # access_level=group, but the scope is taken automatically from
    # the viewer's own hr.department (via employee_id.department_id)
    # instead of a manually-picked group - see document_rules.xml.
    department_id = fields.Many2one(
        "hr.department", string="Restricted To Department",
        help="Only used when access_level = department",
    )
    owner_id = fields.Many2one(
        "res.users", string="Owner", default=lambda self: self.env.user,
        help="Only used when access_level = personal",
    )
    member_ids = fields.Many2many("res.users", string="Team Members")
    allowed_user_ids = fields.Many2many("res.users", "company_document_allowed_user_rel", string="Explicitly Allowed Users")
    classification = fields.Selection([("public","Public"),("internal","Internal"),("confidential","Confidential"),("restricted","Restricted"),("pii","PII")], default="internal", required=True)
    project_id = fields.Integer(index=True, help="Optional project resource identifier for FGA.")
    folder_id = fields.Integer(index=True, help="Optional folder resource identifier for FGA.")


class LLMToolDocument(models.Model):
    _inherit = "llm.tool"

    @llm_tool(read_only_hint=True)
    def list_documents(self, query: str = "") -> dict:
        """List documents visible to the CURRENT user only - company-wide
        documents, documents of groups the user belongs to, and the
        user's own personal documents. This never returns documents the
        current user is not entitled to see; the filtering is done by
        Odoo's own record rule, not by this method's logic.

        Parameters:
            query: Optional text to filter by document name.
        """
        domain = [("name", "ilike", query)] if query else []
        docs = self.env["company.document"].search(domain)
        result = {"count": len(docs), "documents": [
            {"id": d.id, "name": d.name, "access_level": d.access_level,
             "description": d.description or ""}
            for d in docs
        ]}
        # Context Firewall (roadmap #28) - GAP FOUND during the v22
        # merge's own audit pass: `description` is free text a
        # document's uploader wrote, i.e. exactly the "document-sourced
        # free text" category context_firewall.py's own docstring says
        # this should apply to. search_documents_semantic already did
        # this for excerpt content; list_documents/get_document had
        # simply been missed in every branch. Scrubs any secret-shaped
        # string before it ever reaches the model's context.
        if hasattr(self, "_context_firewall"):
            result = self._context_firewall(result)
        return result

    @llm_tool(read_only_hint=True)
    def get_document(self, document_id: int = 0) -> dict:
        """Get metadata for one document by id. Returns an access-denied
        error (not the document) if the current user is not entitled to
        see it - enforced by the same record rule as list_documents.

        Parameters:
            document_id: The company.document record id.
        """
        if not document_id:
            return {"error": "missing_required_field", "missing_fields": ["document_id"]}
        try:
            doc = self.env["company.document"].browse(document_id)
            doc.check_access("read")
            result = {"id": doc.id, "name": doc.name, "access_level": doc.access_level,
                      "description": doc.description or "", "file_name": doc.file_name or ""}
            if hasattr(self, "_context_firewall"):
                result = self._context_firewall(result)
            return result
        except AccessError as exc:
            _audit(self.env, "get_document", {"document_id": document_id},
                   success=False, error_message=str(exc))
            return {"error": "access_denied"}
