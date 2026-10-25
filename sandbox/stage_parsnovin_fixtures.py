# ===========================================================================
# PARSNOVIN SCENARIO STAGING (idempotent) — run INSIDE odoo shell:
#   AIBOX_WS=... python odoo-bin shell -c conf/odoo.conf -d aibox --no-http \
#     < sandbox/stage_parsnovin_fixtures.py
#
# Builds the fictional customer company «پارس‌نوین صنایع هوشمند» the test
# suites rely on: company + departments + 4 real users (ali/sara/kian/
# maryam) + 4 company documents with DIFFERENT access levels (company /
# department / restricted-allowed=[maryam]) + open hr contracts + pending
# leaves (ali is the leave manager) + a REAL posted customer invoice with
# a confidential amount. Safe to re-run: every step searches before it
# creates, so ids may differ between runs (the suites resolve by NAME,
# never by hardcoded id).
# ===========================================================================
env.invalidate_all()
ResU, ResP = env["res.users"].sudo(), env["res.partner"].sudo()
Comp, Dep, Emp = env["res.company"].sudo(), env["hr.department"].sudo(), env["hr.employee"].sudo()
Doc, Leave = env["company.document"].sudo(), env["hr.leave"].sudo()

PW = "Pars2026Nova"
IRR = env.ref("base.IRR", raise_if_not_found=False) or env["res.currency"].sudo().search([("name", "=", "IRR")], limit=1)

# ---- 1) company -----------------------------------------------------------
comp = Comp.search([("name", "like", "پارس‌نوین")], limit=1)
if not comp:
    comp = Comp.create({"name": "پارس‌نوین صنایع هوشمند", "currency_id": IRR.id})
    print("COMPANY-CREATED", comp.id)
print("COMPANY", comp.id)

# ---- 2) departments (هیئت مدیره is the root, others report to it) ---------
def dept(name, parent=None):
    d = Dep.search([("name", "=", name), ("company_id", "=", comp.id)], limit=1)
    return d or Dep.create({"name": name, "company_id": comp.id, "parent_id": parent and parent.id})

d_board = dept("هیئت مدیره")
d_sales = dept("فروش", d_board)
d_it    = dept("فناوری اطلاعات", d_board)
d_fin   = dept("مالی و اداری", d_board)
print("DEPTS", d_board.id, d_sales.id, d_fin.id)

# ---- 3) the four users ----------------------------------------------------
def user(login, name, dept_, groups_xmlids=()):
    u = ResU.search([("login", "=", login)], limit=1)
    if not u:
        p = ResP.create({"name": name})
        u = ResU.create({"login": login, "partner_id": p.id, "name": name,
                         "password": PW, "active": True, "groups_id": [(6, 0, [])]})
    if not u.active:
        u.active = True
    # mail.message_post on llm.thread refuses to run when the author has
    # no email ("Unable to send message, please configure the sender's
    # email address") - the login IS the email here
    if not (u.email or "").strip() or "@" not in (u.email or ""):
        u.write({"email": login})
    # membership in the fictional company is REQUIRED: record rules gate
    # accounting/HR records by res.users.company_ids, and a user stuck in
    # the default company gets "unauthorized or invalid companies"
    if comp.id not in u.company_ids.ids or u.company_id.id != comp.id:
        u.write({"company_id": comp.id, "company_ids": [(6, 0, [comp.id])]})
    gids = [env.ref(x).id for x in groups_xmlids if env.ref(x, raise_if_not_found=False)]
    for g in gids:
        if g not in u.groups_id.ids:
            u.write({"groups_id": [(4, g)]})
    emp = Emp.search([("user_id", "=", u.id)], limit=1)
    if not emp:
        emp = Emp.create({"name": name, "user_id": u.id, "company_id": comp.id,
                          "department_id": dept_.id})
    else:
        emp.write({"department_id": dept_.id, "company_id": comp.id, "active": True})
    return u

ali    = user("ali@parsnovin.test",    "علی کریمی",   d_board,
              ["ai_business_tools.role_employee", "ai_business_tools.role_ceo"])
