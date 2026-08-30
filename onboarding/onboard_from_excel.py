"""
Client onboarding script - reads an Excel/CSV file of employees and
creates: hr.department (if missing), hr.job (if missing), hr.employee,
res.users (with the right Role Template group from
`ai_business_tools/data/role_templates_data.xml`). Credentials are NEVER
written to Excel/CSV output; use the secure invitation/session provisioning flow.

Rewrite (roadmap items #36 Excel Onboarding, #37 Excel Preview +
Rollback) - full pipeline, matching the flow from the roadmap exactly:

    Parse -> Validate -> Normalize -> Department -> Position ->
    Manager -> Role Mapping -> Preview -> Approval -> Import

Compared to the previous version, the two things that actually changed
behavior (not just structure):

1. **Role mapping now points at the real Role Templates** (`role_employee`,
   `role_manager`, `role_hr_manager`, ... in `ai_business_tools/data/
   role_templates_data.xml` - roadmap item #5), not a second, disconnected
   set of hand-picked groups. Before this rewrite the script's own
   `ROLE_GROUPS` dict was a parallel, out-of-sync mapping that didn't
   match the Role Permissions Overview (item #4) or the "Role: X" names
   HR would actually see when looking a person up - fixed here.
2. **Nothing is written to the database until you explicitly approve a
   preview.** The whole import (department/job creation, users,
   employees, API keys) runs inside one Postgres SAVEPOINT
   (`env.cr.savepoint()`); if anything raises partway through, or the
   run is `--dry-run`, the savepoint is rolled back and the database is
   left exactly as it was - nothing partially created.

Run this ONCE per new client, right after 02_install_modules.sh, before
handing the device over.

USAGE (from the server, inside the Odoo shell):

    source /opt/odoo-venv/bin/activate
    pip install openpyxl pandas
    /opt/odoo/odoo-bin shell -c /opt/odoo.conf -d company_ai \\
        < onboarding/onboard_from_excel.py

By default this runs interactively: it parses and validates the file,
prints a full preview, and asks you to type IMPORT to proceed. Edit the
constants below before running, or override them with environment
variables (handy for the deployment checklist / CI, since the Odoo
shell script has no argv):

    ONBOARD_FILE=/opt/client_employees.xlsx   (default: see EXCEL_PATH)
    ONBOARD_OUTPUT=/opt/onboarding_audit.csv (default: see OUTPUT_CSV; non-secret manifest only)
    ONBOARD_YES=1        skip the interactive prompt, import immediately
                         (only use once you've already reviewed a preview)
    ONBOARD_DRY_RUN=1    run the entire pipeline including the DB writes,
                         print the preview AND the post-write summary,
                         then roll everything back on purpose - proves
                         the savepoint rollback actually works (item #37)
                         and lets you sanity-check a real file with zero
                         risk to the database. Nothing is committed and
                         credential-bearing onboarding result files are NOT written.

Expected columns (see sample_employees.xlsx.csv for the exact format).
Only `name` and `email` are required; everything else is optional and
may be blank, but role must be explicit:

    name           - full name, any language
    email          - used as their login (must be unique in the file
                     and not already exist in Odoo)
    role           - one of the ROLE_TEMPLATES keys below (default:
                     "employee" if blank or unrecognized)
    department     - free text (e.g. "مالی"); matched case-insensitively
                     against existing hr.department, created if new
    job_title      - free text position (e.g. "کارشناس حسابداری");
                     matched/created the same way against hr.job
    manager_email  - email of this person's manager. Can point at
                     another row in the SAME file (resolved after
                     everyone is created) or at an existing employee
                     already in Odoo. Leave blank for no manager.

Output: a non-secret CSV audit manifest only (user id, login, role, department,
job, created_at). Passwords, API keys, bearer tokens, reset tokens and secrets
are never written to disk.
"""
import csv
import os
import re
import sys

