#!/usr/bin/env python3
"""Deep data-consistency audit for the appliance (ALL installed modules).

Run inside odoo shell:   odoo-bin shell -c conf -d aibox < this file
Every check prints a CHK* marker; the last line is AUDIT-DONE."""
import ast
import time

t0 = time.time()
def P(*a):
    print(*a, flush=True)

Inst = env["ir.module.module"].sudo()
installed = set(Inst.search([("state", "=", "installed")]).mapped("name"))
P("CHK0 installed modules:", len(installed))

pending = Inst.search([("state", "in", ["to install", "to upgrade", "to remove"])])
P("CHK1 pending module states:", len(pending), pending.mapped("name")[:5])

bad_models = []
models = env["ir.model"].sudo().search_read([], ["model", "state"])
for rec in models:
    if rec["state"] == "manual":
        try:
            env[rec["model"]].sudo().search_count([], limit=1)
        except Exception as e:
            bad_models.append((rec["model"], str(e)[:80]))
P("CHK2 queryable registry models:", len(models), "| broken:", len(bad_models), bad_models[:6])

bad_rel = []
for f in env["ir.model.fields"].sudo().search_read(
        [("ttype", "in", ["many2one", "one2many", "many2many"])],
        ["model", "name", "relation", "modules"]):
    try:
        env[f["relation"]]
    except Exception:
        bad_rel.append((f["model"], f["name"], f["relation"], f["modules"]))
P("CHK3 relational fields with missing comodel:", len(bad_rel), bad_rel[:8])

# combined view validation (Odoo 18+: 'list' replaced 'tree')
broken, checked = [], 0
model_ids = {r["model"] for r in env["ir.model"].sudo().search_read([], ["model"])}
viewed = {v["model"] for v in env["ir.ui.view"].sudo().search_read([("type", "in", ["form", "tree", "list"])], ["model"])}
for m in sorted(viewed & model_ids):
    for vtype in ("form", "list"):
        try:
            env[m].sudo().get_view(None, vtype)
            checked += 1
        except Exception as e:
            msg = str(e)[:110]
            if "could not be found" in msg:
                continue
            broken.append((m, vtype, msg))
P("CHK4 combined views validated OK:", checked, "| broken:", len(broken), broken[:6])

D = env["ir.model.data"].sudo()
dead, seen = [], {}
for rec in D.search_read([], ["model", "res_id", "module", "name"]):
    m, rid = rec["model"], rec["res_id"]
    if not rid:
        continue
    if m not in seen:
        try:
            env[m]
            seen[m] = True
        except Exception:
            seen[m] = False
    if not seen.get(m):
        continue
    try:
        if not env[m].sudo().browse(rid).exists():
            dead.append((rec["module"], rec["name"], m, rid))
    except Exception:
        pass
    if len(dead) >= 40:
        break
P("CHK5 dangling xml_ids:", len(dead), dead[:6])

bad_act = []
for a in env["ir.actions.act_window"].sudo().search_read([], ["name", "res_model"]):
    if a["res_model"] and a["res_model"] not in model_ids:
        bad_act.append((a["name"], a["res_model"]))
P("CHK6 window actions with missing res_model:", len(bad_act), bad_act[:6])

from odoo.tools.safe_eval import safe_eval
bad_rules, okr = [], 0
for r in env["ir.rule"].sudo().search([]):
    try:
        ctx = r._eval_context() if hasattr(r, "_eval_context") else {
            "user": env.user, "time": time,
            "company_ids": env.companies.ids, "company_id": env.company.id}
        safe_eval(r.domain_force or "[]", ctx)
        okr += 1
    except Exception as e:
        bad_rules.append((r.name, str(e)[:70]))
P("CHK7 security rules eval: ok=%d broken=%d" % (okr, len(bad_rules)), bad_rules[:5])

bad_cron = env["ir.cron"].sudo().search_count([("interval_number", "<=", 0)])
P("CHK8 crons:", env["ir.cron"].sudo().search_count([]), "| bad interval:", bad_cron)

neg = env["ir.sequence"].sudo().search_count([("number_next_actual", "<", 0)])
P("CHK9 sequences:", env["ir.sequence"].sudo().search_count([]), "| negative next numbers:", neg)

orph = []
for mm in env["mail.message"].sudo().search_read([("model", "!=", False)], ["model", "res_id"], limit=4000):
    m, rid = mm["model"], mm["res_id"]
    if rid and m in model_ids and not env[m].sudo().browse(rid).exists():
        orph.append((m, rid))
    if len(orph) >= 10:
        break
P("CHK10 orphan mail.messages (probe 4000):", len(orph), orph[:4])

orph2 = []
for at in env["ir.attachment"].sudo().search_read([("res_model", "!=", False)], ["res_model", "res_id"], limit=4000):
    m, rid = at["res_model"], at["res_id"]
    if rid and m in model_ids and not env[m].sudo().browse(rid).exists():
        orph2.append((m, rid))
    if len(orph2) >= 10:
        break
P("CHK10B orphan attachments (probe 4000):", len(orph2), orph2[:4])

with_acl = {r["model_id"][1] if isinstance(r["model_id"], tuple) else r["model_id"]
            for r in env["ir.model.access"].sudo().search_read([], ["model_id"])}
no_acl = [r["model"] for r in env["ir.model"].sudo().search_read(
    [("transient", "=", False)], ["model"]) if r["model"] not in with_acl]
P("CHK11 models without any ACL:", len(no_acl), no_acl[:6])

owning = set()
for r in env["ir.model"].sudo().search_read([], ["model", "modules"]):
    for mod in (r["modules"] or "").split(","):
        owning.add(mod.strip())
empty = sorted(installed - owning)
P("CHK12 installed modules owning no model:", len(empty), empty[:10])

orph_co = {}
for mname in ("res.partner", "product.template", "account.move", "sale.order",
              "purchase.order", "crm.lead", "hr.employee", "project.project"):
    if mname in model_ids and env[mname]._fields.get("company_id"):
        try:
            n = env[mname].sudo().search_count([("company_id", "=", False)])
            if n:
                orph_co[mname] = n
        except Exception:
            pass
P("CHK13 business records without company (informational):", orph_co or "none")

P("CHK14 menus:", env["ir.ui.menu"].sudo().search_count([]),
  "| companies:", env["res.company"].sudo().search_count([]),
  "| active users:", env["res.users"].sudo().search_count([("active", "=", True)]))
P("AUDIT-DONE elapsed %.1fs" % (time.time() - t0))
env.cr.commit()