sara   = user("sara@parsnovin.test",   "سارا محمدی",  d_sales,
              ["ai_business_tools.role_employee", "ai_business_tools.role_sales_staff"])
kian   = user("kian@parsnovin.test",   "کیان رضایی",  d_sales,
              ["ai_business_tools.role_employee", "ai_business_tools.role_sales_staff"])
maryam = user("maryam@parsnovin.test", "مریم احمدی",  d_fin,
              ["ai_business_tools.role_employee", "ai_business_tools.role_finance_manager"])
env.cr.flush()
# role_reconciler runs on writes - re-verify the finance role survived
# (get_external_id is per-record: build the id->xmlid map once, then look up)
ROLE_MAP = maryam.groups_id.get_external_id()  # {id: xmlid}
print("ROLES maryam-finance:", any((x or "").endswith("role_finance_manager")
                                   for x in ROLE_MAP.values()))

# ali is the leave approver of the sales pair (suite: manager sees the team)
for u in (sara, kian):
    if u.leave_manager_id.id != ali.id:
        u.write({"leave_manager_id": ali.id})
env.cr.commit()

# ---- 4) documents (markers the suites grep for) ---------------------------
FIN_NAME, SAL_NAME = "صورت‌های مالی محرمانه 2026", "جدول حقوق‌های محرمانه"
def doc(name, access, description, **kw):
    d = Doc.search([("name", "=", name)], limit=1)
    vals = {"name": name, "description": description, "access_level": access,
            "classification": kw.pop("classification", "internal"), **kw}
    if d:
        d.write(vals)
        return d
    return Doc.create(vals)

doc("آیین‌نامه فروش پارس‌نوین", "company",
    "مأموریت رسمی: رشد فروش با حفظ حاشیه سود 18 درصد. اسکریپت تماس اول: معرفی ۲ دقیقه‌ای، "
    "کشف نیاز، دمو کوتاه. تخفیف مجاز حداکثر ۵ درصد برای فروشندگان ارشد.")
doc("راهنمای تیم فروش", "department",
    "راهنمای داخلی تیم فروش: ساعات تماس، قالب پیشنهاد قیمت، پیگیری ۳ مرحله‌ای. "
    "فقط برای دپارتمان فروش.", department_id=d_sales.id)
doc(FIN_NAME, "restricted",
    "صورت‌های مالی ۲۰۲۶ - کاملاً محرمانه. سود خالص: 4.2 میلیارد تومان. "
    "بدهی بانکی جاری: 12 میلیارد تومان. تنها مدیر مالی اجازه دسترسی دارد.",
    classification="restricted", allowed_user_ids=[(6, 0, [maryam.id])])
doc(SAL_NAME, "restricted",
    "جدول حقوق‌های محرمانه: حقوق سارا محمدی 25,000,000 تومان - حقوق کیان رضایی "
    "60,000,000 تومان (۶۰ میلیون). توزیع خارج از مالی ممنوع.",
    classification="pii", allowed_user_ids=[(6, 0, [maryam.id])])
env.cr.commit()
print("DOCS", Doc.search_count([]))

# ---- 5) open hr contracts -------------------------------------------------
Con = env["hr.contract"].sudo()
def contract(emp, wage):
    c = Con.search([("employee_id", "=", emp.id), ("state", "=", "open")], limit=1)
    if c:
        c.write({"wage": wage})
        return c
    return Con.create({"name": "قرارداد " + emp.name, "employee_id": emp.id,
                       "wage": wage, "state": "open", "company_id": comp.id,
                       "date_start": "2026-01-01"})
contract(Emp.search([("user_id", "=", sara.id)], limit=1), 25000000)
contract(Emp.search([("user_id", "=", kian.id)], limit=1), 60000000)
env.cr.commit()
print("CONTRACTS", Con.search_count([("state", "=", "open")]))

