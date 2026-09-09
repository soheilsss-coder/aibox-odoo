from odoo import SUPERUSER_ID, api


def _environment(first_arg, registry=None):
    """Return an Odoo Environment for both hook APIs.

    Odoo 18 calls post_init_hook(env). Older releases called
    post_init_hook(cr, registry). Supporting both keeps this addon installable
    across the supported migration path.
    """
    if registry is None:
        return first_arg
    return api.Environment(first_arg, SUPERUSER_ID, {})


def post_init_hook(env_or_cr, registry=None):
    """Complete the initial module-to-agent catalog after install.

    The control-plane hook can run before this addon in a fresh database
    because dependency installation is ordered. Running the same idempotent
    onboarding after this addon is loaded closes that initial ordering gap;
    later official module installs continue through the control-plane cron.
    """
    env = _environment(env_or_cr, registry)
    env["ai.control.module"].sudo().sync_installed_modules()
