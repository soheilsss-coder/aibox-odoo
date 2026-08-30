import base64
import csv
import hashlib
import io
import json
import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLE_XMLIDS = {
    "employee": "ai_business_tools.role_employee",
    "manager": "ai_business_tools.role_manager",
    "hr_staff": "ai_business_tools.role_hr_staff",
    "hr_manager": "ai_business_tools.role_hr_manager",
    "finance_staff": "ai_business_tools.role_finance_staff",
    "finance_manager": "ai_business_tools.role_finance_manager",
    "warehouse_staff": "ai_business_tools.role_warehouse_staff",
    "warehouse_manager": "ai_business_tools.role_warehouse_manager",
    "project_manager": "ai_business_tools.role_project_manager",
    "executive": "ai_business_tools.role_executive",
    "security": "ai_business_tools.role_security",
    "system_admin": "ai_business_tools.role_system_admin",
}
UPDATABLE_FIELDS = ("department", "job_title", "job_level", "location", "employment_type")


class _DryRunComplete(Exception):
    """Marker exception thrown after a simulated import has collected its
    summary; the enclosing savepoint rolls the ephemeral writes back and
    the wizard state itself is never touched."""


class AiExcelRoleImport(models.TransientModel):
    _name = "ai.customer.excel.role.import"
    _description = "Excel Role Import - Preview and Commit"

    file_name = fields.Char(required=True)
    file_data = fields.Binary(required=True, attachment=False)
    file_sha256 = fields.Char(readonly=True)
    state = fields.Selection([
        ("draft", "Draft"), ("validated", "Validated"),
        ("approved", "Approved"), ("imported", "Imported"), ("failed", "Failed"),
    ], default="draft", readonly=True)
    preview_json = fields.Text(readonly=True)
    error_text = fields.Text(readonly=True)
    warning_text = fields.Text(readonly=True)
    approved_by = fields.Many2one("res.users", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    imported_at = fields.Datetime(readonly=True)
    imported_count = fields.Integer(readonly=True)

    # create + update + dry-run (Phase 1.3)
    dry_run_json = fields.Text(readonly=True)
    create_count = fields.Integer(readonly=True)
    update_count = fields.Integer(readonly=True)
    unchanged_count = fields.Integer(readonly=True)

    # -- decoding / validation --------------------------------------------

    def _decode_rows(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError("Upload an Excel or CSV file first.")
        raw = base64.b64decode(self.file_data)
        self.file_sha256 = hashlib.sha256(raw).hexdigest()
        if self.file_name.lower().endswith(".csv"):
            text = raw.decode("utf-8-sig")
            return list(csv.DictReader(io.StringIO(text)))
        try:
            import openpyxl
        except ImportError as exc:
            raise UserError("openpyxl is required for .xlsx role imports.") from exc
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        headers = [str(v or "").strip() for v in next(ws.iter_rows(values_only=True))]
        return [dict(zip(headers, row)) for row in ws.iter_rows(min_row=2, values_only=True)
                if row and any(v is not None for v in row)]

    def _validate_rows(self, rows):
        """Build the CLEAN row list. Email (the login, i.e. the stable
        matching key) is the identity used for the create/update decision.
        An existing user is no longer rejected: it is classified as an
        update/no-op by _row_field_diffs at plan time."""
        errors, warnings, clean = [], [], []
        seen = set()
        for line, row in enumerate(rows, 2):
            name = str(row.get("name") or "").strip()
            email = str(row.get("email") or "").strip().lower()
            role = str(row.get("role") or "").strip().lower()
            department = str(row.get("department") or "").strip()
            job_title = str(row.get("job_title") or "").strip()
            job_level = str(row.get("job_level") or "").strip()
            location = str(row.get("location") or "").strip()
            employment_type = str(row.get("employment_type") or "").strip()
            if not name or not email:
                errors.append(f"line {line}: name and email are required")
                continue
            if not EMAIL_RE.match(email):
                errors.append(f"line {line}: invalid email '{email}'")
                continue
            if email in seen:
                errors.append(f"line {line}: duplicate email '{email}'")
                continue
            seen.add(email)
            if role and role not in ROLE_XMLIDS:
                errors.append(f"line {line}: unknown role '{role}'. Import is blocked; no silent fallback.")
                continue
            if not role:
                policy_role = self.env["ai.customer.role.policy"].resolve(
                    self.env.company, department=department, position=job_title, job_level=job_level,
                    manager_required=bool(row.get("manager_email")), location=location, employment_type=employment_type
                )
                if not policy_role:
                    errors.append(f"line {line}: no role policy matched department/position/job_level/manager/location/employment_type; import blocked")
                    continue
                role = next((k for k, v in ROLE_XMLIDS.items() if self.env.ref(v).id == policy_role.id), "")
                if not role:
                    errors.append(f"line {line}: role policy resolved to an unknown product role; import blocked")
                    continue
            clean.append({
                "line": line, "name": name, "email": email, "role": role,
                "department": department, "job_title": job_title, "job_level": job_level,
                "location": location, "employment_type": employment_type,
            })
            if role in {"system_admin", "security", "executive"}:
                warnings.append(f"line {line}: elevated role '{role}' requires explicit approval")
        return clean, errors, warnings

    # -- create + update plan ---------------------------------------------

    def _resolve_department(self, name):
        if not name:
            return False
        return self.env["hr.department"].sudo().search(
            [("name", "=ilike", name)], limit=1
        ) or self.env["hr.department"].sudo().create({"name": name})

    def _resolve_job(self, name):
        if not name:
            return False
        return self.env["hr.job"].sudo().search(
            [("name", "=ilike", name)], limit=1
        ) or self.env["hr.job"].sudo().create({"name": name})

    def _row_field_diffs(self, row, user, employee, role_group):
        """Exact list of fields that WOULD change for an existing user:
        [{"field": <name>, "old": <value>, "new": <value>}, ...]. An empty
        list means the row is a no-op. login is intentionally NOT offered
        for update - it is the stable matching key/identity."""
        diffs = []
        name = str(row["name"]).strip()
        email = str(row["email"]).strip().lower()
        if user.name != name:
            diffs.append({"field": "user.name", "old": user.name or "", "new": name})
        if (user.email or "").lower() != email:
            diffs.append({"field": "user.email", "old": user.email or "", "new": email})
        if role_group.id not in user.groups_id.ids:
            diffs.append({"field": "groups.role", "old": "current", "new": role_group.name})
        if not employee:
            diffs.append({"field": "employee", "old": "missing", "new": "create employee record"})
        else:
            if (employee.work_email or "").lower() != email:
                diffs.append({"field": "employee.work_email", "old": employee.work_email or "", "new": email})
            # Deliberately name-only comparisons: this function must be
            # side-effect free (it runs during preview/dry-run planning),
            # so it never creates departments/jobs - only _create_row /
            # _update_row do that, at commit time.
            if row.get("department") and (not employee.department_id or employee.department_id.name != str(row["department"]).strip()):
                diffs.append({"field": "employee.department", "old": employee.department_id.name or "", "new": str(row["department"]).strip()})
            if row.get("job_title") and (not employee.job_id or employee.job_id.name != str(row["job_title"]).strip()):
                diffs.append({"field": "employee.job", "old": employee.job_id.name or "", "new": str(row["job_title"]).strip()})
        return diffs

    def _create_row(self, row, role_group):
        dept = self._resolve_department(row.get("department") or "")
        job = self._resolve_job(row.get("job_title") or "")
        user = self.env["res.users"].sudo().create({
            "name": row["name"], "login": row["email"], "email": row["email"],
            "groups_id": [(6, 0, [role_group.id])],
            "company_id": self.env.company.id,
            "company_ids": [(4, self.env.company.id)],
        })
        employee_vals = {"name": row["name"], "user_id": user.id, "work_email": row["email"]}
        if dept:
            employee_vals["department_id"] = dept.id
        if job:
            employee_vals["job_id"] = job.id
        self.env["hr.employee"].sudo().create(employee_vals)
        self.env["ai.customer.role.assignment"].sudo().create({
            "user_id": user.id, "role_group_id": role_group.id, "source": "direct",
            "company_id": self.env.company.id, "managed_by": "excel", "reason": "Excel onboarding role assignment",
        })
        return user

    def _update_row(self, row, user, employee, diffs):
        """Apply ONLY the changed fields identified by _row_field_diffs.
        Nothing that already matches is rewritten, so a no-op row is never
        even written to."""
        user_vals = {}
        for d in diffs:
            if d["field"] == "user.name":
                user_vals["name"] = d["new"]
            elif d["field"] == "user.email":
                user_vals["email"] = d["new"]
        if user_vals:
            user.sudo().write(user_vals)
        role_group = self.env.ref(ROLE_XMLIDS[row["role"]], raise_if_not_found=True)
        if "groups.role" in {d["field"] for d in diffs}:
            user.sudo().write({"groups_id": [(6, 0, [role_group.id])]})
            assignment = self.env["ai.customer.role.assignment"].sudo().search(
                [("user_id", "=", user.id)], limit=1)
            if assignment:
                assignment.sudo().write({"role_group_id": role_group.id,
                                         "reason": "Excel role update"})
            else:
                self.env["ai.customer.role.assignment"].sudo().create({
                    "user_id": user.id, "role_group_id": role_group.id, "source": "direct",
                    "company_id": self.env.company.id, "managed_by": "excel",
                    "reason": "Excel role update",
                })
        dept = self._resolve_department(row.get("department") or "")
        job = self._resolve_job(row.get("job_title") or "")
        if employee:
            emp_vals = {}
            if "employee.work_email" in {d["field"] for d in diffs}:
                emp_vals["work_email"] = row["email"]
            if "employee.department" in {d["field"] for d in diffs}:
                emp_vals["department_id"] = dept.id if dept else False
            if "employee.job" in {d["field"] for d in diffs}:
                emp_vals["job_id"] = job.id if job else False
            if emp_vals:
                employee.sudo().write(emp_vals)
        else:
            emp_vals = {"name": row["name"], "user_id": user.id, "work_email": row["email"]}
            if dept:
                emp_vals["department_id"] = dept.id
            if job:
                emp_vals["job_id"] = job.id
            self.env["hr.employee"].sudo().create(emp_vals)

    def _apply_rows(self, rows):
        """Single code path shared by the dry-run (rolled back after) and
        the real commit: classify every row and perform exactly the work
        its classification demands. Returns the summary that the dry-run
        presents and the import records in the audit log."""
        summary = {"create_count": 0, "update_count": 0, "unchanged_count": 0,
                   "creates": [], "updates": []}
        for row in rows:
            existing = self.env["res.users"].sudo().search(
                [("login", "=", row["email"])], limit=1)
            role_group = self.env.ref(ROLE_XMLIDS[row["role"]], raise_if_not_found=True)
            employee = existing and self.env["hr.employee"].sudo().search(
                [("user_id", "=", existing.id)], limit=1)
            if not existing:
                user = self._create_row(row, role_group)
                summary["create_count"] += 1
                summary["creates"].append({"email": row["email"], "user_id": user.id,
                                           "role": row["role"]})
                continue
            diffs = self._row_field_diffs(row, existing, employee, role_group)
            if not diffs:
                summary["unchanged_count"] += 1
                continue
            self._update_row(row, existing, employee, diffs)
            summary["update_count"] += 1
            summary["updates"].append({
                "email": row["email"], "user_id": existing.id,
                "role": row["role"],
                "fields": [d["field"] for d in diffs],
            })
        return summary

    # -- actions ----------------------------------------------------------

    def action_validate(self):
        self.ensure_one()
        rows = self._decode_rows()
        clean, errors, warnings = self._validate_rows(rows)
        self.error_text = "\n".join(errors) or False
        self.warning_text = "\n".join(warnings) or False
        # Plan the create/update/unchanged split NOW so the preview shows
        # the admin exactly what a commit would do before anything is
        # approved. The same decision is recomputed at commit time by
        # _apply_rows, so the preview and the commit cannot drift.
        plan = {"create_count": 0, "update_count": 0, "unchanged_count": 0,
                "updates": []}
        if clean:
            for row in clean:
                existing = self.env["res.users"].sudo().search(
                    [("login", "=", row["email"])], limit=1)
                if not existing:
                    plan["create_count"] += 1
                    continue
                role_group = self.env.ref(ROLE_XMLIDS[row["role"]], raise_if_not_found=True)
                employee = self.env["hr.employee"].sudo().search(
                    [("user_id", "=", existing.id)], limit=1)
                diffs = self._row_field_diffs(row, existing, employee, role_group)
                if diffs:
                    plan["update_count"] += 1
                    plan["updates"].append({"email": row["email"], "fields": diffs})
                else:
                    plan["unchanged_count"] += 1
        self.preview_json = json.dumps({
            "sha256": self.file_sha256,
            "rows": clean,
            "row_count": len(clean),
            "elevated": sum(1 for r in clean if r["role"] in {"system_admin", "security", "executive"}),
            "create_count": plan["create_count"],
            "update_count": plan["update_count"],
            "unchanged_count": plan["unchanged_count"],
            "updates": plan["updates"],
        }, ensure_ascii=False, indent=2)
        self.write({
            "create_count": plan["create_count"],
            "update_count": plan["update_count"],
            "unchanged_count": plan["unchanged_count"],
        })
        self.state = "validated" if not errors else "failed"
        return True

    def action_dry_run(self):
        """Simulate the real commit inside a savepoint and roll it ALL
        back. Reuses the exact same _apply_rows the commit runs, so the
        summary (creates / updates / unchanged + per-row fields) is
        produced by actually executing the writes - not by re-reading the
        file - and nothing persists."""
        self.ensure_one()
        if self.state not in ("draft", "validated", "approved"):
            raise UserError("Only a draft/validated/approved import can be dry-run.")
        if not self.preview_json:
            raise UserError("Run validation first.")
        rows = json.loads(self.preview_json)["rows"]
        summary = {}
        try:
            with self.env.cr.savepoint():
                summary = self._apply_rows(rows)
                raise _DryRunComplete()
        except _DryRunComplete:
            pass
        self.dry_run_json = json.dumps(summary, ensure_ascii=False, indent=2)
        return True

    def action_approve(self):
        self.ensure_one()
        if self.state != "validated":
            raise UserError("Only a successfully validated import can be approved.")
        if not self.preview_json:
            raise UserError("Run validation first.")
        self.write({
            "state": "approved",
            "approved_by": self.env.user.id,
            "approved_at": fields.Datetime.now(),
        })
        return True

    def action_import(self):
        self.ensure_one()
        if self.state != "approved":
            raise UserError("Import requires an explicit approval after validation.")
        payload = json.loads(self.preview_json or "{}")
        rows = payload.get("rows") or []
        with self.env.cr.savepoint():
            summary = self._apply_rows(rows)
            if "ai.gateway.audit.log" in self.env:
                self.env["ai.gateway.audit.log"].sudo().log(
                    user_id=self.env.user.id, source="customer_control_plane",
                    action="excel_role_import_committed",
                    payload={"sha256": self.file_sha256, "summary": summary},
                )
        self.write({
            "state": "imported", "imported_at": fields.Datetime.now(),
            "imported_count": summary["create_count"] + summary["update_count"],
            "create_count": summary["create_count"],
            "update_count": summary["update_count"],
            "unchanged_count": summary["unchanged_count"],
        })
        return True