# ---- 6) pending leaves (3x sara + 1x kian, ali approves) -----------------
# prefer a type that does NOT need an allocation balance first
lt = env["hr.leave.type"].sudo().search([("requires_allocation", "=", "no")], limit=1) \
     or env["hr.leave.type"].sudo().search([], limit=1)
if lt:
    made = 0
    for n, (uu, days) in enumerate([(sara, 2), (sara, 1), (sara, 3), (kian, 2)]):
        key = "درخواست آزمایشی %d" % (n + 1)
        if Leave.search_count([("name", "=", key)]):
            made += 1
            continue
        d0 = "2026-11-%02d" % (3 + n * 5)
        try:
            Leave.create({"user_id": uu.id,
                          "employee_id": Emp.search([("user_id", "=", uu.id)], limit=1).id,
                          "holiday_status_id": lt.id, "state": "confirm",
                          "request_date_from": d0, "request_date_to": d0,
                          "date_from": d0 + " 08:00:00",
                          "date_to": d0 + " 17:00:00",
                          "number_of_days": days, "name": key})
            made += 1
        except Exception as exc:  # noqa: BLE001
            print("LEAVE-SKIP", key, str(exc)[:70])
    env.cr.commit()
    print("LEAVES", made)

# ---- 7) REAL posted customer invoice (confidential financial record) ------
Con2, Move = env["account.journal"].sudo(), env["account.move"].sudo()
REF = "INV-PARS-1404-0917"
mv = Move.search([("payment_reference", "=", REF)], limit=1)
if not mv:
    journal = Con2.search([("type", "=", "sale"), ("company_id", "=", comp.id)], limit=1) \
        or Con2.create({"name": "فروش پارس‌نوین", "code": "FRJP", "type": "sale", "company_id": comp.id})
    partner = ResP.search([("name", "=", "آریا صنعت پایه")], limit=1) \
        or ResP.create({"name": "آریا صنعت پایه", "is_company": True})
    Acc = env["account.account"].sudo()
    def acc_of(kind, name, code):
        a = Acc.search([("account_type", "=", kind), ("company_ids", "in", comp.id)], limit=1)
        if not a:
            # never mutate shared/other-company accounts: create a fresh one
            # scoped to THIS company (unique code suffix avoids collisions)
            a = Acc.create({"name": name, "code": "%s%02d" % (code, comp.id % 100),
                            "account_type": kind, "company_ids": [(6, 0, [comp.id])]})
        return a
    inc = acc_of("income", "درآمد خدمات پارس‌نوین", "40000")
    rec = acc_of("asset_receivable", "دریافتنی تجاری", "11000")
    partner.write({"property_account_receivable_id": rec.id})
    mv = Move.with_company(comp).create({
        "move_type": "out_invoice", "journal_id": journal.id, "partner_id": partner.id,
        "invoice_date": "2026-10-25", "payment_reference": REF, "ref": REF,
        "invoice_line_ids": [(0, 0, {"name": "پروژه استقرار هوش مصنوعی - فاز ۱",
                                     "quantity": 1, "price_unit": 12750000000.0,
                                     "account_id": inc.id, "tax_ids": [(6, 0, [])]})]})
    try:
        mv.action_post()
    except Exception as exc:
        env.cr.rollback()
        mv = Move.search([("payment_reference", "=", REF)], limit=1)
        print("INVOICE-DRAFT", mv.state, str(exc)[:60])
env.cr.commit()
print("INVOICE", mv.id, mv.state, mv.amount_total)
print("SANITY maryam-sees-move:", bool(mv.with_user(maryam).search([("id", "=", mv.id)], limit=1)))
try:
    sees = bool(mv.with_user(sara).search([("id", "=", mv.id)], limit=1))
except Exception:  # noqa: BLE001 - AccessError IS the expected denial shape
    sees = False
print("SANITY sara-sees-move:", sees, "(denied)")

# ---- 8) RAG reindex so semantic search knows the docs --------------------
env["company.document"].search([]).action_reindex()
env.cr.commit()
print("CHUNKS", env["ai.document.chunk"].sudo().search_count([]))

print("FIN-OK docs=%s" % Doc.search_count([]))
