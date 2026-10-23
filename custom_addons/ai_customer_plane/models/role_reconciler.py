from odoo import models

class AiRoleReconciler(models.Model):
    _inherit = "res.users"

    def _ai_reconcile_product_roles(self):
        Role = self.env["res.groups"].sudo()
        product_roles = Role.search([]).filtered(lambda g: (g.get_external_id().get(g.id, "") or "").startswith("ai_business_tools.role_"))
        managed = Role.browse()
        for role in product_roles:
            managed |= role.implied_ids
        managed |= product_roles
        for user in self: 
            # Administrators (base.group_system) and the superuser are
            # hand-managed vendor accounts: the reconciler must never strip
            # their groups. During mass module installs Odoo writes groups_id
            # on users to apply new implied groups, which used to wipe
            # group_system off admin and lock the whole console out.
            if user.id == self.env.uid or user._is_superuser() or user.has_group("base.group_system"):
                continue
            direct_roles = user.groups_id & product_roles
            desired = Role.browse()
            for role in direct_roles:
                desired |= role
                desired |= role.implied_ids
            current_managed = user.groups_id & managed
            remove = current_managed - desired
            if remove:
                user.with_context(ai_role_reconcile=True).write({"groups_id": [(3, g.id) for g in remove]})

    def write(self, vals):
        res = super().write(vals)
        if "groups_id" in vals and not self.env.context.get("ai_role_reconcile"):
            self._ai_reconcile_product_roles()
        return res
