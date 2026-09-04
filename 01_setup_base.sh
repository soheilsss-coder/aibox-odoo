#!/usr/bin/env bash
# Native base provisioning for Odoo + AI services. Docker is deliberately not
# used. This prepares pinned source/venv and installs, but does not start,
# services; 03_start_all.sh is the explicit start gate.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")" && pwd)"
: "${ODOO_HOME:=/opt/odoo}"
: "${ODOO_SOURCE:=${ODOO_HOME}/src/odoo}"
: "${ODOO_LLM_PATH:=/opt/odoo-llm}"
: "${ODOO_ADDONS_PATH:=/opt/odoo-custom-addons}"
: "${ODOO_CONF:=/etc/odoo/odoo.conf}"
: "${ODOO_USER:=odoo}"
: "${ODOO_GROUP:=${ODOO_USER}}"
: "${PYTHON_BIN:=python3}"
: "${ODOO_REPO:=https://github.com/odoo/odoo.git}"
: "${ODOO_LLM_REPO:?Set the odoo-llm repository URL together with its pinned commit}"
: "${ODOO_DB:=company_ai}"
: "${ODOO_DB_USER:=odoo}"
: "${ODOO_DATA_DIR:=/var/lib/odoo}"
: "${ODOO_LOG_DIR:=/var/log/odoo}"
: "${AI_SYSTEMD_DIR:=/etc/systemd/system}"
: "${AI_RUNTIME_WORKERS:=/opt/odoo-custom-addons/ai-runtime-workers}"
: "${ODOO_SERVICE:=ai-odoo.service}"
: "${AI_VLLM_CHAT_MODEL_PATH:=}"
: "${AI_VLLM_EMBEDDING_MODEL_PATH:=}"
: "${AI_VLLM_VISION_MODEL_PATH:=}"
: "${AI_RAG_INDEX_VERSION:=rag-v1}"
: "${AI_GATEWAY_ALLOWED_ORIGIN:=}"
: "${AI_GATEWAY_REDIS_URL:=}"
: "${AI_VLLM_MAX_MODEL_LEN:=32768}"
: "${AI_VLLM_MAX_NUM_SEQS:=32}"
: "${AI_VLLM_MAX_NUM_BATCHED_TOKENS:=8192}"
: "${AI_VLLM_GPU_MEMORY_UTILIZATION:=0.90}"
: "${PGVECTOR_PACKAGE:=postgresql-16-pgvector}"
: "${VLLM_VERSION:?Set an immutable VLLM_VERSION for native installation}"
: "${ODOO_COMMIT_SHA:?Set the immutable ODOO_COMMIT_SHA before native installation}"
: "${ODOO_LLM_COMMIT_SHA:?Set the immutable ODOO_LLM_COMMIT_SHA before native installation}"

if [[ "${AI_GATEWAY_ENV:-development}" == "production" ]]; then
  for v in PYTHON_RUNTIME_VERSION MODEL_REVISION_QWEN MODEL_REVISION_GLIMMER MODEL_REVISION_VISION MODEL_REVISION_EMBEDDING AI_VLLM_CHAT_MODEL_PATH AI_VLLM_EMBEDDING_MODEL_PATH AI_VLLM_VISION_MODEL_PATH AI_GATEWAY_ALLOWED_ORIGIN AI_GATEWAY_REDIS_URL; do
    [[ -n "${!v:-}" ]] || { echo "Missing immutable production variable: $v" >&2; exit 1; }
  done
fi

if [[ "${INSTALL_OS_DEPS:-0}" == "1" ]]; then
  [[ "${EUID}" -eq 0 ]] || { echo "INSTALL_OS_DEPS=1 requires root" >&2; exit 1; }
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git build-essential libpq-dev libxml2-dev libxslt1-dev libldap2-dev \
    libsasl2-dev libjpeg-dev libffi-dev libssl-dev postgresql postgresql-client \
    "$PGVECTOR_PACKAGE" redis-server redis-tools
fi

