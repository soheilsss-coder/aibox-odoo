#!/usr/bin/env bash
# Install/upgrade the complete source inventory using Odoo's native module
# loader. No Docker, RPC shortcut, or blanket auto-install is used.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
: "${ODOO_HOME:=/opt/odoo}"
: "${ODOO_SOURCE:=${ODOO_HOME}/src/odoo}"
: "${ODOO_BIN:=${ODOO_SOURCE}/odoo-bin}"
: "${ODOO_PYTHON:=${ODOO_HOME}/venv/bin/python}"
: "${ODOO_CONF:=/etc/odoo/odoo.conf}"
: "${ODOO_DB:?Set ODOO_DB to the tenant database}"
: "${ODOO_USER:=odoo}"
: "${AI_MODULE_MODE:=install}"
: "${AI_ADDON_LIST:=$(find "$ROOT/custom_addons" -mindepth 1 -maxdepth 1 -type d -name 'ai_*' -printf '%f\n' | sort | paste -sd, -)}"
: "${ODOO_UPDATE_MODULES:=base}"

[[ -x "$ODOO_BIN" ]] || { echo "Missing native Odoo binary: $ODOO_BIN" >&2; exit 1; }
[[ -x "$ODOO_PYTHON" ]] || { echo "Missing Odoo virtualenv Python: $ODOO_PYTHON" >&2; exit 1; }
[[ -n "$AI_ADDON_LIST" ]] || { echo "No AI addons discovered" >&2; exit 1; }
case "$AI_MODULE_MODE" in install) action=-i;; upgrade) action=-u;; *) echo "AI_MODULE_MODE must be install or upgrade" >&2; exit 1;; esac

if [[ "$AI_MODULE_MODE" == install ]]; then
  modules="$ODOO_UPDATE_MODULES,$AI_ADDON_LIST"
else
  modules="$AI_ADDON_LIST"
fi
# -u/-i exits only after Odoo's own registry, manifest, XML, ACL and ORM
# validation. Stop mode ensures the caller decides when to expose services.
exec "$ODOO_PYTHON" "$ODOO_BIN" -c "$ODOO_CONF" -d "$ODOO_DB" \
  --stop-after-init "$action" "$modules" --no-http
