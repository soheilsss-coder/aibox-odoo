#!/bin/bash
# =============================================================================
# Customer Onboarding (roadmap #57) - ties together everything built in
# phases 1-8 into the one sequence item #57 itself describes: نصب ->
# Excel import -> تنظیم Role ها -> تنظیم برندینگ -> تست پذیرش -> تحویل
# (install -> Excel import -> Role setup -> branding -> acceptance
# testing -> delivery). Every individual step below already exists as
# its own script - this file does not duplicate any of their logic, it
# just calls them in the right order with the right guardrails, and
# stops at the first real failure instead of plowing ahead with a
# half-configured box.
#
# UPDATE (v24): roadmap items #36/#37 (Excel Preview + Rollback) have
# since landed in onboarding/onboard_from_excel.py - it now runs a real
# Preview -> Approval -> Import pipeline inside one Postgres SAVEPOINT.
# Step 2 below passes ONBOARD_YES=1 to skip that script's own
# interactive "type IMPORT" prompt, since this orchestrator has no
# terminal for it to read from - meaning THIS script trusts whatever
# EXCEL_PATH you gave it without a human re-reading the preview. If you
# want that manual review, run onboard_from_excel.py by itself first
# (its own prompt), then rerun this file with MAINTENANCE_MODE=1 and no
# EXCEL_PATH so it only does steps 3-6.
#
# Usage (fresh box, full run):
#   CUSTOMER_NAME="Acme Corp" \
#   BRAND_NAME="Acme AI Suite" BRAND_DOMAIN="app.acme-example.com" \
#   DOMAIN="app.acme-example.com" EMAIL="you@yourbrand.example" \
#   EXCEL_PATH="/opt/client_employees.xlsx" \
#     ./15_customer_onboarding.sh
#
# Only an explicit maintenance rerun may skip installation/backups. TLS and frontend
# are mandatory for production delivery:
#   MAINTENANCE_MODE=1 ./15_customer_onboarding.sh
# =============================================================================
set -e

ODOO_BIN="${ODOO_BIN:-/opt/odoo/src/odoo/odoo-bin}"
ODOO_PYTHON="${ODOO_PYTHON:-/opt/odoo/venv/bin/python}"
ODOO_CONF="${ODOO_CONF:-/etc/odoo/odoo.conf}"
ODOO_DB="${ODOO_DB:-company_ai}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CUSTOMER_NAME="${CUSTOMER_NAME:-}"
if [ -z "$CUSTOMER_NAME" ]; then
  echo "Usage: CUSTOMER_NAME=\"Acme Corp\" [BRAND_NAME=... BRAND_DOMAIN=... DOMAIN=... EMAIL=... EXCEL_PATH=...] ./15_customer_onboarding.sh"
  echo "(CUSTOMER_NAME is the only hard requirement - every other var gates an optional step, see below.)"
  exit 1
fi

step() { echo ""; echo "======================================================================"; echo "STEP: $1"; echo "======================================================================"; }
skip() { echo "[SKIPPED] $1"; }

echo "Onboarding for: ${CUSTOMER_NAME}"
echo "(this box's Odoo database: ${ODOO_DB})"

# ---------------------------------------------------------------------
# 1. Install (roadmap #57's "نصب") - only for a genuinely fresh box.
#    Skippable because most real onboardings run on a box that was
#    already provisioned separately from receiving this customer's
#    specific data - re-running full install against a live customer
#    database would be destructive.
# ---------------------------------------------------------------------
step "1/6 - Base install + module install"
if [ -n "${MAINTENANCE_MODE:-}" ]; then
  skip "01_setup_base.sh / 02_install_modules.sh (MAINTENANCE_MODE is set)"
else
  echo "Running 01_setup_base.sh and 02_install_modules.sh..."
  bash "${SCRIPT_DIR}/01_setup_base.sh"
  bash "${SCRIPT_DIR}/02_install_modules.sh"
fi

# ---------------------------------------------------------------------
# 2. Excel import (roadmap #57's "Excel import" + "Role ها")
# ---------------------------------------------------------------------
step "2/6 - Employee import from Excel/CSV (creates users + Role assignments (no credentials exported))"
if [ -z "${EXCEL_PATH:-}" ]; then
  skip "Excel onboarding (EXCEL_PATH not set - set it to the customer's real employee file)"
else
  if [ ! -f "$EXCEL_PATH" ]; then
    echo "ERROR: EXCEL_PATH=${EXCEL_PATH} does not exist. Aborting before touching the database."
    exit 1
  fi
  echo "Importing employees from ${EXCEL_PATH}..."
  # onboard_from_excel.py (roadmap #36/#37 rewrite) reads its input
  # path from the ONBOARD_FILE env var and, by default, stops for an
  # interactive "type IMPORT to confirm" prompt (its own real safety
  # feature - a Preview before anything is written). This orchestrator
  # runs non-interactively (stdin is the script itself, piped into
  # `odoo-bin shell` - there is no terminal for that prompt to read
  # from), so ONBOARD_YES=1 is required here to skip it automatically.
  # This means the orchestrator is trusting whatever EXCEL_PATH you
  # gave it WITHOUT a human re-reading the preview first - if you want
  # that manual review, run onboard_from_excel.py by itself once,
  # THEN rerun this script with MAINTENANCE_MODE=1 and no EXCEL_PATH.
  ONBOARD_FILE="$EXCEL_PATH" ONBOARD_YES=1 \
    "$ODOO_PYTHON" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$ODOO_DB" < "${SCRIPT_DIR}/onboarding/onboard_from_excel.py"
  echo "Import complete - a non-secret audit manifest may be produced only at the explicit ONBOARD_OUTPUT path."
