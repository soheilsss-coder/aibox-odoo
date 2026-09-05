from odoo import SUPERUSER_ID, api


def post_init_hook(cr, registry):
    """Complete the initial module-to-agent catalog after install.

    The control-plane hook can run before this addon in a fresh database
    because dependency installation is ordered. Running the same idempotent
    onboarding after this addon is loaded closes that initial ordering gap;
    later official module installs continue through the control-plane cron.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["ai.control.module"].sync_installed_modules()
