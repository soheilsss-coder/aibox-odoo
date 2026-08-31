#!/usr/bin/env bash
# Start the native service set only after a successful install/upgrade.
set -euo pipefail
: "${AI_GATEWAY_ENV:=production}"
: "${ODOO_SERVICE:=ai-odoo.service}"
: "${AI_EVENT_SERVICE:=ai-event-worker.service}"
: "${AI_RAG_SERVICE:=ai-rag-worker.service}"
: "${AI_VLLM_CHAT_SERVICE:=ai-vllm-chat.service}"
: "${AI_VLLM_EMBEDDING_SERVICE:=ai-vllm-embedding.service}"
: "${AI_VLLM_VISION_SERVICE:=ai-vllm-vision.service}"
: "${POSTGRES_SERVICE:=postgresql}"
: "${REDIS_SERVICE:=redis-server}"
: "${SYSTEMCTL:=systemctl}"

[[ "${AI_GATEWAY_ENV}" == production ]] || {
  echo "03_start_all.sh is a production start gate; set AI_GATEWAY_ENV=production" >&2
  exit 1
}
command -v "$SYSTEMCTL" >/dev/null || { echo "systemctl is required for native start" >&2; exit 1; }
if [[ "$SYSTEMCTL" == "systemctl" ]]; then
  systemctl enable --now postgresql
  systemctl enable --now redis-server
else
  "$SYSTEMCTL" enable --now "$POSTGRES_SERVICE"
  "$SYSTEMCTL" enable --now "$REDIS_SERVICE"
fi
"$SYSTEMCTL" is-active --quiet "$POSTGRES_SERVICE" || { echo "PostgreSQL failed health gate" >&2; exit 1; }
"$SYSTEMCTL" is-active --quiet "$REDIS_SERVICE" || { echo "Redis failed health gate" >&2; exit 1; }
for unit in "$AI_VLLM_CHAT_SERVICE" "$AI_VLLM_EMBEDDING_SERVICE" "$AI_VLLM_VISION_SERVICE" "$ODOO_SERVICE" "$AI_EVENT_SERVICE" "$AI_RAG_SERVICE"; do
  "$SYSTEMCTL" enable "$unit"
  "$SYSTEMCTL" restart "$unit"
done
for unit in "$AI_VLLM_CHAT_SERVICE" "$AI_VLLM_EMBEDDING_SERVICE" "$AI_VLLM_VISION_SERVICE" "$ODOO_SERVICE" "$AI_EVENT_SERVICE" "$AI_RAG_SERVICE"; do
  "$SYSTEMCTL" is-active --quiet "$unit" || { echo "Service failed health gate: $unit" >&2; exit 1; }
done
echo "NATIVE_SERVICES_HEALTHY: Odoo, event worker, and RAG worker are active."
