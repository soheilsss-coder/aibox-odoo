#!/usr/bin/env bash
# ==============================================================
# setup_optional_deps.sh - unlock every optional module.
#
# Four catalog modules could not install out of the box because
# their dependency chains point into OCA repositories that ship
# neither with odoo nor with odoo-llm:
#
#   llm_document_page        -> document_page, document_knowledge (OCA/knowledge)
#   llm_tool_mis_builder     -> mis_builder (OCA/mis-builder), report_xlsx
#                               (OCA/reporting-engine), date_range (OCA/server-ux)
#   account_invoice_import_llm -> account_invoice_import, base_business_document_import
#                               (OCA/edi), uom_unece + account_tax_unece + base_unece
#                               (OCA/community-data-files)
#
# This script clones those repos (shallow, 18.0), exposes ONLY the
# needed modules through a symlink dir (so the module catalog does
# not balloon with every OCA repo), installs the small Python
# extras they declare, and appends the dir to addons_path.
#
# auth_ldap is the ONE module this cannot fix: it needs the system
# packages libldap2-dev/libsasl2-dev to build python-ldap. On a
# machine with apt access run:
#   sudo apt-get install -y libldap2-dev libsasl2-dev python3-dev gcc
#   $AIBOX_WS/venv/bin/python -m pip install python-ldap
# and it installs like any other module.
#
# Idempotent: re-running refreshes nothing that already exists.
# Usage:  AIBOX_WS=/path/to/aibox-ws bash sandbox/setup_optional_deps.sh
# ==============================================================
set -u
AIBOX_WS="${AIBOX_WS:-/home/user/aibox-ws}"
OCA_ROOT="${AIBOX_OCA_ROOT:-/tmp/oca}"
SEL="$OCA_ROOT/selected"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

clone() { # clone <org/repo> <dir>
  local repo="$1" dir="$2"
  [ -d "$OCA_ROOT/$dir/.git" ] && { echo "have $dir"; return 0; }
  mkdir -p "$OCA_ROOT"
  git clone -q --depth 1 --branch 18.0 "https://github.com/$repo.git" "$OCA_ROOT/$dir" \
    && echo "cloned $repo" || { echo "WARN: clone $repo failed (offline?)"; return 1; }
}

mkdir -p "$SEL"
clone OCA/knowledge knowledge
clone OCA/mis-builder mis-builder
clone OCA/reporting-engine reporting-engine
clone OCA/server-ux server-ux
clone OCA/community-data-files community-data-files
clone OCA/edi edi

# expose exactly the modules the catalog needs (symlinks keep the
# ir.module.module list small and the install target precise)
link_mod() { [ -e "$SEL/$2" ] || ln -sfn "$OCA_ROOT/$1" "$SEL/$2"; }
link_mod knowledge/document_page document_page
link_mod knowledge/document_knowledge document_knowledge
link_mod mis-builder/mis_builder mis_builder
link_mod reporting-engine/report_xlsx report_xlsx
link_mod server-ux/date_range date_range
link_mod community-data-files/uom_unece uom_unece
link_mod community-data-files/account_tax_unece account_tax_unece
link_mod community-data-files/base_unece base_unece
link_mod edi/account_invoice_import account_invoice_import
link_mod edi/base_business_document_import base_business_document_import

# python extras declared by those modules (+ their llm wrappers)
if [ -x "$AIBOX_WS/venv/bin/python" ]; then
  "$AIBOX_WS/venv/bin/python" -m pip install -q markdownify openupgradelib mistralai \
    && echo "python extras ok" || echo "WARN: python extras failed"
else
  echo "WARN: venv python not found at $AIBOX_WS/venv"
fi

# addons_path: append the selected dir once
CONF="$AIBOX_WS/conf/odoo.conf"
if [ -f "$CONF" ] && ! grep -q "$SEL" "$CONF"; then
  sed -i "s#^addons_path = \(.*\)$#addons_path = \1,$SEL#" "$CONF"
  echo "addons_path updated in $CONF"
fi

# make the new modules visible to the DB registry (needs odoo stopped
# or it picks them up on the next update pass anyway)
echo "NEXT: restart the appliance, then run mass_install_modules.py"
echo "      (it re-scans and installs everything installable)."
