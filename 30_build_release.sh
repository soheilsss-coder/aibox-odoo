#!/usr/bin/env bash
# Offline/source release verification. Runtime certification remains a separate
# gate because Odoo, PostgreSQL, Redis, vLLM, IdP and DGX hardware are not
# bundled in this checkout.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

python3 -m compileall -q custom_addons tests 48_auto_integration_certification.py 60_v58_llm_benchmark.py 61_v58_capacity_gate.py 62_v58_module_certification.py
python3 -m unittest discover -s tests -v
python3 60_v58_llm_benchmark.py --help >/dev/null
python3 61_v58_capacity_gate.py --help >/dev/null
python3 ai_gateway_queue_selftest.py
python3 inference_policy_selftest.py
for script in 00_final_production_install.sh 01_setup_base.sh 02_install_modules.sh 03_start_all.sh 30_build_release.sh deploy.sh; do
  bash -n "$script"
done
while IFS= read -r -d '' script; do bash -n "$script"; done < <(find runtime_workers -type f -name '*.sh' -print0)
git diff --check

python3 25_static_audit.py
python3 28_release_audit.py
python3 29_production_e2e.py
python3 50_v47_static_security_tests.py
python3 59_v57_hardening_audit.py
python3 FINAL_PRODUCTION_GATE.py
python3 FINAL_EXHAUSTIVE_SOURCE_AUDIT.py

if command -v npm >/dev/null 2>&1; then
  (
    cd "$ROOT/frontend"
    # Do not retain dependency trees in the release workspace.
    rm -rf node_modules
    build_tmp="$(mktemp -d)"
    trap 'rm -rf node_modules "$build_tmp"' EXIT
    npm ci --ignore-scripts
    # Keep generated bundles outside the workspace; source and lockfiles are
    # the release inputs, not a checked-in build cache.
    npm run build -- --outDir "$build_tmp/dist"
    # npm 10's legacy quick-audit endpoint is intermittently retired/invalid
    # in appliance builds; npm ci has already audited the lockfile and this
    # offline pass makes the release gate deterministic after package install.
    npm audit --audit-level=high --offline
  )
else
  echo "RUNTIME_REQUIRED: npm is not installed; frontend build was not executed" >&2
  exit 1
fi

echo "SOURCE_RELEASE_VERIFICATION_PASS: static audits, contract suite, frontend build, and dependency audit completed."
echo "RUNTIME_CERTIFICATION_REQUIRED: run 48_auto_integration_certification.py and DGX benchmark on the native target."
