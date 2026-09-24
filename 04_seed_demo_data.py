"""
Rich demo data seed - run with:
  /opt/odoo/odoo-bin shell -c /opt/odoo.conf -d company_ai < 04_seed_demo_data.py

⚠️ FOR YOUR OWN SALES DEMO ONLY - never run this against a real
customer's database. This creates fake departments, employees, leave
requests, tasks, documents, and approvals so that logging in as any
demo user immediately shows a populated, working product instead of
an empty shell - useful for showing the product to a prospect, or for
your own testing.

Idempotent: safe to run more than once - it checks for an existing
"[DEMO]" marker department before creating anything, and does nothing
if that marker is already there.
"""
import random
from datetime import date, timedelta

MARKER_DEPT_NAME = "[DEMO] Executive"

existing = env["hr.department"].search([("name", "=", MARKER_DEPT_NAME)], limit=1)
if existing:
    print(f"Demo data already seeded (found '{MARKER_DEPT_NAME}'). Nothing to do - "
          f"delete departments named '[DEMO] ...' first if you want to reseed.")
else:
    print("=== Seeding rich demo data ===")

    # -----------------------------------------------------------------
    # 1. Departments
    # -----------------------------------------------------------------
    dept_names = ["[DEMO] Executive", "[DEMO] HR", "[DEMO] Finance",
                  "[DEMO] Warehouse", "[DEMO] Engineering", "[DEMO] Sales"]
    departments = {}
    for name in dept_names:
        departments[name] = env["hr.department"].create({"name": name})
    print(f"Created {len(departments)} departments.")

    # -----------------------------------------------------------------
    # 2. Role groups (already installed by ai_business_tools)
    # -----------------------------------------------------------------
    def role(xmlid):
        return env.ref(f"ai_business_tools.{xmlid}")

    # -----------------------------------------------------------------
    # 3. Employees + users, spread across departments and roles.
    #    (login, full name, department key, role xmlid, job title)
    # -----------------------------------------------------------------
    PEOPLE = [
        ("demo.ceo@yourbrand.example", "سارا احمدی", "[DEMO] Executive", "role_executive", "مدیرعامل"),
        ("demo.hr.manager@yourbrand.example", "مریم رضایی", "[DEMO] HR", "role_hr_manager", "مدیر منابع انسانی"),
        ("demo.hr.staff@yourbrand.example", "نگار کریمی", "[DEMO] HR", "role_hr_staff", "کارشناس منابع انسانی"),
        ("demo.finance.manager@yourbrand.example", "علی محمدی", "[DEMO] Finance", "role_finance_manager", "مدیر مالی"),
        ("demo.finance.staff@yourbrand.example", "زهرا حسینی", "[DEMO] Finance", "role_finance_staff", "کارشناس مالی"),
        ("demo.warehouse.manager@yourbrand.example", "رضا قاسمی", "[DEMO] Warehouse", "role_warehouse_manager", "مدیر انبار"),
        ("demo.warehouse.staff@yourbrand.example", "حسین نوری", "[DEMO] Warehouse", "role_warehouse_staff", "انباردار"),
        ("demo.pm@yourbrand.example", "فاطمه صادقی", "[DEMO] Engineering", "role_project_manager", "مدیر پروژه"),
        ("demo.eng1@yourbrand.example", "امیر جعفری", "[DEMO] Engineering", "role_employee", "توسعه‌دهنده ارشد"),
        ("demo.eng2@yourbrand.example", "لیلا موسوی", "[DEMO] Engineering", "role_employee", "توسعه‌دهنده"),
        ("demo.designer@yourbrand.example", "پریسا اکبری", "[DEMO] Engineering", "role_employee", "کارشناس طراح گرافیک"),
        ("demo.sales1@yourbrand.example", "کاوه رستمی", "[DEMO] Sales", "role_employee", "کارشناس فروش"),
        ("demo.sales2@yourbrand.example", "شیوا امیری", "[DEMO] Sales", "role_manager", "مدیر فروش"),
        ("demo.security@yourbrand.example", "بهروز طاهری", "[DEMO] Executive", "role_security", "مسئول امنیت"),
    ]

    Users = env["res.users"].with_context(no_reset_password=True)
    created_users = {}
    for login, name, dept_key, role_xmlid, job_title in PEOPLE:
        user = Users.create({
            "name": name, "login": login, "email": login,
            "groups_id": [(4, role(role_xmlid).id)],
        })
        employee = env["hr.employee"].create({
            "name": name, "user_id": user.id,
            "department_id": departments[dept_key].id,
            "job_title": job_title,
        })
        env["ai.gateway.api.key"].create_key(user)
        created_users[login] = (user, employee)
    print(f"Created {len(created_users)} employees with users, Role Templates, and API keys.")

    # Wire up managers (roadmap #2/#41 need a real parent_id for some scenarios)
    ceo_emp = created_users["demo.ceo@yourbrand.example"][1]
    hr_mgr_emp = created_users["demo.hr.manager@yourbrand.example"][1]
    fin_mgr_emp = created_users["demo.finance.manager@yourbrand.example"][1]
    wh_mgr_emp = created_users["demo.warehouse.manager@yourbrand.example"][1]
    pm_emp = created_users["demo.pm@yourbrand.example"][1]
    sales_mgr_emp = created_users["demo.sales2@yourbrand.example"][1]

    created_users["demo.hr.staff@yourbrand.example"][1].parent_id = hr_mgr_emp.id
    created_users["demo.finance.staff@yourbrand.example"][1].parent_id = fin_mgr_emp.id
    created_users["demo.warehouse.staff@yourbrand.example"][1].parent_id = wh_mgr_emp.id
    created_users["demo.eng1@yourbrand.example"][1].parent_id = pm_emp.id
    created_users["demo.eng2@yourbrand.example"][1].parent_id = pm_emp.id
    created_users["demo.designer@yourbrand.example"][1].parent_id = pm_emp.id
    created_users["demo.sales1@yourbrand.example"][1].parent_id = sales_mgr_emp.id
    for dept in departments.values():
        pass  # departments left without manager_id - not needed for any current tool

    # -----------------------------------------------------------------
    # 4. Leave requests - mix of states, so approve_leave/reject_leave
    #    and the pending-approvals list have something real to show.
    # -----------------------------------------------------------------
    leave_type = env["hr.leave.type"].search([("requires_allocation", "=", "no")], limit=1) \
        or env["hr.leave.type"].search([], limit=1)
    today = date.today()
    leave_count = 0
    if leave_type:
        for login, (user, employee) in created_users.items():
            if random.random() < 0.6:  # not everyone has a request, more realistic
                start = today + timedelta(days=random.randint(-20, 20))
                leave = env["hr.leave"].with_user(user.id).create({
                    "employee_id": employee.id,
                    "holiday_status_id": leave_type.id,
                    "request_date_from": start,
                    "request_date_to": start + timedelta(days=random.randint(1, 4)),
                    "name": random.choice(["مرخصی استحقاقی", "مرخصی شخصی", "سفر خانوادگی"]),
                })
                if hasattr(leave, "action_confirm"):
                    leave.sudo().action_confirm()
                leave_count += 1
        # Approve a few of them for realism (some stay pending on purpose)
        from odoo.exceptions import ValidationError as _VE

        pending = env["hr.leave"].search([("state", "in", ("confirm", "validate1"))], limit=4)
        for l in pending:
            try:
                l.sudo().action_approve()
            except _VE as e:
                # hr_holidays refuses leaves overlapping non-working days for
                # some calendars; leave those pending - fine for the demo.
                print(f"  (leave #{l.id} stays pending: {str(e)[:80]}...)")
    print(f"Created {leave_count} leave requests (some approved, some left pending for the demo).")

    # -----------------------------------------------------------------
    # 5. Tasks - a mix of on-time and OVERDUE, so
    #    list_overdue_tasks/cron_notify_overdue_tasks has something real
    # -----------------------------------------------------------------
    project = env["project.project"].search([("name", "=", "AI Tasks")], limit=1) \
        or env["project.project"].create({"name": "AI Tasks"})
    task_titles = [
        "بازبینی گزارش مالی سه‌ماهه", "طراحی رابط کاربری داشبورد جدید",
        "بررسی موجودی انبار", "آماده‌سازی ارائه برای مشتری",
        "رفع باگ در ماژول مرخصی", "برنامه‌ریزی جلسه‌ی هفتگی تیم",
        "بررسی درخواست‌های خرید", "به‌روزرسانی مستندات فنی",
    ]
    task_count = 0
    for i, title in enumerate(task_titles):
        assignee_login = random.choice(list(created_users.keys()))
        assignee_user = created_users[assignee_login][0]
        deadline = today + timedelta(days=random.randint(-10, 15))  # some deliberately overdue
        env["project.task"].create({
            "name": title, "project_id": project.id,
            "user_ids": [(6, 0, [assignee_user.id])],
            "date_deadline": deadline,
        })
        task_count += 1
    print(f"Created {task_count} tasks (some overdue on purpose).")

    # -----------------------------------------------------------------
    # 6. Documents - one at every access level
    # -----------------------------------------------------------------
    hr_group = role("role_hr_manager")
    env["company.document"].create({
        "name": "سیاست‌نامه‌ی سازمانی", "access_level": "company",
        "description": "قابل مشاهده برای همه‌ی کارکنان.",
    })
    env["company.document"].create({
        "name": "بودجه‌ی داخلی بخش مالی", "access_level": "department",
        "department_id": departments["[DEMO] Finance"].id,
        "description": "فقط بخش مالی.",
    })
    env["company.document"].create({
        "name": "دستورالعمل تایید مرخصی (محرمانه)", "access_level": "group",
        "group_id": hr_group.id,
        "description": "فقط گروه HR Manager.",
    })
    env["company.document"].create({
        "name": "یادداشت شخصی مدیرعامل", "access_level": "personal",
        "owner_id": ceo_emp.user_id.id,
        "description": "فقط خود مدیرعامل.",
    })
    print("Created 4 documents (one per access level).")

    # -----------------------------------------------------------------
    # 7. One pending HR decree approval + one active temporary grant,
    #    so the Admin Console isn't empty either.
    # -----------------------------------------------------------------
    ceo_env = env(user=ceo_emp.user_id.id)

    def _expect_approval(fn, **kw):
        """These tools raise UserError('approval_required: ...') BY DESIGN when
        the execution gate needs a human decision - the approval row is real.
        Catch it so the seed keeps going."""
        from odoo.exceptions import UserError as _UE

        try:
            return fn(**kw)
        except _UE as e:
            print(f"  (approval pending by design: {e})")
            return {"status": "approval_required"}

    decree_res = _expect_approval(
        ceo_env["llm.tool"].generate_hr_decree,
        employee_name=created_users["demo.eng1@yourbrand.example"][1].name,
        decree_type="raise", decree_text="افزایش حقوق سالانه بر اساس عملکرد.",
    )
    grant_res = _expect_approval(
        ceo_env["llm.tool"].grant_temporary_access,
        user_name=created_users["demo.hr.staff@yourbrand.example"][1].name,
        role_name="HR Manager",
        expires_on=str(today + timedelta(days=14)),
        reason="پوشش دوران مرخصی مدیر HR",
    )
    print(f"Pending HR decree approval: {decree_res.get('status')}")
    print(f"Temporary access grant: {grant_res.get('status')}")

    # -----------------------------------------------------------------
    # 8. The bootstrap admin owns the system-admin role, so the Admin
    #    Console (admin.console.read) is visible and reachable on a real
    #    appliance, not only in the static demo.
    # -----------------------------------------------------------------
    # 7b. The demo identity the product UI ships with (prefilled on the
    #     login screen): Sara Mohammadi <sara@example.com> / demo.
    sara = env["res.users"].with_context(no_reset_password=True).search(
        [("login", "=", "sara@example.com")], limit=1)
    if not sara:
        sara = env["res.users"].with_context(no_reset_password=True).create({
            "name": "Sara Mohammadi", "login": "sara@example.com",
            "email": "sara@example.com", "password": "demo",
        })
    sara.password = "demo"
    for _xml in ("ai_business_tools.role_executive",
                 "ai_business_tools.role_sales_manager"):
        try:
            _g = env.ref(_xml)
            if _g.id not in sara.groups_id.ids:
                sara.groups_id = [(4, _g.id)]
        except Exception:
            pass
    if not env["hr.employee"].search([("user_id", "=", sara.id)], limit=1):
        _dept = env["hr.department"].search([("name", "ilike", "Sales")], limit=1)
        env["hr.employee"].create({"name": "Sara Mohammadi", "user_id": sara.id,
                                   "department_id": _dept.id if _dept else False})
    if "ai.gateway.api.key" in env:
        env["ai.gateway.api.key"].sudo().create_key_by_id(sara.id)
    # A few real tasks for Sara so her dashboard isn't empty on a fresh box.
    _proj = env["project.project"].search([("name", "=", "AI Tasks")], limit=1)
    if _proj:
        for _t in ("Prepare quote for Aria Industries",
                   "Review the 2026 leave policy draft",
                   "Board demo preparation"):
            if not env["project.task"].search_count(
                    [("project_id", "=", _proj.id), ("name", "=", _t)]):
                env["project.task"].create({
                    "name": _t, "project_id": _proj.id,
                    "user_ids": [(6, 0, [sara.id])],
                    "description": "Seeded demo task.",
                })
    print("Demo identity ready: sara@example.com / demo")

    admin_user = env["res.users"].search([("login", "=", "admin")], limit=1)
    if admin_user:
        # Fresh installs can leave the bootstrap admin group-less depending on
        # install order, which locks them out of the console AND of basic
        # internal-user ACLs (chat included). Grant explicitly and idempotently.
        for xmlid in ("base.group_user", "base.group_system",
                      "ai_business_tools.role_system_admin",
                      "ai_business_tools.role_executive"):
            group = env.ref(xmlid, raise_if_not_found=False)
            if group and group not in admin_user.groups_id:
                admin_user.groups_id = [(4, group.id)]
                print("Granted %s to admin." % xmlid)

    env.cr.commit()
    print("\n=== Demo data seeded and committed. ===")
    print("Log in as any of these (password reset needed on first login, "
          "or set one directly if this is a local demo box):")
    for login, _, _, role_xmlid, title in PEOPLE:
        print(f"  {login}  -  {title}  ({role_xmlid})")
