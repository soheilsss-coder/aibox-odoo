"""Backfill the first company-scoped customer branding record.

The old debranding module stored only name/domain in global or
company-qualified ir.config_parameter keys.  This migration copies those
values into the explicit branding model while preserving the old values as a
fallback for databases that have not installed ai_debrand yet.
"""

from odoo import SUPERUSER_ID, api


_DEFAULT_COLORS = {
    "primary_color": "#4f8cff",
    "secondary_color": "#8b5cf6",
    "accent_color": "#3dd68c",
    "background_color": "#0f1115",
    "surface_color": "#171a21",
    "surface_alt_color": "#1e222b",
    "text_color": "#e8eaed",
    "text_muted_color": "#9aa1ac",
    "danger_color": "#e5484d",
    "warning_color": "#caa23d",
}


def _company_param(params, key, company_id, default=False):
    return params.get_param(
        "%s.%s" % (key, company_id),
        params.get_param(key, default),
    )


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Branding = env["ai.customer.branding"].sudo()
    companies = env["res.company"].sudo().search([])
    params = env["ir.config_parameter"].sudo()

    for company in companies:
        if Branding.search_count([("company_id", "=", company.id)]):
            continue
        brand_name = _company_param(params, "ai.brand.name", company.id, False)
        brand_domain = _company_param(params, "ai.brand.domain", company.id, False)
        values = {
            "company_id": company.id,
            "brand_name": brand_name or company.name or "Company AI",
            "legal_name": company.name or False,
            "brand_domain": brand_domain or False,
            "logo": company.logo or False,
        }
        values.update(_DEFAULT_COLORS)
        Branding.create(values)
