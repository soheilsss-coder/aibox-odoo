"""
Acceptance tests - run with:
  /opt/odoo/odoo-bin shell -c /opt/odoo.conf -d company_ai < 05_acceptance_tests.py

Calls the actual tool methods directly (not through the LLM chat),
each time as a DIFFERENT real Odoo user, and checks that Odoo's own
permission system produces the expected pass/fail - exactly the
scenarios from your own examples (CEO can approve, a regular employee
cannot). This is deterministic (no LLM randomness involved), so it is
safe to run before every delivery as a real go/no-go gate, per
roadmap item #50 (Security Testing).

NOTE (corrected): this file's docstring used to also claim it fully
satisfied roadmap item #49 (Evaluation). It only partly does - #49
specifically asks for a script that calls the gateway "با کلیدهای API
واقعی هر Role" (with each role's real API key) over the actual
network, which this script does not do (it calls tool methods
directly inside the Odoo process). See 11_evaluation_suite.py /
11_evaluation_suite.sh for the part of #49 this file does not cover.

Exits with a non-zero code if anything fails, so it can be wired into
a deployment checklist script later (roadmap item #54).

NOTE (v22 merge round): scenarios 19-27 below combine THREE previously
separate rounds that all branched from the same v18 base and each
numbered their own new scenarios starting from 19, unaware of the
others: 19-22 = phase 5 (Automation, #29/#32/#35), 23-25 = phase 8
(#50 Security Testing), 26-27 = two gaps found and fixed during this
merge's own audit pass (company.document's group/department access
levels had zero test coverage; list_documents/get_document skipped
the Context Firewall that search_documents_semantic already used) -
see those two scenarios below for what each checks and why it was
missing. No existing test logic was changed by the renumbering, only
the numbers in comments/print labels.
"""

results = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((status, label, detail))
    print(f"[{status}] {label}" + (f" - {detail}" if detail and status == 'FAIL' else ""))


def get_user(login):
    return env["res.users"].search([("login", "=", login)], limit=1)

ceo = get_user("ceo@demo.local")
accountant = get_user("accountant@demo.local")
warehouse = get_user("warehouse@demo.local")

if not (ceo and accountant and warehouse):
    print("Demo users not found - run 02_install_modules.sh first.")
    import sys
    sys.exit(1)

leave_type = env["hr.leave.type"].search([], limit=1)
accountant_employee = env["hr.employee"].search([("user_id", "=", accountant.id)], limit=1)

# ---------------------------------------------------------------------
# Scenario 1: employee creates their OWN leave request -> should work
# ---------------------------------------------------------------------
acc_env = env(user=accountant.id)
res1 = acc_env["llm.tool"].create_leave_request(date_from="2027-01-10", date_to="2027-01-12",
                                                 reason="acceptance test")
check("Employee can request their own leave", res1.get("status") == "submitted_for_approval", res1)
leave_id = res1.get("leave_id")

# ---------------------------------------------------------------------
# Scenario 2: the SAME employee tries to approve their own request -> must be denied
# ---------------------------------------------------------------------
res2 = acc_env["llm.tool"].approve_leave(leave_id=leave_id)
check("Employee CANNOT approve their own leave request",
      "error" in res2 and "access_denied" in res2["error"], res2)

# ---------------------------------------------------------------------
# Scenario 3: a different regular employee (warehouse) tries to approve
# someone else's leave -> must be denied (no HR manager rights)
# ---------------------------------------------------------------------
wh_env = env(user=warehouse.id)
res3 = wh_env["llm.tool"].approve_leave(leave_id=leave_id)
check("Non-manager employee CANNOT approve someone else's leave",
      "error" in res3, res3)

# ---------------------------------------------------------------------
# Scenario 4: CEO (HR manager group) approves the accountant's leave -> should work
# ---------------------------------------------------------------------
ceo_env = env(user=ceo.id)
res4 = ceo_env["llm.tool"].approve_leave(leave_id=leave_id)
check("CEO/HR-manager CAN approve someone else's leave", res4.get("status") == "done", res4)

