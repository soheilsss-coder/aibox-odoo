from odoo import api, SUPERUSER_ID


def _ensure_xmlid(env, module, name, record):
    imd = env["ir.model.data"].sudo()
    existing = imd.search([("module", "=", module), ("name", "=", name)], limit=1)
    if existing:
        return
    imd.create({
        "module": module,
        "name": name,
        "model": record._name,
        "res_id": record.id,
        "noupdate": True,
    })


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Groups = env["res.groups"].sudo()
    category = env.ref("ai_business_tools.role_category", raise_if_not_found=False)
    group = env.ref("ai_business_tools.group_ai_automation_service", raise_if_not_found=False)
    if not group:
        group = Groups.search([("name", "=", "AI Automation Service")], limit=1)
    if not group:
        vals = {"name": "AI Automation Service"}
        if category:
            vals["category_id"] = category.id
        group = Groups.create(vals)
        _ensure_xmlid(env, "ai_business_tools", "group_ai_automation_service", group)
    base_user = env.ref("base.group_user", raise_if_not_found=False)
    implied = []
    if base_user and base_user.id not in group.implied_ids.ids:
        implied.append((4, base_user.id))
    if implied:
        group.write({"implied_ids": implied})
    user = env.ref("ai_business_tools.ai_automation_service_user", raise_if_not_found=False)
    if user and group.id not in user.groups_id.ids:
        user.sudo().write({"groups_id": [(4, group.id)]})
