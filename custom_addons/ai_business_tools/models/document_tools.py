import logging
from datetime import date

from odoo import models
from odoo.exceptions import AccessError, UserError
from odoo.addons.llm_tool.decorators import llm_tool

_logger = logging.getLogger(__name__)

# Whitelist of resolvable {{token}} values inside a docx template. Anything
# not in this list is left untouched and reported back as "unfilled", so a
# prompt-injected placeholder can never turn into raw SQL or ORM access.
_RESOLVABLE_FIELDS = {
    "employee.name", "employee.work_email", "employee.identification_id",
    "employee.job_id.name", "employee.department_id.name",
    "employee.manager_id.name", "employee.parent_id.name",
    "employee.barcode",
    "contract.wage", "contract.state", "contract.date_start",
    "contract.date_end", "company.name", "today",
    "current_user.name", "current_user.email",
}


def _resolve_value(env, employee, token):
    if token == "today":
        return date.today().isoformat()
    if token == "current_user.name":
        return env.user.name
    if token == "current_user.email":
        return env.user.email or ""
    if token == "company.name":
        try:
            return env.company.name
        except AttributeError:
            return ""
    if token == "employee.name":
        return employee.name or ""
    if token == "employee.work_email":
        return employee.work_email or ""
    if token == "employee.identification_id":
        return employee.identification_id or ""
    if token == "employee.job_id.name":
        return employee.job_id.name if employee.job_id else ""
    if token == "employee.department_id.name":
        return employee.department_id.name if employee.department_id else ""
    if token == "employee.manager_id.name":
        return employee.manager_id.name if employee.manager_id else ""
    if token == "employee.parent_id.name":
        return employee.parent_id.name if employee.parent_id else ""
    if token == "employee.barcode":
        return employee.barcode or ""
    if token.startswith("contract."):
        contract = employee.contract_id or (employee.sudo()._get_active_contracts_for_payslip()
                                            if hasattr(employee, "_get_active_contracts_for_payslip") else employee.contract_id)
        if not contract:
            return ""
        if token == "contract.wage":
            return "%s" % contract.wage
        if token == "contract.state":
            return contract.state or ""
        if token == "contract.date_start":
            return "%s" % (contract.date_start or "")
        if token == "contract.date_end":
            return "%s" % (contract.date_end or "")
    return None


def _render_docx(stream, tokens, env, employee, unfilled):
    """Fill {{token}} placeholders across paragraphs and tables in-place.
    Handles tokens split over multiple runs by rewriting only the first
    run of an affected paragraph and clearing the rest."""
    from docx import Document
    doc = Document(stream)

    def fill_text(text):
        if "{{" not in text:
            return text, False
        changed = False
        for key in tokens:
            step = "{{%s}}" % key
            if step not in text:
                continue
            value = _resolve_value(env, employee, key)
            if value is None:
                # Resolvable token whose data is missing for this person
                # (e.g. no active contract): leave the placeholder in place
                # and report it as unfilled rather than guessing.
                unfilled.append(key)
                continue
            text = text.replace(step, value if isinstance(value, str) else str(value))
            changed = True
        return text, changed

    def fill_runs(paragraph):
        full = "".join(r.text for r in paragraph.runs)
        if "{{" not in full:
            return
        new_text, changed = fill_text(full)
        if changed:
            if paragraph.runs:
                paragraph.runs[0].text = new_text
                for r in paragraph.runs[1:]:
                    r.text = ""

    def walk_table(table):
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    fill_runs(p)

    for p in doc.paragraphs:
        fill_runs(p)
    for table in doc.tables:
        walk_table(table)

    import io
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _audit(env, action, payload, success=True, error_message=None):
    env["ai.gateway.audit.log"].sudo().log(
        user_id=env.user.id, source="tool", action=action,
        payload=payload, success=success, error_message=error_message,
    )


