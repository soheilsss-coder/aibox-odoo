"""
Provisions ONE dedicated, read-only-scoped Buzz-bot identity per real
hr.department - run with:
  /opt/odoo/odoo-bin shell -c /opt/odoo.conf -d company_ai < 20_provision_buzz_bot_users.py

Prints a CSV to /opt/buzz_department_bots.csv that
19_setup_buzz_departments.sh consumes to provision the Nostr/channel/
systemd side per department.

SECURITY DESIGN (read before changing the role assigned below):
Each bot user only gets 'Role: Employee' (base.group_user level),
never a manager Role Template. Buzz's own bridge design means every
message routed through a given bridge process runs as ONE FIXED Odoo
identity (roadmap #19, Agent Identity) - there is no per-Nostr-sender
mapping back to an individual employee's own Odoo account the way the
Telegram bridge does it. Keeping the bot's OWN Odoo permissions at the
lowest level means that even if someone tries to get the bot to
approve a leave or grant access, Odoo's own ACL denies it regardless
of who asked - a UX dead-end, never a security hole. Do not "fix" this
by giving bots a manager role for convenience.

Idempotent: running again skips departments that already have a bot.
"""
import csv

BOT_LOGIN_SUFFIX = "@buzz-bot.local"

departments = env["hr.department"].search([])
if not departments:
    print("No hr.department records found - nothing to provision. "
          "(If this is a demo box, run 04_seed_demo_data.sh first.)")
else:
    employee_role = env.ref("ai_business_tools.role_employee")
    rows = []
    for dept in departments:
        slug = "".join(c if c.isalnum() else "-" for c in dept.name.lower()).strip("-")
        login = f"buzz-bot-{slug}{BOT_LOGIN_SUFFIX}"

        user = env["res.users"].search([("login", "=", login)], limit=1)
        if not user:
            user = env["res.users"].with_context(no_reset_password=True).create({
                "name": f"Buzz Bot - {dept.name}",
                "login": login,
                "email": login,
                "groups_id": [(4, employee_role.id)],
            })
            env["hr.employee"].create({
                "name": f"Buzz Bot - {dept.name}",
                "user_id": user.id,
                "department_id": dept.id,
            })
            print(f"Created bot user: {login} (department: {dept.name})")
        else:
            print(f"Bot user already exists, skipping: {login}")

        api_key_rec = env["ai.gateway.api.key"].search([("user_id", "=", user.id)], limit=1)
        secret = env["ai.gateway.api.key"].create_key(user) if not api_key_rec else None
        if secret:
            secret_dir = "/etc/ai-box/buzz-secrets"
            os.makedirs(secret_dir, mode=0o700, exist_ok=True)
            path = os.path.join(secret_dir, slug)
            with open(path, "w", encoding="utf-8") as fh: fh.write(secret + "\n")
            os.chmod(path, 0o600)

        manager_email = dept.manager_id.user_id.login if dept.manager_id and dept.manager_id.user_id else ""
        rows.append({"department": dept.name, "slug": slug, "bot_login": login, "manager_login": manager_email})

    env.cr.commit()

    print(f"\nProvisioned {len(rows)} department bot identities. Secrets are stored only in /etc/ai-box/buzz-secrets with mode 600.")

import os