command -v "$PYTHON_BIN" >/dev/null || { echo "Python executable not found: $PYTHON_BIN" >&2; exit 1; }
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
if [[ -n "${PYTHON_RUNTIME_VERSION:-}" ]]; then
  actual="$($PYTHON_BIN -c 'import platform; print(platform.python_version())')"
  [[ "$actual" == "${PYTHON_RUNTIME_VERSION}"* ]] || {
    echo "Python runtime mismatch: expected ${PYTHON_RUNTIME_VERSION}, got ${actual}" >&2; exit 1;
  }
fi

as_root() {
  if [[ "$EUID" -eq 0 ]]; then "$@"; else sudo "$@"; fi
}

if ! id -u "$ODOO_USER" >/dev/null 2>&1; then
  [[ "$EUID" -eq 0 ]] || { echo "Create $ODOO_USER or run as root" >&2; exit 1; }
  useradd --system --home-dir "$ODOO_HOME" --shell /usr/sbin/nologin "$ODOO_USER"
fi
ODOO_GROUP="$(id -gn "$ODOO_USER")"
as_root install -d -m 0755 -o "$ODOO_USER" -g "$ODOO_GROUP" "$ODOO_HOME" "$ODOO_ADDONS_PATH" "$ODOO_DATA_DIR" "$ODOO_LOG_DIR" "$(dirname "$ODOO_CONF")"

checkout_pinned() {
  local path="$1" repo="$2" commit="$3"
  if [[ ! -d "$path/.git" ]]; then
    as_root git clone --no-checkout "$repo" "$path"
  fi
  as_root git -C "$path" fetch --force --depth 1 origin "$commit"
  as_root git -C "$path" checkout --detach "$commit"
  [[ "$(as_root git -C "$path" rev-parse HEAD)" == "$commit" ]] || {
    echo "Pinned checkout verification failed: $path" >&2; exit 1;
  }
}
checkout_pinned "$ODOO_SOURCE" "$ODOO_REPO" "$ODOO_COMMIT_SHA"
checkout_pinned "$ODOO_LLM_PATH" "$ODOO_LLM_REPO" "$ODOO_LLM_COMMIT_SHA"

VENV="${ODOO_HOME}/venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  as_root "$PYTHON_BIN" -m venv "$VENV"
fi
as_root "$VENV/bin/python" -m pip install --no-cache-dir -r "$ODOO_SOURCE/requirements.txt"
as_root "$VENV/bin/python" -m pip install --no-cache-dir "vllm==${VLLM_VERSION}"
as_root "$VENV/bin/python" -m pip install --no-cache-dir -r "$ROOT/requirements.lock"

# Stage only source payloads; no model weights, pip cache, or build cache enter
# the repository or the addons directory.
as_root find "$ODOO_ADDONS_PATH" -mindepth 1 -maxdepth 1 -type d -name 'ai_*' -exec rm -rf {} +
as_root find "$ODOO_ADDONS_PATH" -mindepth 1 -maxdepth 1 -type d -name 'company_ai_demo' -exec rm -rf {} +
find "$ROOT/custom_addons" -mindepth 1 -maxdepth 1 -type d -print0 | while IFS= read -r -d '' addon; do
  as_root cp -a "$addon" "$ODOO_ADDONS_PATH/"
done
as_root cp -f "$ROOT/requirements.lock" "$ODOO_ADDONS_PATH/requirements.lock"
as_root cp -f "$ROOT/DEPENDENCY_LOCK.md" "$ODOO_ADDONS_PATH/DEPENDENCY_LOCK.md"

if [[ ! -f "$ODOO_CONF" ]]; then
  : "${ODOO_ADMIN_PASSWORD:?Set ODOO_ADMIN_PASSWORD when creating a new Odoo config}"
  [[ "$ODOO_ADMIN_PASSWORD" != *$'\n'* ]] || { echo "ODOO_ADMIN_PASSWORD may not contain a newline" >&2; exit 1; }
  db_host="${DB_HOST:-False}"; db_port="${DB_PORT:-5432}"; db_password="${DB_PASSWORD:-}"
  [[ "$db_password" != *$'\n'* ]] || { echo "DB_PASSWORD may not contain a newline" >&2; exit 1; }
  as_root sh -c "cat > '$ODOO_CONF'" <<EOF