class LLMToolDocument(models.Model):
    _inherit = "llm.tool"

    @llm_tool(destructive_hint=True)
    def fill_document_template(self, template_attachment_id: int = 0,
                               target_name: str = "", target_email: str = "",
                               employee_code: str = "",
                               description: str = "",
                               idempotency_key: str = "") -> dict:
        """Fill a previously uploaded Word (.docx) template with real
        HR/payroll data. The user must have attached the .docx template
        file to the current conversation; pass its attachment id here.
        target_name OR target_email OR employee_code identifies whose
        data fills the placeholders. The template fills {{placeholders}}
        like {{employee.name}}, {{employee.department_id.name}},
        {{employee.job_id.name}}, {{employee.manager_id.name}},
        {{contract.wage}}, {{company.name}}, {{today}} with the person's
        real values. Anything unknown is left as-is and reported back.

        REQUIRED: template_attachment_id, exactly one target identifier -
        if missing, do NOT invent values; ask the user first.

        Parameters:
            template_attachment_id: id of the attached .docx template
                (shown in the conversation).
            target_name: Name (or partial name) of the person whose HR
                data should be filled in.
            target_email: Alternative - their work email.
            employee_code: Alternative - their employee code.
            description: Optional note about what the document is for
                (used in the audit record).
            idempotency_key: Optional - reuse on retries to avoid
                creating duplicate filled files.
        """
        self.env["ai.gateway.execution.gate"].authorize("fill_document_template")

        cached = self.env["ai.gateway.idempotency"].get_cached(self.env.user.id, idempotency_key)
        if cached is not None:
            return cached

        missing = []
        if not template_attachment_id:
            missing.append("template_attachment_id")
        if not (target_name or target_email or employee_code):
            missing.append("target (نام/ایمیل/کد کارمند)")
        if missing:
            return {"error": "missing_required_field", "missing_fields": missing,
                    "hint": "دقیقاً همین فیلد(های) گم‌شده را از کاربر بپرس، بقیه‌ی اطلاعات را دوباره نپرس."}

        payload = {"template_attachment_id": template_attachment_id,
                   "target_name": target_name, "target_email": target_email,
                   "employee_code": employee_code, "description": description}

        try:
            template = self.env["ir.attachment"].browse(int(template_attachment_id)).sudo().exists()
        except (AccessError, ValueError):
            template = self.env["ir.attachment"]
        if not template:
            _audit(self.env, "fill_document_template", payload, success=False, error_message="template_not_found")
            return {"error": "template_not_found",
                    "message": "فایل قالب پیدا نشد؛ مطمئن شوید فایل .docx به این گفتگو پیوست شده است."}
        if not (template.mimetype or "").endswith(("docx", "doc", "octet-stream")):
            _audit(self.env, "fill_document_template", payload, success=False, error_message="template_not_docx")
            return {"error": "template_not_docx", "message": "فایل پیوست یک سند Word (.docx) نیست."}

        employee = False
        if employee_code:
            code = employee_code.strip()
            domain = ([("employee_code", "=", code)] if "employee_code" in self.env["hr.employee"]._fields else
                      [("barcode", "=", code)] if "barcode" in self.env["hr.employee"]._fields else
                      [("identification_id", "=", code)])
            employees = self.env["hr.employee"].search(domain, limit=20)
            if len(employees) > 1:
                return {"error": "ambiguous_assignee", "message": "چند کارمند با این کد پیدا شد؛ کد دقیق را وارد کنید.",
                        "candidates": employees.mapped("name")}
            employee = employees[:1] if employees else False
        elif target_email:
            employees = self.env["hr.employee"].search(
                [("work_email", "=ilike", target_email.strip())], limit=20)
            if len(employees) > 1:
                return {"error": "ambiguous_assignee", "message": "چند کارمند با این ایمیل پیدا شد.",
                        "candidates": employees.mapped("name")}
            employee = employees[:1] if employees else False
        else:
            employees = self.env["hr.employee"].search(
                [("name", "ilike", target_name)], limit=20)
            if len(employees) > 1:
                return {"error": "ambiguous_assignee", "message": "چند کارمند با این نام پیدا شد؛ نام کامل، ایمیل یا کد را مشخص کنید.",
                        "candidates": employees.mapped("name")}
            employee = employees[:1] if employees else False
        if not employee:
            _audit(self.env, "fill_document_template", payload, success=False, error_message="employee_not_found")
            return {"error": "employee_not_found",
                    "message": "کارمندی با این مشخصات در محدوده‌ی دسترسی شما پیدا نشد."}

        try:
            import docx  # noqa: F401  (package is pinned in requirements.lock)
        except Exception:
            return {"error": "renderer_unavailable",
                    "message": "موتور پایتون‌داک روی سرور نصب نیست (python-docx)."}

        unfilled = []
        raw = False
        try:
            raw = template.datas
        except Exception:
            raw = template.raw if hasattr(template, "raw") else None
        if not raw:
            _audit(self.env, "fill_document_template", payload, success=False, error_message="template_empty")
            return {"error": "template_empty", "message": "فایل قالب خالی یا ناخوانا است."}
        if hasattr(raw, "decode"):
            raw = raw.decode("latin1") if False else raw  # keep bytes

        try:
            import io
            filled = _render_docx(io.BytesIO(raw), sorted(_RESOLVABLE_FIELDS), self.env, employee, unfilled)
        except Exception as exc:
            _audit(self.env, "fill_document_template", payload, success=False, error_message=str(exc))
            return {"error": "render_failed", "message": "پردازش قالب ناموفق بود."}

        import base64
        output_name = "filled_%s.docx" % (template.name or "document")
        try:
            out_att = self.env["ir.attachment"].sudo().create({
                "name": output_name,
                "datas": base64.b64encode(filled).decode("ascii"),
                "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "company_id": employee.company_id.id if employee.company_id else False,
            })
        except (AccessError, UserError) as exc:
            _audit(self.env, "fill_document_template", payload, success=False, error_message=str(exc))
            return {"error": "access_denied", "message": "ذخیره‌ی سند خروجی مجاز نیست."}

        result = {"status": "filled", "attachment_id": out_att.id,
                  "filename": output_name,
                  "filled_for": employee.name,
                  "unfilled_placeholders": sorted(set(unfilled)),
                  "url": "/web/content/%s/%s" % (out_att.id, output_name)}
        _audit(self.env, "fill_document_template", payload)
        return result

    @llm_tool(destructive_hint=True)
    def generate_qweb_report(self, report_xmlid: str = "",
                             target_name: str = "", record_id: int = 0) -> dict:
        """Generate an Odoo native QWeb/PDF report and save it as a
        downloadable attachment. Only report xmlids on an explicit
        allowlist may be rendered - unknown or arbitrary xmlids are
        rejected to keep this from becoming a data-leak channel. Each
        allowlisted report reuses Odoo's OWN standard QWeb template
        (the <report> record for that model), never a from-scratch one.

        Allowlisted reports:
          'ai_business_tools.report_hr_directory' - HR staff directory
              for one employee (human resources module).
          'sale.action_report_saleorder' - Odoo's standard Sale Order
              report (requires the 'sale' module; pass a sale.order id
              via record_id).
          'account.action_report_invoice' - Odoo's standard Invoice
              report (requires the 'account' module; pass an
              account.move id via record_id).

        Parameters:
            report_xmlid: The exact xmlid of the report to render.
            target_name: Whose data the report is about (for the HR
                directory, which is per-person).
            record_id: For the sale/invoice reports, the id of the
                sale.order / account.move to render. Optional and
                unused for the HR directory.
        """
        self.env["ai.gateway.execution.gate"].authorize("generate_qweb_report")

        _ALLOWED_REPORTS = {
            "ai_business_tools.report_hr_directory",
            "sale.action_report_saleorder",
            "account.action_report_invoice",
        }
        # (report xmlid, model, id source) - each maps to Odoo's own
        # standard <report> record; we only supply the record ids.
        _REPORT_SPEC = {
            "ai_business_tools.report_hr_directory": ("hr.employee", "name"),
            "sale.action_report_saleorder": ("sale.order", "id"),
            "account.action_report_invoice": ("account.move", "id"),
        }
        if report_xmlid not in _ALLOWED_REPORTS:
            _audit(self.env, "generate_qweb_report", {"report_xmlid": report_xmlid},
                   success=False, error_message="report_not_allowlisted")
            return {"error": "report_not_allowlisted",
                    "message": "این گزارش در فهرست مجاز نیست. گزارش‌های مجاز: %s" % ", ".join(sorted(_ALLOWED_REPORTS))}

        payload = {"report_xmlid": report_xmlid, "target_name": target_name,
                   "record_id": record_id}
        model_name, by = _REPORT_SPEC[report_xmlid]

        if report_xmlid == "ai_business_tools.report_hr_directory":
            if not target_name:
                return {"error": "missing_required_field", "missing_fields": ["target_name"],
                        "hint": "نام کارمند را از کاربر بپرس."}
            records = self.env["hr.employee"].search([("name", "ilike", target_name)], limit=20)
            if len(records) > 1:
                return {"error": "ambiguous_assignee", "message": "چند کارمند با این نام پیدا شد؛ نام کامل را مشخص کنید.",
                        "candidates": records.mapped("name")}
            records = records[:1] if records else self.env["hr.employee"]
            if not records:
                _audit(self.env, "generate_qweb_report", payload, success=False, error_message="employee_not_found")
                return {"error": "employee_not_found", "message": "کارمندی با این نام پیدا نشد."}
        else:
            # Sale order / Invoice: Odoo's standard model-driven
            # reports. The record must exist and be readable by the
            # CURRENT user - record rules apply exactly as for any
            # other read, so a user who cannot see the order/invoice
            # gets an access-denied here, not a leaked PDF.
            if not record_id:
                return {"error": "missing_required_field", "missing_fields": ["record_id"],
                        "hint": "شناسه رکورد (sale.order / account.move) را از کاربر بپرس."}
            try:
                records = self.env[model_name].browse(int(record_id)).exists()
                records.check_access("read")
            except (AccessError, ValueError):
                _audit(self.env, "generate_qweb_report", payload, success=False, error_message="record_access_denied")
                return {"error": "access_denied",
                        "message": "دسترسی به این سند یا گزارش مجاز نیست."}
            if not records:
                _audit(self.env, "generate_qweb_report", payload, success=False, error_message="record_not_found")
                return {"error": "record_not_found", "message": "رکورد موردنظر پیدا نشد."}

        try:
            report = self.env.ref(report_xmlid)
        except Exception:
            _audit(self.env, "generate_qweb_report", payload, success=False, error_message="report_missing")
            return {"error": "report_missing", "message": "گزارش در دیتابیس جاری وجود ندارد (ماژول متناظر نصب نیست)."}
        try:
            content, content_type = report._render_qweb_pdf(records.ids)
        except Exception as exc:
            _audit(self.env, "generate_qweb_report", payload, success=False, error_message=str(exc))
            return {"error": "render_failed", "message": "ساخت PDF ناموفق بود."}

        import base64
        output_name = "%s.pdf" % report_xmlid.split(".")[-1]
        out_att = self.env["ir.attachment"].sudo().create({
            "name": output_name,
            "datas": base64.b64encode(content).decode("ascii"),
            "mimetype": "application/pdf",
        })
        _audit(self.env, "generate_qweb_report", payload)
        return {"status": "generated", "attachment_id": out_att.id, "filename": output_name,
                "url": "/web/content/%s/%s" % (out_att.id, output_name)}