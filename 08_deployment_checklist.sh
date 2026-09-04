#!/usr/bin/env bash
# Final native delivery gate. A green result means the listed host checks
# passed; it is not a production certification and cannot replace browser,
# security, restore and load evidence.
set -euo pipefail

: "${DOMAIN:?Set DOMAIN to the real customer hostname}"
: "${ODOO_DB:=company_ai}"
: "${ODOO_CONF:=/etc/odoo/odoo.conf}"
: "${ODOO_DATA_DIR:=/var/lib/odoo}"
: "${BACKUP_DIR:=/var/backups/ai-box}"
: "${AI_MODEL_CHECKSUM_MANIFEST:?Set AI_MODEL_CHECKSUM_MANIFEST to the verified model checksum file}"
: "${BACKUP_RESTORE_EVIDENCE:?Set BACKUP_RESTORE_EVIDENCE to a dated, operator-signed restore test record}"

failures=0
check() {
  local label="$1"; shift
  if "$@"; then echo "PASS  $label"; else echo "FAIL  $label" >&2; failures=$((failures + 1)); fi
}

[[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || { echo "Invalid DOMAIN" >&2; exit 1; }
[[ "$DOMAIN" != *..* ]] || { echo "Invalid DOMAIN" >&2; exit 1; }
[[ -s "$ODOO_CONF" ]] || { echo "Missing Odoo config: $ODOO_CONF" >&2; exit 1; }
[[ -s "$AI_MODEL_CHECKSUM_MANIFEST" ]] || { echo "Missing model checksum manifest" >&2; exit 1; }
[[ -s "$BACKUP_RESTORE_EVIDENCE" ]] || { echo "Missing backup restore evidence" >&2; exit 1; }

check "native service manager available" command -v systemctl
check "nginx configuration" nginx -t
check "PostgreSQL active" systemctl is-active --quiet postgresql
check "Redis active" systemctl is-active --quiet redis-server
for unit in ai-vllm-chat.service ai-vllm-embedding.service ai-vllm-vision.service ai-odoo.service ai-event-worker.service ai-rag-worker.service; do
  check "$unit active" systemctl is-active --quiet "$unit"
done
check "backup timer active" systemctl is-active --quiet ai-box-backup.timer
check "backup restore evidence is recent" bash -c 'test "$(find "$1" -maxdepth 0 -mtime -31 -type f -print -quit)" = "$1"' _ "$BACKUP_RESTORE_EVIDENCE"
check "model checksums" sha256sum --check --status "$AI_MODEL_CHECKSUM_MANIFEST"
check "frontend deployed" test -s "/var/www/${DOMAIN}/index.html"
check "certificate valid" openssl x509 -in "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" -noout -checkend 86400
check "public health endpoint" curl --fail --silent --show-error --max-time 15 "https://${DOMAIN}/api/health" >/dev/null
check "pgvector enabled" bash -c 'runuser -u postgres -- psql -Atqc "SELECT 1 FROM pg_extension WHERE extname = '\''vector'\''" "$1" | grep -qx 1' _ "$ODOO_DB"

# Static checks are deliberately reported separately from host/runtime checks.
if python3 FINAL_PRODUCTION_GATE.py; then
  echo "PASS  static production gate"
else
  echo "FAIL  static production gate" >&2
  failures=$((failures + 1))
fi

if (( failures )); then
  echo "DEPLOYMENT_BLOCKED: ${failures} checklist item(s) failed; do not hand off this installation." >&2
  exit 1
fi
echo "HOST_CHECKS_PASS: browser regression, adversarial security, concurrency/load, and business acceptance evidence remain required."
