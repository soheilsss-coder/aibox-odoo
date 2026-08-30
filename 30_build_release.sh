#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
python3 "$ROOT/25_static_audit.py"
python3 "$ROOT/28_release_audit.py"
python3 "$ROOT/29_production_e2e.py"
python3 "$ROOT/50_v47_static_security_tests.py"
if command -v npm >/dev/null 2>&1; then (cd "$ROOT/frontend" && npm run build); fi
