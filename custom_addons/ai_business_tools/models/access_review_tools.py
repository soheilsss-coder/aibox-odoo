from odoo import fields, models
from odoo.addons.llm_tool.decorators import llm_tool


class LLMToolAccessGrant(models.Model):
    _inherit = "llm.tool"

    @llm_tool(destructive_hint=True)
    def grant_temporary_access(self, user_name: str = "", role_name: str = "",
                                expires_on: str = "", reason: str = "") -> dict:
        """Give someone a role/group temporarily, with automatic
        expiry (roadmap #41 Delegation / #42 Temporary Access) - e.g.
        'give my deputy HR Manager access until Aug 25 while I'm on
        leave'. user_name, role_name and expires_on are all REQUIRED;
        ask the user for any that are missing rather than guessing.

        PERMISSION RULE (enforced here, not just by ACL): you may only
        grant a role that you YOURSELF currently hold (delegating your
        own authority), unless you are an Executive or System
        Administrator - a Warehouse Staff member can never grant
        someone HR Manager access, even temporarily, even for
        themselves.

        Parameters:
            user_name: Name of the person to grant access to.
            role_name: Exact or partial name of the role/group, e.g.
                'HR Manager' (matches 'Role: HR Manager').
            expires_on: Date the access should automatically end, YYYY-MM-DD.
            reason: Optional short reason.
        """
        self.env["ai.gateway.execution.gate"].authorize("grant_temporary_access")

        missing = [n for n, v in (
            ("user_name", user_name), ("role_name", role_name), ("expires_on", expires_on)
        ) if not v]
        if missing:
            return {"error": "missing_required_field", "missing_fields": missing,
                    "hint": "دقیقاً همین فیلد(های) گم‌شده را از کاربر بپرس."}

        target_users = self.env["res.users"].search([("name", "ilike", user_name)])
        if len(target_users) > 1:
            return {"error": "ambiguous_user", "message": "چند کاربر پیدا شد؛ ایمیل یا شناسه کارمند را مشخص کنید.", "candidates": target_users.mapped("name")}
        target_user = target_users[:1]
        if not target_user:
            return {"error": f"کاربری با نام '{user_name}' پیدا نشد."}

        groups = self.env["res.groups"].search([("name", "ilike", role_name)])
        groups = groups.filtered(lambda g: (getattr(g, "module", "") or "") == "ai_business_tools" or any(v.startswith("ai_business_tools.") for v in g.get_external_id().values()))
        if len(groups) > 1:
            return {"error": "ambiguous_role", "message": "چند نقش پیدا شد؛ نام دقیق نقش را مشخص کنید.", "candidates": groups.mapped("name")}
        group = groups[:1]
        if not group:
            return {"error": f"نقش/گروهی با نام '{role_name}' پیدا نشد."}

        executive = self.env.ref("ai_business_tools.role_executive", raise_if_not_found=False)
        sysadmin = self.env.ref("ai_business_tools.role_system_admin", raise_if_not_found=False)
        is_privileged = (
            (executive and executive in self.env.user.groups_id)
            or (sysadmin and sysadmin in self.env.user.groups_id)
        )
        if not is_privileged and group not in self.env.user.groups_id:
            return {"error": "access_denied: شما فقط می‌توانید نقشی را که خودتان دارید موقتاً تفویض کنید."}

        grant = self.env["ai.gateway.access.grant"].sudo().create({
            "to_user_id": target_user.id,
            "group_id": group.id,
            "delegated_from_id": self.env.user.id if group in self.env.user.groups_id else False,
            "expires_on": expires_on,
            "reason": reason or "",
            "granted_by_id": self.env.user.id,
        })
        if "ai.gateway.audit.log" in self.env:
            self.env["ai.gateway.audit.log"].sudo().log(
                user_id=self.env.user.id, source="tool", action="grant_temporary_access",
                payload={"user": target_user.name, "role": group.name, "expires_on": expires_on},
            )
        return {"status": "scheduled", "grant_id": grant.id, "user": target_user.name,
                "role": group.name, "expires_on": expires_on,
                "note": "این دسترسی توسط cron روزانه فعال و در تاریخ انقضا خودکار برداشته می‌شود."}

    @llm_tool(read_only_hint=True)
    def list_elevated_access(self) -> dict:
        """Return the privileged-access review only to authorized reviewers.

        Authorization is checked BEFORE any privileged group membership or
        temporary-grant data is queried, preventing information disclosure
        through an unauthorized caller.
        """
        allowed_roles = (
            "ai_business_tools.role_hr_manager",
            "ai_business_tools.role_security",
            "ai_business_tools.role_executive",
            "ai_business_tools.role_system_admin",
        )
        if not any(self.env.user.has_group(x) for x in allowed_roles):
            raise AccessError("access_denied: elevated access review is restricted")

        sensitive_role_xmlids = [
            "ai_business_tools.role_hr_manager", "ai_business_tools.role_finance_manager",
            "ai_business_tools.role_warehouse_manager", "ai_business_tools.role_executive",
            "ai_business_tools.role_system_admin",
        ]
        holders = []
        for xmlid in sensitive_role_xmlids:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if not group:
                continue
            for user in group.users:
                holders.append({"user": user.name, "role": group.name})

        active_grants = self.env["ai.gateway.access.grant"].sudo().search(
            [("state", "in", ("scheduled", "active"))]
        )
        return {
            "elevated_role_holders": holders,
            "active_temporary_grants": [
                {"user": g.to_user_id.name, "role": g.group_id.name,
                 "expires_on": str(g.expires_on), "state": g.state,
                 "delegated_from": g.delegated_from_id.name if g.delegated_from_id else None}
                for g in active_grants
            ],
        }