[options]
admin_passwd = ${ODOO_ADMIN_PASSWORD}
db_host = ${db_host}
db_port = ${db_port}
db_user = ${ODOO_DB_USER}
db_password = ${db_password}
db_name = ${ODOO_DB}
addons_path = ${ODOO_SOURCE}/addons,${ODOO_LLM_PATH},${ODOO_ADDONS_PATH}
data_dir = ${ODOO_DATA_DIR}
logfile = ${ODOO_LOG_DIR}/odoo.log
proxy_mode = True
list_db = False
http_interface = 127.0.0.1
workers = ${ODOO_WORKERS:-4}
max_cron_threads = ${ODOO_MAX_CRON_THREADS:-1}
limit_time_cpu = ${ODOO_LIMIT_TIME_CPU:-120}
limit_time_real = ${ODOO_LIMIT_TIME_REAL:-240}
EOF
  as_root chmod 0600 "$ODOO_CONF"; as_root chown "$ODOO_USER:$ODOO_GROUP" "$ODOO_CONF"
fi

# Systemd receives only non-secret location settings from this environment file.
for model_path in "$AI_VLLM_CHAT_MODEL_PATH" "$AI_VLLM_EMBEDDING_MODEL_PATH" "$AI_VLLM_VISION_MODEL_PATH"; do
  [[ "$model_path" != *$'\n'* ]] || { echo "Model path contains a newline" >&2; exit 1; }
