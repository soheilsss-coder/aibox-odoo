#!/bin/bash
# =============================================================================
# White-label configuration (roadmap #55) - the "remaining" step that
# item #55 itself flagged: swap YOUR_BRAND_NAME/YOUR_BRAND_DOMAIN for a
# SPECIFIC customer, repeatably, every time a new box ships - not a
# one-off manual sed edit you have to remember how to redo.
#
# WHY NOT JUST HAND-EDIT custom_addons/ai_debrand/data/debrand_data.xml:
# that file is loaded with noupdate="1" (deliberately, per its own
# comment - it must not silently re-run and clobber a value a previous
# round already set). That means re-running `-u ai_debrand` after the
# FIRST install will NOT re-apply changes made to that XML file - Odoo
# skips noupdate records on upgrade by design. So this script does NOT
# edit that XML file at all; it sets the same two things (ir.config_
# parameter 'report.url' and every res.company's report_footer)
# directly through the ORM via `odoo-bin shell`, which always takes
# effect immediately regardless of install history - the correct,
# idempotent way to reconfigure this per customer, at first install or
# on a later rebrand.
#
# The debrand.js static asset (backend/frontend "Odoo" text replace) is
# a real file on disk, not a noupdate XML record, so THAT part is
# still a straightforward, idempotent sed replace.
#
# v24 addition: also patches the chat assistant's own system prompt
# (which used to literally say "running inside Odoo" - a direct source
# of the chat naming its underlying platform when asked) the same
# ORM-not-XML way, for the same noupdate reason. See step [1/3] below.
#
# Usage:
#   BRAND_NAME="Acme AI Suite" BRAND_DOMAIN="app.acme-example.com" \
#     ./14_configure_whitelabel.sh
# =============================================================================
set -e

if [ -z "$BRAND_NAME" ] || [ -z "$BRAND_DOMAIN" ]; then
  echo "Usage: BRAND_NAME=\"Acme AI Suite\" BRAND_DOMAIN=\"app.acme-example.com\" ./14_configure_whitelabel.sh"
  exit 1
fi

ODOO_BIN="${ODOO_BIN:-/opt/odoo/src/odoo/odoo-bin}"
ODOO_PYTHON="${ODOO_PYTHON:-/opt/odoo/venv/bin/python}"
ODOO_CONF="${ODOO_CONF:-/etc/odoo/odoo.conf}"
ODOO_DB="${ODOO_DB:-company_ai}"
ADDONS_DIR="${ADDONS_DIR:-/opt/odoo-custom-addons}"
DEBRAND_JS="${ADDONS_DIR}/ai_debrand/static/src/js/debrand.js"

echo "=== [1/3] Setting brand name/domain in the database (ir.config_parameter + res.company) ==="
"$ODOO_PYTHON" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$ODOO_DB" <<PYEOF
brand_name = ${BRAND_NAME@Q}
brand_domain = ${BRAND_DOMAIN@Q}

param = env["ir.config_parameter"].sudo()
old_domain = param.get_param("ai.brand.domain", default="(not set)")
param.set_param("ai.brand.domain", "https://" + brand_domain)
param.set_param("ai.brand.name", brand_name)
print(f"ai.brand.domain: {old_domain!r} -> https://{brand_domain}")

companies = env["res.company"].sudo().search([])
old_footers = companies.mapped("report_footer")
companies.write({"report_footer": brand_name})
print(f"res.company.report_footer for {len(companies)} companies: {old_footers} -> {brand_name!r}")

env.cr.commit()
print("Committed.")

# --- v24: chat-assistant identity leak -----------------------------
# The Company Assistant's own system prompt used to literally say
# "running inside Odoo" (company_ai_demo/data/llm_agent_data.xml) - so
# when someone asked the chat "what are you built on?" it could just
# read that back. The XML file itself was fixed to no longer say that
# AND to add an explicit "never name the underlying platform" rule -
# but that file is noupdate="1" (same reason as debrand_data.xml
# above), so on a box that was installed BEFORE this fix, only editing
# the XML source does nothing until this also runs directly via ORM.
assistant = env["llm.assistant"].sudo().search([("name", "=", "Company Assistant")], limit=1)
if assistant and assistant.default_values:
    import json as _json
    try:
        vals = _json.loads(assistant.default_values)
    except ValueError:
        vals = None
    if vals is not None:
        changed = False
        if "in Odoo" in vals.get("background", "") or "running inside Odoo" in vals.get("background", ""):
            vals["background"] = ("You are the internal AI assistant for this company. "
                                   "You act strictly with the permissions of the employee "
                                   "who is chatting with you right now.")
            changed = True
        if "in Odoo" in vals.get("goal", ""):
            vals["goal"] = vals["goal"].replace(" in Odoo", "")
            changed = True
        if "13." not in vals.get("instructions", ""):
            vals["instructions"] = vals.get("instructions", "") + (
                "\n13. هرگز نام Odoo، نام هیچ پلتفرم/فریمورک فنی زیرساختی، یا نام هیچ "
                "مدل زبانی که پشت این سیستم است را به کاربر نگو - نه در پاسخ عادی، نه "
                "اگر مستقیم پرسیدند «این روی چی ساخته شده؟» یا «کدوم مدل هستی؟». فقط "
                "بگو: «من دستیار داخلی همین شرکت هستم» و کار خواسته‌شده را انجام بده. "
                "این یک قانون سکوت است، نه دروغ‌گفتن - هرگز اسم غلط دیگری هم نساز، "
                "فقط پاسخ نده."
            )
            changed = True
        if changed:
            assistant.write({"default_values": _json.dumps(vals, ensure_ascii=False)})
            env.cr.commit()
            print("Company Assistant system prompt patched to remove the Odoo mention "
                  "and add the never-reveal-platform rule.")
        else:
            print("Company Assistant system prompt already clean (nothing to patch).")
elif not assistant:
    print("No 'Company Assistant' llm.assistant record found - skipped the chat-prompt patch "
          "(is company_ai_demo installed?).")
PYEOF

echo ""
echo "=== [2/3] Updating the debrand.js static asset (backend/login page text replace) ==="
if [ -f "$DEBRAND_JS" ]; then
  # Idempotent: matches whatever the current BRAND_NAME value is
  # (placeholder OR a previously-set brand), not just the placeholder,
  # so re-running this for a rebrand works too.
  sed -i "s/var BRAND_NAME = \"[^\"]*\";/var BRAND_NAME = \"${BRAND_NAME}\";/" "$DEBRAND_JS"
  echo "Updated: $DEBRAND_JS"
else
  echo "WARNING: $DEBRAND_JS not found - is ai_debrand deployed under \$ADDONS_DIR? (ADDONS_DIR=$ADDONS_DIR)"
  echo "         Skipped the JS text-replace step; the database values above were still set."
fi

echo ""
echo "=== [3/3] Restart required for the JS change to take effect ==="
echo "Odoo caches the compiled web.assets_backend/web.assets_frontend bundle -"
echo "a plain page refresh will NOT pick up the new debrand.js content. Restart"
echo "Odoo (or bump the asset bundle) before showing this to the customer."
echo ""
echo "======================================================================"
echo "Done. This script can NOT verify what actually renders in a browser -"
echo "you still must open the real running site and manually confirm"
echo "(same reminder debrand_templates.xml itself gives, roadmap #55):"
echo "  1. The login page shows '${BRAND_NAME}', not 'Odoo'"
echo "  2. The browser tab title shows '${BRAND_NAME}'"
echo "  3. One real outgoing email (e.g. a leave-approval notification)"
echo "     shows the new footer, not the Odoo default"
