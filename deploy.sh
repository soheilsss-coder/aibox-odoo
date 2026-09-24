#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
: "${ODOO_ADDONS_PATH:=/opt/odoo-custom-addons}"
: "${ODOO_CONF:=/etc/odoo/odoo.conf}"
: "${AI_GATEWAY_ALLOWED_ORIGIN:?Set AI_GATEWAY_ALLOWED_ORIGIN to the exact HTTPS frontend origin before production install}"
case "$AI_GATEWAY_ALLOWED_ORIGIN" in https://*) ;; *) echo "AI_GATEWAY_ALLOWED_ORIGIN must be HTTPS" >&2; exit 1;; esac
mkdir -p "$ODOO_ADDONS_PATH"
find "$ROOT/custom_addons" -mindepth 1 -maxdepth 1 -type d -print0 | while IFS= read -r -d '' d; do cp -a "$d" "$ODOO_ADDONS_PATH/"; done
test -s "$ROOT/requirements.lock"
test -s "$ROOT/DEPENDENCY_LOCK.md"
# requirements.lock is the single source of truth for app deps - must land
# next to the custom addons so 01_setup_base.sh step [7/9] installs from it.
cp -a "$ROOT/requirements.lock" "$ODOO_ADDONS_PATH/requirements.lock"
cp -a "$ROOT/DEPENDENCY_LOCK.md" "$ODOO_ADDONS_PATH/DEPENDENCY_LOCK.md"
python3 "$ROOT/FINAL_PRODUCTION_GATE.py"
if [[ "${AI_GATEWAY_ENV:-development}" == "production" ]]; then
  for v in ODOO_COMMIT_SHA ODOO_LLM_COMMIT_SHA VLLM_IMAGE_DIGEST PYTHON_RUNTIME_VERSION NODE_RUNTIME_VERSION MODEL_REVISION_QWEN MODEL_REVISION_GLIMMER MODEL_REVISION_VISION MODEL_REVISION_EMBEDDING PGVECTOR_IMAGE_DIGEST; do
    [[ -n "${!v:-}" ]] || { echo "Missing immutable production artifact variable: $v" >&2; exit 1; }
  done
fi
echo "Code payload and static gates are ready. Runtime certification starts after the real Odoo/PostgreSQL/Redis/vLLM stack is started."