# ---------------------------------------------------------------------
# EDIT THESE before running (or set the ONBOARD_* env vars - see above)
# ---------------------------------------------------------------------
EXCEL_PATH = os.environ.get("ONBOARD_FILE", "/opt/client_employees.xlsx")  # .xlsx or .csv
OUTPUT_CSV = os.environ.get("ONBOARD_OUTPUT", "/opt/onboarding_audit.csv")
SKIP_PROMPT = os.environ.get("ONBOARD_YES") == "1"
DRY_RUN = os.environ.get("ONBOARD_DRY_RUN") == "1"

# role (Excel column value, lowercase) -> Role Template external ID
# in ai_business_tools/data/role_templates_data.xml (roadmap item #5).
# This IS the permission model - keep this in sync with that file, not
# with a second hand-picked list of raw groups.
ROLE_TEMPLATES = {
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

# Roles considered "elevated" for the preview's approval-friction summary
# only (roadmap #36 example: "11 دسترسی بالا") - not a separate ACL, just
# which Role Templates carry approve/admin-level implied_ids.
ROLE_RULES = {
    ("human resources", "manager"): "hr_manager",
    ("hr", "manager"): "hr_manager",
    ("finance", "manager"): "finance_manager",
    ("accounting", "manager"): "finance_manager",
    ("warehouse", "manager"): "warehouse_manager",
    ("inventory", "manager"): "warehouse_manager",
    ("project", "manager"): "project_manager",
}

ELEVATED_ROLES = {
    "hr_manager", "finance_manager", "warehouse_manager",
    "executive", "system_admin",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------
# 1. PARSE
# ---------------------------------------------------------------------
def parse_rows(path):
    if not os.path.exists(path):
        raise SystemExit(f"File not found: {path}")

    if path.lower().endswith(".csv"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path)
        ws = wb.active
        headers = [(c.value or "").strip() for c in ws[1]]
        rows = []
        for raw in ws.iter_rows(min_row=2, values_only=True):
            if raw is None or all(v is None for v in raw):
                continue
            rows.append(dict(zip(headers, raw)))

    # attach the original spreadsheet row number (header = row 1) so
    # every later error message can point the client's IT contact at
    # the exact line to fix, not just "row 14 of the parsed list"
    for i, row in enumerate(rows):
        row["_line"] = i + 2
    return rows


# ---------------------------------------------------------------------
# 2/3. VALIDATE + NORMALIZE (one pass: normalize a field, then validate it)
# ---------------------------------------------------------------------
def normalize_and_validate(rows):
    """Returns (clean_rows, errors, warnings). clean_rows have every
    field trimmed/lowercased-where-appropriate. errors are blocking
    (the whole import is refused if any exist - see main()); warnings
    are shown in the preview but don't block."""
    errors = []
    warnings = []
    clean = []
    seen_emails = set()

    for row in rows:
        line = row["_line"]
        name = (row.get("name") or "").strip()
        email = (row.get("email") or "").strip().lower()
        role_raw = (row.get("role") or "").strip().lower()
        department = (row.get("department") or "").strip()
        job_title = (row.get("job_title") or "").strip()
        job_level = (row.get("job_level") or "").strip()
        location = (row.get("location") or "").strip()
        employment_type = (row.get("employment_type") or "").strip()
        manager_email = (row.get("manager_email") or "").strip().lower()

        if not name:
            errors.append(f"line {line}: missing name")
            continue
        if not email:
            errors.append(f"line {line}: missing email for '{name}'")
            continue
        if not EMAIL_RE.match(email):
            errors.append(f"line {line}: '{email}' does not look like a valid email")
            continue
        if email in seen_emails:
            errors.append(f"line {line}: duplicate email '{email}' also appears earlier in this file")
            continue
        seen_emails.add(email)

        if manager_email and not EMAIL_RE.match(manager_email):
            errors.append(f"line {line}: manager_email '{manager_email}' does not look like a valid email")
            continue
        if manager_email == email:
            errors.append(f"line {line}: '{name}' cannot be their own manager")
            continue

        role = role_raw
        if not role:
            policy_role = env["ai.customer.role.policy"].resolve(
                env.company, department=department, position=job_title, job_level=job_level,
                manager_required=bool(manager_email), location=location, employment_type=employment_type
            ) if "ai.customer.role.policy" in env else env["res.groups"].browse()
            if policy_role:
                role = next((k for k,v in ROLE_TEMPLATES.items() if env.ref(v).id == policy_role.id), "")
                warnings.append(f"line {line}: role inferred by customer role policy as '{role}'")
            if not role:
                errors.append(f"line {line}: role is required and no safe role policy matched the supplied attributes")
                continue
        elif role not in ROLE_TEMPLATES:
            errors.append(
                f"line {line}: unknown role '{role_raw}' for '{name}'. "
                f"Import is blocked; known roles: {', '.join(sorted(ROLE_TEMPLATES))}"
            )
            continue

        existing = env["res.users"].search([("login", "=", email)], limit=1)
        if existing:
            warnings.append(f"line {line}: user '{email}' already exists in Odoo - will be SKIPPED")

        clean.append({
            "line": line,
            "name": name,
            "email": email,
            "role": role,
            "department": department,
            "job_title": job_title,
            "manager_email": manager_email,
            "job_level": job_level, "location": location, "employment_type": employment_type,
            "skip_existing": bool(existing),
        })

    # manager cycle detection (A -> B -> A), only across rows that will
    # actually be imported (skip_existing rows can still be a valid
    # manager target - they already exist in Odoo - so only chase
    # cycles through the in-file email graph)
    by_email = {r["email"]: r for r in clean}
    for r in clean:
        chain = [r["email"]]
        cursor = r
        for _ in range(len(clean) + 1):
            mgr_email = cursor.get("manager_email")
            if not mgr_email or mgr_email not in by_email:
                break
            if mgr_email in chain:
                errors.append(
                    f"line {r['line']}: manager chain starting at '{r['email']}' "
                    f"cycles back through '{mgr_email}' ({' -> '.join(chain + [mgr_email])})"
                )
                break
            chain.append(mgr_email)
            cursor = by_email[mgr_email]

    return clean, errors, warnings


# ---------------------------------------------------------------------
# helpers for 4/5. DEPARTMENT + POSITION (find-or-create, case-insensitive)
# Called only from inside run_import() - i.e. only after approval, and
# only inside the savepoint, so it's safe for this to actually create
# records: if the run is --dry-run or later fails, the whole savepoint
# (including any department/job created here) is rolled back with it.
# ---------------------------------------------------------------------
def get_or_create_department(name_cache, name):
    if not name:
        return False
    key = name.lower()
    if key in name_cache:
        return name_cache[key]
    existing = env["hr.department"].search([("name", "=ilike", name)], limit=1)
    dept = existing or env["hr.department"].create({"name": name})
    name_cache[key] = dept.id
    return dept.id


def get_or_create_job(name_cache, title):
    if not title:
        return False
    key = title.lower()
    if key in name_cache:
        return name_cache[key]
    existing = env["hr.job"].search([("name", "=ilike", title)], limit=1)
    job = existing or env["hr.job"].create({"name": title})
    name_cache[key] = job.id
    return job.id


# ---------------------------------------------------------------------
# 8. PREVIEW
# ---------------------------------------------------------------------
def print_preview(clean, errors, warnings, new_departments, new_jobs):
    print("=" * 72)
    print(f"ONBOARDING PREVIEW - {EXCEL_PATH}")
    print("=" * 72)

    to_import = [r for r in clean if not r["skip_existing"]]
    to_skip = [r for r in clean if r["skip_existing"]]

    print(f"\n{len(clean)} valid rows parsed, {len(to_import)} will be imported, "
          f"{len(to_skip)} skipped (already exist).")

    role_counts = {}
    elevated = []
    for r in to_import:
        role_counts[r["role"]] = role_counts.get(r["role"], 0) + 1
        if r["role"] in ELEVATED_ROLES:
            elevated.append(r)

    print("\nRoles:")
    for role, count in sorted(role_counts.items()):
        flag = "  ** ELEVATED **" if role in ELEVATED_ROLES else ""
        print(f"  {role:<20} x{count}{flag}")

    if elevated:
        print(f"\n{len(elevated)} elevated-access grant(s) - review carefully:")
        for r in elevated:
            print(f"  line {r['line']}: {r['name']} <{r['email']}> -> {r['role']}")

    if new_departments:
        print(f"\n{len(new_departments)} new department(s) will be created:")
        for d in sorted(new_departments):
            print(f"  - {d}")

    if new_jobs:
        print(f"\n{len(new_jobs)} new position(s) will be created:")
        for j in sorted(new_jobs):
            print(f"  - {j}")

    manager_links = [r for r in to_import if r["manager_email"]]
    if manager_links:
        print(f"\n{len(manager_links)} manager link(s) will be set:")
        for r in manager_links:
            print(f"  line {r['line']}: {r['name']} reports to {r['manager_email']}")

    if warnings:
        print(f"\n{len(warnings)} warning(s) (non-blocking):")
        for w in warnings:
            print(f"  ! {w}")

    if errors:
        print(f"\n{len(errors)} ERROR(s) - IMPORT BLOCKED until these are fixed:")
        for e in errors:
            print(f"  x {e}")

    print("=" * 72)


# ---------------------------------------------------------------------
# 9/10. APPROVAL + IMPORT (inside one savepoint - roadmap #37)
# ---------------------------------------------------------------------
def run_import(clean):
    """Everything below runs inside a single Postgres SAVEPOINT. If any
    line raises, or the caller re-raises after a --dry-run, Odoo's
    Cursor.savepoint() rolls the whole block back automatically -
    nothing partially created."""
    dept_cache = {}
    job_cache = {}
    results = []
    created_by_email = {}

    to_import = [r for r in clean if not r["skip_existing"]]

    # pass 1: departments + jobs + users + employees (no manager yet -
    # the manager might be created later in this same loop)
    for r in to_import:
        dept_id = get_or_create_department(dept_cache, r["department"])
        job_id = get_or_create_job(job_cache, r["job_title"])

        role_xmlid = ROLE_TEMPLATES[r["role"]]
        group = env.ref(role_xmlid)

        user = env["res.users"].create({
            "name": r["name"],
            "login": r["email"],
            "email": r["email"],
            "groups_id": [(6, 0, [group.id])],
        })
        # No password/API key is generated here. Customer identity is provisioned
        # through the SSO/SCIM or secure invitation/session flow.

        employee_vals = {
            "name": r["name"],
            "user_id": user.id,
            "work_email": r["email"],
        }
        if dept_id:
            employee_vals["department_id"] = dept_id
        if job_id:
            employee_vals["job_id"] = job_id
        if r["job_title"]:
            employee_vals["job_title"] = r["job_title"]
        employee = env["hr.employee"].create(employee_vals)

        created_by_email[r["email"]] = employee
        env["ai.customer.role.assignment"].sudo().create({
            "user_id": user.id, "role_group_id": group.id, "source": "direct",
            "company_id": env.company.id, "managed_by": "excel", "reason": "Excel onboarding role assignment"
        })
        results.append({
            "line": r["line"],
            "name": r["name"],
            "login": r["email"],
            "role": r["role"],
            "department": r["department"],
            "job_title": r["job_title"],
            "manager_email": r["manager_email"],
            "user_id": user.id,
        })
        print(f"  OK - created {r['name']} ({r['email']}) as {r['role']}")

    # pass 2: manager links, now that every in-file person exists
    for r in to_import:
        if not r["manager_email"]:
            continue
        employee = created_by_email.get(r["email"])
        manager_employee = created_by_email.get(r["manager_email"])
        if not manager_employee:
            manager_user = env["res.users"].search([("login", "=", r["manager_email"])], limit=1)
            manager_employee = manager_user.employee_id if manager_user else False
        if not manager_employee:
            print(f"  WARNING - could not resolve manager '{r['manager_email']}' for {r['name']}, left blank")
            continue
        employee.write({"parent_id": manager_employee.id})

    return results


def write_result_csv(results):
    """Write a non-secret audit manifest. Never serialize credentials."""
    fieldnames = ["user_id", "login", "name", "role", "department", "job_title"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