done
[[ "${AI_VLLM_SPECULATIVE_CONFIG:-}" != *$'\n'* ]] || { echo "Speculative config contains a newline" >&2; exit 1; }
[[ "$AI_GATEWAY_ALLOWED_ORIGIN" != *$'\n'* && "$AI_GATEWAY_REDIS_URL" != *$'\n'* && "$AI_RAG_INDEX_VERSION" != *$'\n'* ]] || { echo "Runtime configuration contains a newline" >&2; exit 1; }
as_root install -d -m 0755 -o "$ODOO_USER" -g "$ODOO_GROUP" "$AI_RUNTIME_WORKERS" /etc/ai-box /var/cache/ai-box
as_root sh -c "cat > /etc/ai-box/runtime.env" <<EOF
ODOO_BIN=${ODOO_SOURCE}/odoo-bin
ODOO_CONF=${ODOO_CONF}
ODOO_DB=${ODOO_DB}
AI_GATEWAY_ENV=${AI_GATEWAY_ENV:-development}
AI_GATEWAY_ALLOWED_ORIGIN=${AI_GATEWAY_ALLOWED_ORIGIN}
AI_GATEWAY_REDIS_URL=${AI_GATEWAY_REDIS_URL}
AI_RAG_INDEX_VERSION=${AI_RAG_INDEX_VERSION}
AI_CHAT_GLOBAL_CONCURRENCY=${AI_CHAT_GLOBAL_CONCURRENCY:-32}
AI_CHAT_LEASE_SECONDS=${AI_CHAT_LEASE_SECONDS:-240}
AI_CHAT_GLOBAL_WAIT_SECONDS=${AI_CHAT_GLOBAL_WAIT_SECONDS:-240}
AI_CHAT_QUEUE_CONCURRENCY=${AI_CHAT_QUEUE_CONCURRENCY:-8}
AI_CHAT_QUEUE_MAX_WAITERS=${AI_CHAT_QUEUE_MAX_WAITERS:-128}
AI_CHAT_QUEUE_TIMEOUT=${AI_CHAT_QUEUE_TIMEOUT:-240}
EOF
as_root chmod 0600 /etc/ai-box/runtime.env; as_root chown root:root /etc/ai-box/runtime.env
write_vllm_env() {
  local file="$1" model_path="$2" port="$3" served_model="$4" runner="$5" max_len="$6" max_seqs="$7" max_batch="$8"
  cat <<EOF | as_root tee "$file" >/dev/null
AI_VLLM_BIN=${VENV}/bin/vllm
AI_VLLM_MODEL_PATH=${model_path}
AI_VLLM_HOST=127.0.0.1
AI_VLLM_PORT=${port}
AI_VLLM_SERVED_MODEL=${served_model}
AI_VLLM_RUNNER=${runner}
AI_VLLM_MAX_MODEL_LEN=${max_len}
AI_VLLM_MAX_NUM_SEQS=${max_seqs}
AI_VLLM_MAX_NUM_BATCHED_TOKENS=${max_batch}
AI_VLLM_GPU_MEMORY_UTILIZATION=${AI_VLLM_GPU_MEMORY_UTILIZATION}
AI_VLLM_ENABLE_PREFIX_CACHING=1
AI_VLLM_ENABLE_CHUNKED_PREFILL=1
AI_VLLM_TRUST_REMOTE_CODE=${AI_VLLM_TRUST_REMOTE_CODE:-0}
AI_VLLM_SPECULATIVE_CONFIG=${AI_VLLM_SPECULATIVE_CONFIG:-}
EOF
  as_root chmod 0600 "$file"; as_root chown root:root "$file"
}
write_vllm_env /etc/ai-box/vllm-chat.env "$AI_VLLM_CHAT_MODEL_PATH" 8000 local-model generate "$AI_VLLM_MAX_MODEL_LEN" "$AI_VLLM_MAX_NUM_SEQS" "$AI_VLLM_MAX_NUM_BATCHED_TOKENS"
write_vllm_env /etc/ai-box/vllm-embedding.env "$AI_VLLM_EMBEDDING_MODEL_PATH" 8002 embedding-model pooling 8192 64 4096
write_vllm_env /etc/ai-box/vllm-vision.env "$AI_VLLM_VISION_MODEL_PATH" 8001 vision-model generate "$AI_VLLM_MAX_MODEL_LEN" "$AI_VLLM_MAX_NUM_SEQS" "$AI_VLLM_MAX_NUM_BATCHED_TOKENS"
as_root cp -f "$ROOT/runtime_workers/event_bus_worker.py" "$ROOT/runtime_workers/rag_worker.py" "$AI_RUNTIME_WORKERS/"
as_root cp -f "$ROOT/runtime_workers/run_event_worker.sh" "$ROOT/runtime_workers/run_rag_worker.sh" "$ROOT/runtime_workers/run_vllm_server.sh" "$AI_RUNTIME_WORKERS/"
as_root chmod 0755 "$AI_RUNTIME_WORKERS"/*.sh
for unit in ai-odoo.service ai-event-worker.service ai-rag-worker.service ai-vllm-chat.service ai-vllm-embedding.service ai-vllm-vision.service; do
  src="$ROOT/systemd/$unit"
  [[ -f "$src" ]] || { echo "Missing systemd unit: $src" >&2; exit 1; }
  as_root sed -e "s#^User=.*#User=${ODOO_USER}#" \
    -e "s#^Group=.*#Group=${ODOO_GROUP}#" \
    -e "s#^ExecStart=/opt/odoo/odoo-bin#ExecStart=${ODOO_SOURCE}/odoo-bin#" \
    -e "s#^ExecStart=/opt/odoo/src/odoo/odoo-bin#ExecStart=${ODOO_SOURCE}/odoo-bin#" \
    -e "s#^ExecStart=/opt/odoo-custom-addons/ai-runtime-workers#ExecStart=${AI_RUNTIME_WORKERS}#" \
    "$src" | as_root tee "${AI_SYSTEMD_DIR}/${unit}" >/dev/null
  as_root chmod 0644 "${AI_SYSTEMD_DIR}/${unit}"
done
if command -v systemctl >/dev/null 2>&1; then as_root systemctl daemon-reload; fi
echo "BASE_READY: pinned native source and Odoo virtualenv prepared; services remain stopped."