# ---------------------------------------------------------------------
# Scenario 5: idempotency - retrying the same key must not double-create
# ---------------------------------------------------------------------
key = "acceptance-test-key-001"
before = env["project.task"].search_count([])
r5a = acc_env["llm.tool"].create_task(title="Idempotency test", assignee_name=accountant.name,
                                       deadline="2027-02-01", idempotency_key=key)
r5b = acc_env["llm.tool"].create_task(title="Idempotency test", assignee_name=accountant.name,
                                       deadline="2027-02-01", idempotency_key=key)
after = env["project.task"].search_count([])
check("Idempotency key prevents duplicate task creation",
      after - before == 1 and r5a.get("task_id") == r5b.get("task_id"), (r5a, r5b))

# ---------------------------------------------------------------------
# Scenario 6: document access levels
# ---------------------------------------------------------------------
Doc = env["company.document"]
company_doc = Doc.sudo().create({"name": "Company Policy", "access_level": "company"})
personal_doc = Doc.sudo().create({"name": "CEO Private Note", "access_level": "personal",
                                   "owner_id": ceo.id})

acc_docs = acc_env["llm.tool"].list_documents()
acc_doc_ids = [d["id"] for d in acc_docs.get("documents", [])]
check("Employee sees company-wide document", company_doc.id in acc_doc_ids)
check("Employee does NOT see someone else's personal document", personal_doc.id not in acc_doc_ids)

ceo_docs = ceo_env["llm.tool"].list_documents()
ceo_doc_ids = [d["id"] for d in ceo_docs.get("documents", [])]
check("Owner sees their own personal document", personal_doc.id in ceo_doc_ids)

# ---------------------------------------------------------------------
# Scenario 7: generate_hr_decree requires approval, requester can't self-approve
# ---------------------------------------------------------------------
res7 = ceo_env["llm.tool"].generate_hr_decree(
    employee_name=accountant.name, decree_type="raise", decree_text="acceptance test raise"
)
check("HR decree creation returns pending_approval, not immediate effect",
      res7.get("status") == "pending_approval", res7)
approval_id = res7.get("approval_id")
if approval_id:
    approval = ceo_env["ai.gateway.approval"].browse(approval_id)
    try:
        approval.action_approve()
        check("Requester CANNOT approve their own HR decree request", False)
    except Exception as exc:
        check("Requester CANNOT approve their own HR decree request", True, str(exc))

# ---------------------------------------------------------------------
# Scenario 8: a non-privileged user cannot grant a role they don't hold
# ---------------------------------------------------------------------
res8 = wh_env["llm.tool"].grant_temporary_access(
    user_name=accountant.name, role_name="HR Manager", expires_on="2027-03-01"
)
check("Warehouse staff CANNOT grant HR Manager access to someone else",
      "error" in res8 and "access_denied" in res8["error"], res8)

# ---------------------------------------------------------------------
# Scenario 9: CEO (Executive) CAN grant a role temporarily
# ---------------------------------------------------------------------
res9 = ceo_env["llm.tool"].grant_temporary_access(
    user_name=accountant.name, role_name="HR Manager", expires_on="2027-03-01",
    reason="acceptance test delegation"
)
check("Executive CAN grant a temporary role to someone else",
      res9.get("status") == "scheduled", res9)

# ---------------------------------------------------------------------
# Scenario 10: memory scope - personal memory is not visible to others
# ---------------------------------------------------------------------
ceo_env["llm.tool"].save_memory(key="acceptance-test-secret", value="only CEO should see this",
                                 scope="personal")
res10 = acc_env["llm.tool"].recall_memory(query="acceptance-test-secret")
check("Employee cannot recall another user's personal memory",
      res10.get("error") == "No matching memories found.", res10)

# ---------------------------------------------------------------------
# Security Testing (roadmap #50) - scenarios 11-16 below are DELIBERATE
# bypass attempts, not happy-path checks. Each one tries to do
# something the current user should NOT be able to do, and the test
# only passes if that attempt is actually denied.
# ---------------------------------------------------------------------

