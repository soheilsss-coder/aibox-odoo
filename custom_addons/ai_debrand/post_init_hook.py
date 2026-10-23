"""Post-install: apply the white-label values that need Python.

<function> tags in the data XML cannot express "write to every company"
safely in Odoo 18 (a recordset <value> crashes the install), so the
branding write lives here instead - idempotent, all companies.
"""
__all__ = ["post_init_hook"]


def post_init_hook(env):
    companies = env["res.company"].sudo().search([])
    if companies:
        companies.write({"report_footer": "Company AI"})