fi

# ---------------------------------------------------------------------
# 3. Branding (roadmap #57's "تنظیم برندینگ", roadmap #55)
# ---------------------------------------------------------------------
step "3/6 - White-label branding"
if [ -z "${BRAND_NAME:-}" ] || [ -z "${BRAND_DOMAIN:-}" ]; then
  skip "14_configure_whitelabel.sh (BRAND_NAME and/or BRAND_DOMAIN not set)"
else
  BRAND_NAME="$BRAND_NAME" BRAND_DOMAIN="$BRAND_DOMAIN" bash "${SCRIPT_DIR}/14_configure_whitelabel.sh"
fi

# ---------------------------------------------------------------------
# 3b. TLS (also naturally belongs in "delivery", roadmap #53)
# ---------------------------------------------------------------------
step "3b/6 - TLS (mandatory for production delivery)"
if [ -z "${DOMAIN:-}" ] || [ -z "${EMAIL:-}" ]; then
  echo "ERROR: DOMAIN and EMAIL are required for production TLS." >&2; exit 1
else
  DOMAIN="$DOMAIN" EMAIL="$EMAIL" bash "${SCRIPT_DIR}/06_setup_tls.sh"
fi

# ---------------------------------------------------------------------
# 3c. Backups (must exist before real customer data accumulates)
# ---------------------------------------------------------------------
step "3c/6 - Daily backups"
if [ -n "${MAINTENANCE_MODE:-}" ]; then
  skip "07_setup_backups.sh (MAINTENANCE_MODE is set)"
else
  bash "${SCRIPT_DIR}/07_setup_backups.sh"
fi

# ---------------------------------------------------------------------
# 4. Acceptance testing (roadmap #57's "تست پذیرش", roadmap #49/#50)
#    All three suites - ORM-level, real-HTTP, and adversarial - as a
#    real go/no-go gate. Stops here (set -e) if any of them fail;
#    do NOT hand a box to a customer past this point on a failure.
# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# 3d. Frontend (this was MISSING before - a customer needs an actual
#    website, not just a backend + API. Same DOMAIN as TLS above.)
# ---------------------------------------------------------------------
step "3d/6 - Frontend build + deploy (roadmap #43-47)"
if [ -z "${DOMAIN:-}" ]; then
  echo "ERROR: DOMAIN is required for production frontend deployment." >&2; exit 1
else
  DOMAIN="$DOMAIN" bash "${SCRIPT_DIR}/17_setup_frontend.sh"
fi

# ---------------------------------------------------------------------
step "4/6 - Acceptance tests (05_acceptance_tests.py, ORM-level + security scenarios)"
"$ODOO_PYTHON" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$ODOO_DB" < "${SCRIPT_DIR}/05_acceptance_tests.py"

step "4b/6 - Evaluation suite (11_evaluation_suite.sh, real HTTP with per-role API keys)"
bash "${SCRIPT_DIR}/11_evaluation_suite.sh"

step "4c/6 - Adversarial security testing (13_security_testing.sh, attacker-perspective HTTP)"
if [ -n "${RUN_SLOW_SECURITY_TESTS:-}" ]; then
  bash "${SCRIPT_DIR}/13_security_testing.sh" --run-slow
else
  bash "${SCRIPT_DIR}/13_security_testing.sh"
  echo "(pass RUN_SLOW_SECURITY_TESTS=1 to also include the ~1-minute auth-flood scenario)"
fi

# ---------------------------------------------------------------------
# 5. Delivery checklist (roadmap #57's "تحویل", roadmap #54)
#    Final combined gate - re-checks TLS/backups/secrets/branding and
#    re-runs the two suites above itself, so this is the one command
#    you actually stand behind before leaving the customer's site.
# ---------------------------------------------------------------------
step "5/6 - Deployment checklist (final delivery gate)"
bash "${SCRIPT_DIR}/08_deployment_checklist.sh"

# ---------------------------------------------------------------------
step "6/6 - Done"
echo "Onboarding sequence for ${CUSTOMER_NAME} completed with no hard failures."
echo ""
echo "Still MANUAL, on purpose (no script can verify these for you):"
echo "  - Open the real running site and visually confirm branding (see"
echo "    14_configure_whitelabel.sh's own reminder above if that step ran)"
echo "  - Confirm demo user passwords were changed or those accounts disabled"
echo "  - Review LICENSING_NOTES.md with a real lawyer before signing anything (roadmap #56)"
echo "  - No credential file is produced or handed off"
