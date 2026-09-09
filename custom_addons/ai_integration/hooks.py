from odoo import SUPERUSER_ID, api


def _environment(first_arg, registry=None):
    if registry is None:
        return first_arg
    return api.Environment(first_arg, SUPERUSER_ID, {})


def post_init_hook(env_or_cr, registry=None):
    env = _environment(env_or_cr, registry)
    env["ai.control.module"].sudo().sync_installed_modules()
