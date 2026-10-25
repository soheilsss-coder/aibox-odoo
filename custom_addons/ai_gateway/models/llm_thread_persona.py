# -*- coding: utf-8 -*-
"""Access-aware assistant persona.

Every chat turn must know WHO it is talking to and WHAT that person may
see, so the assistant can behave like a professional, personalised
colleague instead of a generic bot - while never crossing the user's
real permission boundary.

The block is injected as an extra system message on EVERY generation
(defence in depth - the technical enforcement stays where it belongs:
capability gate + tool allowlist per user + tools running under the
user's own env + Odoo ACLs/record rules). The prompt layer only tells
the model to respect it.
"""
from odoo import models


class LLMThreadPersona(models.Model):
    _inherit = "llm.thread"

    ROLE_LABELS = (
        ("ai_business_tools.role_executive", "executive"),
        ("ai_business_tools.role_system_admin", "system_admin"),
        ("ai_business_tools.role_manager", "manager"),
        ("ai_business_tools.role_hr_manager", "hr_manager"),
        ("ai_business_tools.role_security", "security_officer"),
        ("ai_gateway.group_developer_admin", "developer_admin"),
        ("base.group_system", "system_admin"),
    )

    def _persona_block(self):
        user = self.env.user
        emp = self.env["hr.employee"].sudo().search(
            [("user_id", "=", user.id)], limit=1)
        dept = emp.department_id.name if emp and emp.department_id else ""
        job = emp.job_title if emp and emp.job_title else ""
        roles = []
        for xmlid, label in self.ROLE_LABELS:
            try:
                if user.has_group(xmlid) and label not in roles:
                    roles.append(label)
            except Exception:  # noqa: BLE001 - unknown xmlid must not break chat
                pass
        if not roles:
            roles = ["employee"]
        lines = [
            "[identity-context] injected by the appliance for THIS user:",
            "user: %s (%s)" % (user.name, user.login),
        ]
        if user.company_id:
            lines.append("company: %s" % user.company_id.name)
        if dept:
            lines.append("department: %s" % dept)
        if job:
            lines.append("job_title: %s" % job)
        lines.append("access_level: %s" % ", ".join(roles))
        lines.append(
            "Behaviour: greet/address the user personally (use their first "
            "name where natural), answer in the language they write in, be "
            "concise, honest and professional. You only have access to the "
            "data this user's own permissions allow - never reveal other "
            "users' private records, salaries or personal data. If a request "
            "is beyond this user's permissions, say clearly that it is "
            "outside their access level and suggest the proper channel."
        )
        return "\n".join(lines)

    def get_prepend_messages(self):
        msgs = super().get_prepend_messages()
        try:
            block = self._persona_block()
        except Exception:  # noqa: BLE001 - persona must never break chat
            return msgs
        return msgs + [{"role": "system", "content": block}]
