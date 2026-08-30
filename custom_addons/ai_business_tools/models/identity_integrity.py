from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool


class LLMToolIdentityIntegrity(models.Model):
    _inherit = "llm.tool"

    # Roadmap item #1 (Identity): "چیز جدیدی نساز، فقط مطمئن شو هر
    # کارمند دقیقاً یک res.users دارد و کلید API گیت‌وی به همان کاربر
    # گره خورده". The one-key-per-user part is already guaranteed
    # structurally by the user_unique SQL constraint on
    # ai.gateway.api.key. What was still missing is a way to actually
    # VERIFY the "one employee = one traceable identity" part on a
    # real, possibly messy, database (e.g. after Excel onboarding) -
    # this tool is that check, read-only, same style as
    # list_elevated_access (#40).
    @llm_tool(read_only_hint=True)
    def check_identity_integrity(self) -> dict:
        """Identity integrity report (roadmap #1): flags any break in
        the 'one human = one traceable res.users' chain that Identity
        is supposed to guarantee. Does not fix anything, only reports -
        available to any user, but only useful/expected to be run by
        HR/Executive/Admin, e.g. after an Excel import (#36).

        Checks:
        - hr.employee records with no linked res.users (that person
          cannot be identified as an actor in Odoo or the AI gateway
          at all - every action they take is invisible/unattributable).
        - active, non-portal, non-service res.users with no linked
          hr.employee (an account exists but isn't tied to a real
          organizational identity - can't be scoped by department/role
          the way Identity item #1 and Department item #2 assume).
        - internal users with no ai.gateway.api.key yet, i.e. they
          cannot use the AI gateway/frontend until one is created
          (informational, not necessarily an error - many users may
          legitimately only use the Odoo web client).
        """
        if not any(self.env.user.has_group(x) for x in ("ai_business_tools.role_hr_manager", "ai_business_tools.role_security", "ai_business_tools.role_executive", "ai_business_tools.role_system_admin")):
            return {"error": "access_denied: identity integrity is restricted to HR/Security/Executive/System Admin."}

        employees_without_user = self.env["hr.employee"].search(
            [("user_id", "=", False), ("active", "=", True)]
        )

        service_logins = {"ai-automation@service.local"}
        internal_users = self.env["res.users"].search(
            [("share", "=", False), ("active", "=", True)]
        )
        users_without_employee = internal_users.filtered(
            lambda u: not u.employee_id and u.login not in service_logins
        )

        existing_key_user_ids = set(
            self.env["ai.gateway.api.key"].sudo().search([]).mapped("user_id.id")
        )
        users_without_api_key = internal_users.filtered(
            lambda u: u.id not in existing_key_user_ids and u.login not in service_logins
        )

        return {
            "employees_without_user": [
                {"id": e.id, "name": e.name} for e in employees_without_user
            ],
            "users_without_employee": [
                {"id": u.id, "name": u.name, "login": u.login} for u in users_without_employee
            ],
            "users_without_api_key": [
                {"id": u.id, "name": u.name, "login": u.login} for u in users_without_api_key
            ],
            "ok": not employees_without_user and not users_without_employee,
        }
