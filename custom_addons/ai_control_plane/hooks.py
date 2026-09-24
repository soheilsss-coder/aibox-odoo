def post_init_hook(env):
    """Discover the modules installed on this appliance.

    This Odoo calls module hooks with ``env`` (older releases passed
    ``cr, registry`` - support both so the hook never breaks an install).
    """
    if hasattr(env, "cr"):
        env["ai.control.module"].sync_installed_modules()
        return
    cr, registry = env
    from odoo import api, SUPERUSER_ID

    api.Environment(cr, SUPERUSER_ID, {})["ai.control.module"].sync_installed_modules()
