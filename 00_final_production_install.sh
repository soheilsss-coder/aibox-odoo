#!/usr/bin/env bash
# Single native release entrypoint. It never invokes Docker and fails closed
# before touching production when immutable artifact variables are missing.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
: "${AI_GATEWAY_ENV:=production}"
: "${AI_MODULE_MODE:=install}"
export AI_GATEWAY_ENV AI_MODULE_MODE
case "$AI_MODULE_MODE" in install|upgrade) ;; *) echo "AI_MODULE_MODE must be install or upgrade" >&2; exit 1;; esac
"$ROOT/01_setup_base.sh"
"$ROOT/deploy.sh"
"$ROOT/02_install_modules.sh"
"$ROOT/03_start_all.sh"
echo "NATIVE_INSTALL_COMPLETE: run runtime certification before making capacity or production claims."