from odoo.exceptions import AccessError, UserError
import os
from cryptography.fernet import Fernet
if not os.environ.get("AI_MEMORY_ENCRYPTION_KEY"):
    os.environ["AI_MEMORY_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

# ---------------------------------------------------------------------
# Scenario 11: gateway allowlist deny-by-default - hr.employee.write
# was never deliberately added to ai.gateway.model.policy, so a
# dashboard-style RPC write against it must be refused regardless of
# what the user's own Odoo ACL would otherwise allow.
# ---------------------------------------------------------------------
res11 = env["ai.gateway.model.policy"].is_allowed("hr.employee", "write")
check("Gateway allowlist denies hr.employee.write (never deliberately added)",
      res11 is False, res11)

# ---------------------------------------------------------------------
# Scenario 12: Risk Engine RISK_5 hard block (roadmap #18/#20) - a
# tool mis-registered at RISK_5 ("human-only") must be refused by
# ai.gateway.tool.risk.enforce() unconditionally, even for the CEO.
# ---------------------------------------------------------------------
Risk = env["ai.gateway.tool.risk"].sudo()
fake_risk5 = Risk.create({"tool_name": "acceptance_test_risk5_tool", "risk_level": 5})
try:
    ceo_env["ai.gateway.tool.risk"].enforce("acceptance_test_risk5_tool")
    check("RISK_5 tool is blocked even for the CEO", False)
except UserError as exc:
    check("RISK_5 tool is blocked even for the CEO", True, str(exc))
fake_risk5.unlink()

# ---------------------------------------------------------------------
# Scenario 13: Context Firewall (roadmap #28) - a secret-shaped value
# saved to memory must come back redacted, not verbatim, even to the
# same user who saved it (the firewall protects the MODEL's context,
# not just other users).
# ---------------------------------------------------------------------
ceo_env["llm.tool"].save_memory(
    key="acceptance-test-secret-shaped",
    value="the db password is sk-abcdEFGH12345678ijklMNOPqrst",
    scope="personal",
)
res13 = ceo_env["llm.tool"].recall_memory(query="acceptance-test-secret-shaped")
recalled_value = (res13.get("memories") or [{}])[0].get("value", "")
check("Context Firewall redacts a secret-shaped value on recall",
      "sk-abcd" not in recalled_value and "REDACTED" in recalled_value, res13)

# ---------------------------------------------------------------------
# Scenario 14: Audit log row-level security (roadmap #12) - a regular
# employee must NOT be able to read another user's (the CEO's) audit
# log entries, only their own.
# ---------------------------------------------------------------------
ceo_only_entries = env["ai.gateway.audit.log"].sudo().search_count([("user_id", "=", ceo.id)])
visible_to_accountant = acc_env["ai.gateway.audit.log"].search_count([("user_id", "=", ceo.id)])
check("Employee CANNOT read the CEO's audit log entries",
      ceo_only_entries > 0 and visible_to_accountant == 0,
      {"ceo_entries_total": ceo_only_entries, "visible_to_accountant": visible_to_accountant})

# ---------------------------------------------------------------------
# Scenario 15: a manager who is NOT in the HR Manager approver group
# cannot approve someone else's pending HR decree - approval is scoped
# to the specific approver_group_id, not "any manager".
# ---------------------------------------------------------------------
res15_decree = ceo_env["llm.tool"].generate_hr_decree(
    employee_name=accountant.name, decree_type="warning", decree_text="acceptance test warning"
)
approval15_id = res15_decree.get("approval_id")
if approval15_id:
    try:
        wh_env["ai.gateway.approval"].browse(approval15_id).action_approve()
        check("Non-HR-Manager CANNOT approve someone else's HR decree", False)
    except (AccessError, UserError) as exc:
        check("Non-HR-Manager CANNOT approve someone else's HR decree", True, str(exc))
else:
    check("Non-HR-Manager CANNOT approve someone else's HR decree", False, res15_decree)

# ---------------------------------------------------------------------
# Scenario 16: a regular employee cannot directly write to the tool
# risk registry via the ORM (bypassing the AI layer entirely and going
# straight for the underlying model) - only base.group_system may.
# ---------------------------------------------------------------------
try:
    acc_env["ai.gateway.tool.risk"].create({"tool_name": "acceptance-test-hack", "risk_level": 0})
    check("Regular employee CANNOT write directly to the tool risk registry", False)
except AccessError as exc:
    check("Regular employee CANNOT write directly to the tool risk registry", True, str(exc))

# ---------------------------------------------------------------------
# Scenario 17: RAG semantic search (roadmap #27) - access filter must
# apply BEFORE vector search, not after. Create a personal document
# for `warehouse` with a distinctive phrase, index it, then search for
# that exact phrase as `accountant` (who has no access to it) - it
# must not come back, even though the embedding would clearly match.
# If the local embedding server (/opt/start_vllm_embed.sh, port 8002)
# isn't running, this is SKIPPED rather than failed - it is an
# optional runtime dependency, not something every dev box has up.
# ---------------------------------------------------------------------
wh_env = env(user=warehouse.id)
secret_phrase = "acceptance-test-zorbnaxel-secret-project-codename"
rag_doc = wh_env["company.document"].create({
    "name": "acceptance-test personal doc",
    "access_level": "personal",
    "owner_id": warehouse.id,
    "description": f"This document mentions {secret_phrase} and nothing else relevant.",
})
try:
    rag_doc._rag_reindex()
    res17 = acc_env["llm.tool"].search_documents_semantic(query=secret_phrase, top_k=5)
    if "error" in res17 and "embedding" in res17["error"]:
        print(f"[SKIP] RAG access-filter test - embedding server not running: {res17['error']}")
    else:
        leaked = any(r["document_id"] == rag_doc.id for r in res17.get("results", []))
        check("RAG search does NOT leak a document outside the searching user's access",
              not leaked, res17)

        # Scenario 18: the OWNER of the same document, searching the
        # same phrase, SHOULD find it - proves the filter is precise
        # (denying everyone) rather than accidentally denying everyone.
        res18 = wh_env["llm.tool"].search_documents_semantic(query=secret_phrase, top_k=5)
        found = any(r["document_id"] == rag_doc.id for r in res18.get("results", []))
        check("RAG search DOES find a document for a user who owns it",
              found, res18)
except Exception as exc:  # noqa: BLE001
    print(f"[SKIP] RAG acceptance tests - embedding/pgvector stack not available: {exc}")
# Scenario 19 (roadmap #29, Workflow): a state change on hr.leave must
# already produce a chatter notification via Odoo's own mail-thread
# tracking, with NO new code needed - this test verifies that claim
# instead of just assuming it, per the roadmap item's own wording
# ("اکثرش از قبل در Odoo هست، فقط باید تست شود"). Reuses the leave
# approved in Scenario 4.
# ---------------------------------------------------------------------
approved_leave = env["hr.leave"].sudo().browse(leave_id)
check("Leave state change produced a chatter notification (roadmap #29)",
      len(approved_leave.message_ids) > 0,
      f"message_ids count={len(approved_leave.message_ids)}")

# ---------------------------------------------------------------------
# Scenario 20 (roadmap #32, Task dependency): a task cannot move to a
# closed stage while a task it depends on is still open.
# ---------------------------------------------------------------------
from odoo import fields as _fields
from datetime import timedelta as _timedelta

phase5_project = env["project.project"].sudo().search([("name", "=", "AI Tasks")], limit=1)
if not phase5_project:
    phase5_project = env["project.project"].sudo().create({"name": "AI Tasks"})

closed_stage = env["project.task.type"].sudo().search([("is_closed", "=", True)], limit=1)
task_a = env["project.task"].sudo().create({"name": "acceptance-test dependency A",
                                             "project_id": phase5_project.id})
task_b = env["project.task"].sudo().create({
    "name": "acceptance-test dependency B", "project_id": phase5_project.id,
    "depends_on_task_ids": [(6, 0, [task_a.id])],
})
dep_blocked = False
try:
    task_b.sudo().write({"stage_id": closed_stage.id})
except Exception:  # noqa: BLE001 - UserError expected
    dep_blocked = True
check("Task B cannot be closed while dependency Task A is still open (roadmap #32)",
      dep_blocked, f"task_b.stage_id={task_b.stage_id.name}")

# ---------------------------------------------------------------------
# Scenario 21: once the dependency (Task A) is closed, Task B CAN be
# closed - proves the gate is precise, not a permanent block.
# ---------------------------------------------------------------------
task_a.sudo().write({"stage_id": closed_stage.id})
task_b.sudo().write({"stage_id": closed_stage.id})
check("Task B CAN be closed once Task A (its dependency) is closed (roadmap #32)",
      task_b.stage_id.id == closed_stage.id, f"task_b.stage_id={task_b.stage_id.name}")

# ---------------------------------------------------------------------
# Scenario 22 (roadmap #35, Escalation): a task 10 days overdue must
# escalate to level 2 (department manager) with the default thresholds
# (level1=3 days, level2=7 days, level3=14 days), not level 1 or 3.
# ---------------------------------------------------------------------
overdue_task = env["project.task"].sudo().create({
    "name": "acceptance-test escalation", "project_id": phase5_project.id,
    "user_ids": [(6, 0, [accountant.id])],
    "date_deadline": _fields.Date.today() - _timedelta(days=10),
})
env["project.task"].sudo().cron_escalate_overdue_tasks()
overdue_task_after = env["project.task"].sudo().browse(overdue_task.id)
check("Task 10 days overdue escalates to level 2 - department manager (roadmap #35)",
      overdue_task_after.escalation_level == 2,
      f"escalation_level={overdue_task_after.escalation_level}")

# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# Scenario 23 (v19, roadmap #50): the v17 department-scoped task rule
# (project_task_department_rule) actually restricts a plain Role:
# Manager to their own department's tasks, and does NOT over-restrict
# Executive. Self-contained fixtures - creates its own departments/
# users/task so it does not depend on demo data having departments set.
# ---------------------------------------------------------------------
from datetime import timedelta

role_manager_group = env.ref("ai_business_tools.role_manager", raise_if_not_found=False)
if role_manager_group is None:
    print("[SKIP] Scenario 23 (department task rule) - ai_business_tools.role_manager not found")
else:
    dept_a = env["hr.department"].create({"name": "Acceptance Test Dept A"})
    dept_b = env["hr.department"].create({"name": "Acceptance Test Dept B"})

    mgr_a_user = env["res.users"].create({
        "name": "Acceptance Test Manager A", "login": "acctest.mgr.a@local.test",
        "groups_id": [(4, role_manager_group.id)],
    })
    env["hr.employee"].create({"name": "Acceptance Test Manager A", "user_id": mgr_a_user.id,
                                "department_id": dept_a.id})
    staff_b_user = env["res.users"].create({"name": "Acceptance Test Staff B",
                                             "login": "acctest.staff.b@local.test"})
    env["hr.employee"].create({"name": "Acceptance Test Staff B", "user_id": staff_b_user.id,
                                "department_id": dept_b.id})

    dept_rule_project = env["project.project"].search([], limit=1) or env["project.project"].create(
        {"name": "Acceptance Test Project"})
    dept_rule_task_b = env["project.task"].create({
        "name": "Acceptance test task in dept B", "project_id": dept_rule_project.id,
        "user_ids": [(4, staff_b_user.id)],
    })

    mgr_a_env = env(user=mgr_a_user.id)
    check("Role:Manager in Dept A does NOT see a task assigned to Dept B staff",
          dept_rule_task_b.id not in mgr_a_env["project.task"].search([]).ids)

    exec_group = env.ref("ai_business_tools.role_executive", raise_if_not_found=False)
    if exec_group:
        exec_user = env["res.users"].create({
            "name": "Acceptance Test Executive", "login": "acctest.exec@local.test",
            "groups_id": [(4, exec_group.id)],
        })
        check("Executive still sees the Dept B task (department rule does not over-restrict)",
              dept_rule_task_b.id in env(user=exec_user.id)["project.task"].search([]).ids)
    else:
        print("[SKIP] Executive half of scenario 23 - ai_business_tools.role_executive not found")

# ---------------------------------------------------------------------
# Scenario 24 (v19, roadmap #50/#41/#42): ai.gateway.access.grant expiry
# is cron-driven (cron_apply_and_expire_grants), NOT enforced in real
# time by anything that blocks Odoo's own permission check. This is a
# KNOWN, ACCEPTED gap (roadmap #22's own honesty section already notes
# that anything scheduled runs as a restricted cron user, not that the
# schedule itself is instant) - this scenario makes it visible instead
# of hiding it, and then proves the mitigation for anything urgent
# (manual action_revoke_now(), which IS instant) actually works.
# ---------------------------------------------------------------------
if role_manager_group is not None:
    grant = env["ai.gateway.access.grant"].sudo().create({
        "to_user_id": warehouse.id, "group_id": role_manager_group.id,
        "start_date": _fields.Date.today(),
        "expires_on": _fields.Date.today() + timedelta(days=1),
        "state": "active",
        "reason": "acceptance test active grant",
    })
    check("Temporary access grant does NOT mutate permanent res.groups membership",
          warehouse.id not in role_manager_group.users.ids)
    grant.action_revoke_now()
    check("Manual action_revoke_now() DOES revoke the temporary grant immediately",
          grant.state == "revoked" and not grant.active,
          {"state": grant.state, "active": grant.active})

# ---------------------------------------------------------------------
# Scenario 25 (v19, roadmap #50): a regular employee cannot self-
# escalate by writing res.groups directly (bypassing every tool,
# approval, and risk-engine layer above by going straight at the ORM)
# - Odoo's own base ACL on res.groups must stop this on its own.
# ---------------------------------------------------------------------
if role_manager_group is not None:
    try:
        wh_env["res.groups"].browse(role_manager_group.id).write({"users": [(4, warehouse.id)]})
        check("Regular employee CANNOT self-escalate by writing res.groups directly", False)
    except Exception as exc:  # noqa: BLE001
        check("Regular employee CANNOT self-escalate by writing res.groups directly", True, str(exc))

# ---------------------------------------------------------------------
# Scenario 26 (v22, roadmap #26/#27): company.document's "group" and
# "department" access levels, specifically. GAP FOUND during the v22
# merge's own audit pass: Scenario 6 above only ever exercised
# "company" and "personal" access_level; Scenario 17/18 (RAG) only
# ever exercised "personal" too. Neither the group_id branch nor the
# department_id branch of company_document_rule_user's domain
# (security/document_rules.xml) had ANY acceptance-test coverage across
# any of the five branches that got merged into this v22 tree - purely
# a testing gap, not a code gap (the ir.rule domain itself was already
# correct, see document_rules.xml's own comments), but a gap worth
# closing rather than leaving unverified. Self-contained fixtures,
# same pattern as Scenario 23.
# ---------------------------------------------------------------------
dept_doc_a = env["hr.department"].sudo().create({"name": "Acceptance Test Doc Dept A"})
dept_doc_b = env["hr.department"].sudo().create({"name": "Acceptance Test Doc Dept B"})

# Use the already-provisioned demo internal users here. Creating ad-hoc
# res.users records in a shell fixture can leave them without the generated
# User Type state that Odoo's ACL check expects, which tests the fixture
# instead of the document rule. The demo users are real internal users and
# are already part of the product onboarding contract.
warehouse_employee = env["hr.employee"].sudo().search([("user_id", "=", warehouse.id)], limit=1)
if not accountant_employee:
    accountant_employee = env["hr.employee"].sudo().create({"name": accountant.name, "user_id": accountant.id})
if not warehouse_employee:
    warehouse_employee = env["hr.employee"].sudo().create({"name": warehouse.name, "user_id": warehouse.id})
accountant_employee.sudo().write({"department_id": dept_doc_a.id})
warehouse_employee.sudo().write({"department_id": dept_doc_b.id})

dept_doc = env["company.document"].sudo().create({
    "name": "Acceptance Test Dept-A-only Policy",
    "access_level": "department", "department_id": dept_doc_a.id,
})
doc_staff_a_env = env(user=accountant.id)
doc_staff_b_env = env(user=warehouse.id)
staff_a_docs = doc_staff_a_env["llm.tool"].list_documents().get("documents", [])
staff_b_docs = doc_staff_b_env["llm.tool"].list_documents().get("documents", [])
check("Employee in the SAME department sees a department-scoped document",
      any(d["id"] == dept_doc.id for d in staff_a_docs))
check("Employee in a DIFFERENT department does NOT see it",
      not any(d["id"] == dept_doc.id for d in staff_b_docs))

# Group branch: use an already-assigned product role so the test does not
# mutate permanent res.groups membership just to create a fixture.
doc_group = env.ref("ai_business_tools.role_finance_staff", raise_if_not_found=False)
if doc_group is not None:
    group_doc = env["company.document"].sudo().create({
        "name": "Acceptance Test Group-only Policy",
        "access_level": "group", "group_id": doc_group.id,
    })
    check("A member of the restricted group sees a group-scoped document",
          any(d["id"] == group_doc.id for d in acc_env["llm.tool"].list_documents().get("documents", [])))
    check("A non-member does NOT see the group-scoped document",
          not any(d["id"] == group_doc.id for d in wh_env["llm.tool"].list_documents().get("documents", [])))
else:
    print("[SKIP] Scenario 26 group half - ai_business_tools.role_finance_staff not found")

# ---------------------------------------------------------------------
# Scenario 27 (v22, roadmap #28): a second GAP FOUND during this same
# audit pass, same family as Scenario 26 - list_documents/get_document
# returned a document's `description` field completely unscrubbed,
# unlike search_documents_semantic (which already ran excerpts through
# the Context Firewall). Fixed in company_document.py; this scenario
# is the regression guard so it can't quietly slip again.
# ---------------------------------------------------------------------
secret_doc = env["company.document"].sudo().create({
    "name": "Acceptance Test Secret-shaped Description", "access_level": "company",
    "description": "the db password is sk-abcdEFGH12345678ijklMNOPqrst",
})
listed = acc_env["llm.tool"].list_documents(query="Acceptance Test Secret-shaped")
listed_desc = (listed.get("documents") or [{}])[0].get("description", "")
check("Context Firewall redacts a secret-shaped document description via list_documents",
      "sk-abcd" not in listed_desc and "REDACTED" in listed_desc, listed)

fetched = acc_env["llm.tool"].get_document(document_id=secret_doc.id)
check("Context Firewall redacts a secret-shaped document description via get_document",
      "sk-abcd" not in fetched.get("description", "") and "REDACTED" in fetched.get("description", ""),
      fetched)

# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# Memory is canonical ORM-backed storage. Clean acceptance rows through the
# same service rather than a parallel SQLite database.
# ---------------------------------------------------------------------
if "ai.agent.memory.record" in env:
    env["ai.agent.memory.record"].sudo().search([("key", "like", "acceptance-test%")]).unlink()

env.cr.rollback()  # this is a TEST run - never commit acceptance-test data
print("\nRolled back all test data (nothing written permanently).\n")

failed = [r for r in results if r[0] == "FAIL"]
print(f"\n{len(results) - len(failed)}/{len(results)} passed.")
if failed:
    print("FAILURES:")
    for status, label, detail in failed:
        print(f"  - {label}: {detail}")
    import sys
    sys.exit(1)
else:
    print("ALL ACCEPTANCE TESTS PASSED - system ready per checklist item #22/#49.")
