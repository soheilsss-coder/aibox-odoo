#!/usr/bin/env bash
# AIBOX single-file installer/launcher.
#
# One-line install/update example:
#   curl -fsSL https://raw.githubusercontent.com/soheilsss-coder/aibox-odoo/arena/01a07ab5-aibox-odoo/install_aibox_onefile.sh | bash -s -- install
#
# Foreground launch examples (run in separate visible terminals):
#   ./install_aibox_onefile.sh serve-vllm
#   ./install_aibox_onefile.sh serve-odoo https://your-public-origin.example
#   ./install_aibox_onefile.sh serve-frontend
#   ./install_aibox_onefile.sh serve-cloudflare
#
# Safety defaults:
# - Uses only $HOME/aibox-workspace unless AIBOX_WORKSPACE is set.
# - Does not reset or drop an existing database unless AIBOX_RESET_DB=1.
# - Uses Docker only for this user's PostgreSQL/pgvector and Redis.
# - Runs long-lived services in the foreground so logs stay visible.
set -Eeuo pipefail

CMD="${1:-install}"
shift || true

AIBOX_REPO="${AIBOX_REPO:-https://github.com/soheilsss-coder/aibox-odoo.git}"
AIBOX_BRANCH="${AIBOX_BRANCH:-arena/01a07ab5-aibox-odoo}"
WS="${AIBOX_WORKSPACE:-$HOME/aibox-workspace}"
APP="$WS/app/aibox-odoo"
SRC="$WS/src"
ODOO_SRC="${ODOO_SRC:-$SRC/odoo}"
ODOO_LLM_SRC="${ODOO_LLM_SRC:-$SRC/odoo-llm}"
VENV="${VENV:-$WS/venv}"
VLLM_VENV="${VLLM_VENV:-$WS/vllm-venv}"
LOG_DIR="${LOG_DIR:-$WS/logs}"
ODOO_CONF="${ODOO_CONF:-$WS/odoo.conf}"
DB_NAME="${DB_NAME:-aibox_${USER}_dev}"
DB_USER="${DB_USER:-aibox_${USER}}"
DB_PASSWORD="${DB_PASSWORD:-}"
PG_PORT="${PG_PORT:-15433}"
REDIS_PORT="${REDIS_PORT:-16379}"
ODOO_PORT="${ODOO_PORT:-18069}"
FRONTEND_PORT="${FRONTEND_PORT:-15173}"
AI_VLLM_CHAT_MODEL_PATH="${AI_VLLM_CHAT_MODEL_PATH:-$WS/models/qwen3-30b-a3b-instruct-2507-awq}"
AI_VLLM_CHAT_API_BASE="${AI_VLLM_CHAT_API_BASE:-http://127.0.0.1:8000/v1}"
AI_VLLM_GPU_MEMORY_UTILIZATION="${AI_VLLM_GPU_MEMORY_UTILIZATION:-0.55}"
AI_VLLM_MAX_MODEL_LEN="${AI_VLLM_MAX_MODEL_LEN:-32768}"
AI_VLLM_MAX_NUM_SEQS="${AI_VLLM_MAX_NUM_SEQS:-4}"
AI_VLLM_MAX_NUM_BATCHED_TOKENS="${AI_VLLM_MAX_NUM_BATCHED_TOKENS:-2048}"
ODOO_REPO="${ODOO_REPO:-https://github.com/odoo/odoo.git}"
ODOO_BRANCH="${ODOO_BRANCH:-18.0}"
ODOO_LLM_REPO="${ODOO_LLM_REPO:-https://github.com/apexive/odoo-llm.git}"
ODOO_LLM_BRANCH="${ODOO_LLM_BRANCH:-18.0}"

CUSTOM_MODULES="company_ai_demo,ai_gateway,ai_business_tools,ai_control_plane,ai_integration,ai_rag,ai_customer_plane,ai_semantic_api,ai_correspondence,ai_document_intelligence,ai_workflow,ai_collaboration,ai_production,ai_experience,ai_telegram_bridge,ai_debrand"
BASE_MODULES="hr,hr_attendance,hr_holidays,project,mail,stock,account,mrp,sales_team,sale_management,purchase,llm,llm_tool,llm_openai,llm_thread,llm_assistant,llm_knowledge"
AIBOX_MODULES="${AIBOX_MODULES:-$BASE_MODULES,$CUSTOM_MODULES}"

log() { printf '\n===== %s =====\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

write_env_var() {
  local key="$1" value="$2"
  python3 - "$WS/aibox-env.sh" "$key" "$value" <<'PY'
import os, re, shlex, sys
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path, encoding='utf-8').read() if os.path.exists(path) else ''
line = 'export %s=%s' % (key, shlex.quote(value))
pat = re.compile(r'^export %s=.*$' % re.escape(key), re.M)
text = pat.sub(line, text) if pat.search(text) else text + ('' if text.endswith('\n') or not text else '\n') + line + '\n'
open(path, 'w', encoding='utf-8').write(text)
PY
}

load_env_if_exists() {
  if [ -f "$WS/aibox-env.sh" ]; then
    # shellcheck disable=SC1091
    source "$WS/aibox-env.sh"
  fi
}

init_workspace() {
  mkdir -p "$WS" "$APP" "$SRC" "$LOG_DIR" "$WS/models" "$WS/bin"
  chmod 700 "$WS"
  if [ -z "${DB_PASSWORD:-}" ]; then
    if [ -f "$WS/.db_password" ]; then
      DB_PASSWORD="$(cat "$WS/.db_password")"
    else
      DB_PASSWORD="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"
      umask 077; printf '%s\n' "$DB_PASSWORD" > "$WS/.db_password"
    fi
  fi
  local mem_key="${AI_MEMORY_ENCRYPTION_KEY:-}"
  if [ -z "$mem_key" ]; then
    mem_key="$(python3 - <<'PY'
import base64, os
print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY
)"
  fi
  : > "$WS/aibox-env.sh"
  write_env_var WS "$WS"
  write_env_var APP "$APP"
  write_env_var ODOO_SRC "$ODOO_SRC"
  write_env_var ODOO_LLM_SRC "$ODOO_LLM_SRC"
  write_env_var VENV "$VENV"
  write_env_var VLLM_VENV "$VLLM_VENV"
  write_env_var LOG_DIR "$LOG_DIR"
  write_env_var ODOO_CONF "$ODOO_CONF"
  write_env_var DB_NAME "$DB_NAME"
  write_env_var DB_USER "$DB_USER"
  write_env_var DB_PASSWORD "$DB_PASSWORD"
  write_env_var PG_PORT "$PG_PORT"
  write_env_var REDIS_PORT "$REDIS_PORT"
  write_env_var ODOO_PORT "$ODOO_PORT"
  write_env_var FRONTEND_PORT "$FRONTEND_PORT"
  write_env_var AI_MEMORY_ENCRYPTION_KEY "$mem_key"
  write_env_var AI_VLLM_CHAT_MODEL_PATH "$AI_VLLM_CHAT_MODEL_PATH"
  write_env_var AI_VLLM_CHAT_API_BASE "$AI_VLLM_CHAT_API_BASE"
  write_env_var AI_VLLM_GPU_MEMORY_UTILIZATION "$AI_VLLM_GPU_MEMORY_UTILIZATION"
  chmod 600 "$WS/aibox-env.sh"
}

ensure_system_packages() {
  need_cmd git
  need_cmd python3
  need_cmd docker
  if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
    die "docker compose is required"
  fi
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    if [ "${AIBOX_INSTALL_SYSTEM_PACKAGES:-0}" = "1" ] && command -v sudo >/dev/null 2>&1; then
      log "INSTALL_NODEJS"
      curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
      sudo apt-get install -y nodejs
    else
      die "node/npm not found. Install Node 22+, or rerun with AIBOX_INSTALL_SYSTEM_PACKAGES=1 if sudo is allowed."
    fi
  fi
}

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    docker compose --env-file "$WS/docker-compose.env" -f "$WS/docker-compose.aibox.yml" "$@"
  else
    docker-compose --env-file "$WS/docker-compose.env" -f "$WS/docker-compose.aibox.yml" "$@"
  fi
}

write_compose() {
  cat > "$WS/docker-compose.env" <<EOF
POSTGRES_DB=$DB_NAME
POSTGRES_USER=$DB_USER
POSTGRES_PASSWORD=$DB_PASSWORD
PG_PORT=$PG_PORT
REDIS_PORT=$REDIS_PORT
EOF
  cat > "$WS/docker-compose.aibox.yml" <<EOF
services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: aibox_${USER}_postgres
    environment:
      POSTGRES_DB: \${POSTGRES_DB}
      POSTGRES_USER: \${POSTGRES_USER}
      POSTGRES_PASSWORD: \${POSTGRES_PASSWORD}
    ports:
      - "127.0.0.1:\${PG_PORT}:5432"
    volumes:
      - aibox_${USER}_pgdata:/var/lib/postgresql/data
    restart: unless-stopped
  redis:
    image: redis:7-alpine
    container_name: aibox_${USER}_redis
    command: ["redis-server", "--appendonly", "yes"]
    ports:
      - "127.0.0.1:\${REDIS_PORT}:6379"
    volumes:
      - aibox_${USER}_redisdata:/data
    restart: unless-stopped
volumes:
  aibox_${USER}_pgdata:
  aibox_${USER}_redisdata:
EOF
}

sync_repo() {
  log "SYNC_AIBOX_SOURCE"
  if [ -d "$APP/.git" ]; then
    git -C "$APP" fetch origin "$AIBOX_BRANCH"
    git -C "$APP" checkout "$AIBOX_BRANCH" 2>/dev/null || git -C "$APP" checkout -B "$AIBOX_BRANCH" "origin/$AIBOX_BRANCH"
    git -C "$APP" pull --ff-only origin "$AIBOX_BRANCH"
  else
    rm -rf "$APP"
    git clone --branch "$AIBOX_BRANCH" "$AIBOX_REPO" "$APP"
  fi
}

sync_odoo_sources() {
  log "SYNC_ODOO_SOURCE"
  if [ -d "$ODOO_SRC/.git" ]; then
    git -C "$ODOO_SRC" fetch origin "$ODOO_BRANCH"
    git -C "$ODOO_SRC" checkout "$ODOO_BRANCH" 2>/dev/null || git -C "$ODOO_SRC" checkout -B "$ODOO_BRANCH" "origin/$ODOO_BRANCH"
    git -C "$ODOO_SRC" pull --ff-only origin "$ODOO_BRANCH" || true
  else
    git clone --depth 1 --branch "$ODOO_BRANCH" "$ODOO_REPO" "$ODOO_SRC"
  fi
  log "SYNC_ODOO_LLM_SOURCE"
  if [ -d "$ODOO_LLM_SRC/.git" ]; then
    git -C "$ODOO_LLM_SRC" fetch origin "$ODOO_LLM_BRANCH"
    git -C "$ODOO_LLM_SRC" checkout "$ODOO_LLM_BRANCH" 2>/dev/null || git -C "$ODOO_LLM_SRC" checkout -B "$ODOO_LLM_BRANCH" "origin/$ODOO_LLM_BRANCH"
    git -C "$ODOO_LLM_SRC" pull --ff-only origin "$ODOO_LLM_BRANCH" || true
  else
    git clone --depth 1 --branch "$ODOO_LLM_BRANCH" "$ODOO_LLM_REPO" "$ODOO_LLM_SRC"
  fi
}

install_python_deps() {
  log "PYTHON_VENV"
  [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install -U pip setuptools wheel
  if [ -f "$ODOO_SRC/requirements.txt" ]; then
    "$VENV/bin/python" -m pip install -r "$ODOO_SRC/requirements.txt"
  fi
  if [ -f "$ODOO_LLM_SRC/requirements.txt" ]; then
    "$VENV/bin/python" -m pip install -r "$ODOO_LLM_SRC/requirements.txt"
  fi
  "$VENV/bin/python" -m pip install -r "$APP/requirements.lock"
}

install_frontend_deps() {
  log "FRONTEND_DEPS"
  (cd "$APP/frontend" && npm install --no-audit --no-fund && npm run build)
}

write_odoo_conf() {
  local addons="$ODOO_SRC/odoo/addons,$WS/odoo-data/addons/18.0,$ODOO_SRC/addons,$ODOO_LLM_SRC,$APP/custom_addons"
  mkdir -p "$WS/odoo-data/addons/18.0" "$WS/odoo-data/filestore" "$WS/odoo-sessions"
  cat > "$ODOO_CONF" <<EOF
[options]
addons_path = $addons
data_dir = $WS/odoo-data
http_interface = 127.0.0.1
http_port = $ODOO_PORT
proxy_mode = True
db_host = 127.0.0.1
db_port = $PG_PORT
db_user = $DB_USER
db_password = $DB_PASSWORD
dbfilter = ^$DB_NAME$
list_db = False
workers = 0
max_cron_threads = 1
log_level = info
EOF
  chmod 600 "$ODOO_CONF"
}

db_has_odoo_schema() {
  "$VENV/bin/python" - <<'PY'
import os, sys, psycopg2
try:
    conn = psycopg2.connect(
        host='127.0.0.1', port=os.environ['PG_PORT'], dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'], connect_timeout=3,
    )
    cur = conn.cursor()
    cur.execute("SELECT to_regclass('public.ir_module_module') IS NOT NULL")
    ok = bool(cur.fetchone()[0])
    conn.close()
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
PY
}

install_or_update_modules() {
  log "ODOO_MODULES"
  export AI_GATEWAY_ENV="${AI_GATEWAY_ENV:-production}"
  export AI_GATEWAY_ALLOWED_ORIGIN="${AI_GATEWAY_ALLOWED_ORIGIN:-https://example.invalid}"
  export AI_GATEWAY_COOKIE_SECURE="${AI_GATEWAY_COOKIE_SECURE:-1}"
  export AI_GATEWAY_COOKIE_SAMESITE="${AI_GATEWAY_COOKIE_SAMESITE:-None}"
  export AI_GATEWAY_REDIS_URL="redis://127.0.0.1:${REDIS_PORT}/0"
  export AI_MEMORY_ENCRYPTION_KEY
  export AI_VLLM_CHAT_API_BASE
  export PYTHONWARNINGS="ignore:.*SwigPyPacked.*:DeprecationWarning,ignore:.*SwigPyObject.*:DeprecationWarning,ignore:.*swigvarlink.*:DeprecationWarning"
  if [ "${AIBOX_RESET_DB:-0}" = "1" ]; then
    warn "AIBOX_RESET_DB=1 set; dropping only database $DB_NAME inside this user's compose postgres"
    compose_cmd exec -T postgres dropdb -U "$DB_USER" --if-exists "$DB_NAME"
    compose_cmd exec -T postgres createdb -U "$DB_USER" "$DB_NAME"
  fi
  if db_has_odoo_schema; then
    "$VENV/bin/python" "$ODOO_SRC/odoo-bin" -c "$ODOO_CONF" -d "$DB_NAME" -u "$CUSTOM_MODULES" --stop-after-init
  else
    "$VENV/bin/python" "$ODOO_SRC/odoo-bin" -c "$ODOO_CONF" -d "$DB_NAME" -i "$AIBOX_MODULES" --stop-after-init
  fi
}

cmd_install() {
  init_workspace
  load_env_if_exists
  ensure_system_packages
  write_compose
  log "DB_REDIS_UP"
  compose_cmd up -d
  sync_repo
  sync_odoo_sources
  install_python_deps
  install_frontend_deps
  write_odoo_conf
  install_or_update_modules
  log "INSTALL_DONE"
  cat <<EOF
Workspace: $WS
Env file:  $WS/aibox-env.sh
Odoo:      http://127.0.0.1:$ODOO_PORT
Frontend:  http://127.0.0.1:$FRONTEND_PORT

Start services in visible terminals:
  $APP/install_aibox_onefile.sh serve-vllm
  $APP/install_aibox_onefile.sh serve-odoo https://your-public-origin
  $APP/install_aibox_onefile.sh serve-frontend
  $APP/install_aibox_onefile.sh serve-cloudflare
EOF
}

cmd_serve_vllm() {
  load_env_if_exists
  mkdir -p "$VLLM_VENV" "$WS/models"
  if [ ! -x "$VLLM_VENV/bin/vllm" ]; then
    log "INSTALL_VLLM"
    python3 -m venv "$VLLM_VENV"
    "$VLLM_VENV/bin/python" -m pip install -U pip setuptools wheel
    "$VLLM_VENV/bin/python" -m pip install -U vllm "huggingface_hub[cli]" ninja
  fi
  export PATH="$VLLM_VENV/bin:$PATH"
  command -v ninja >/dev/null 2>&1 || die "ninja is not in PATH; expected $VLLM_VENV/bin/ninja"
  [ -f "$AI_VLLM_CHAT_MODEL_PATH/config.json" ] || die "model config.json not found: $AI_VLLM_CHAT_MODEL_PATH"
  log "SERVE_VLLM_FOREGROUND"
  exec "$VLLM_VENV/bin/vllm" serve "$AI_VLLM_CHAT_MODEL_PATH" \
    --host 127.0.0.1 \
    --port 8000 \
    --served-model-name local-model \
    --max-model-len "$AI_VLLM_MAX_MODEL_LEN" \
    --max-num-seqs "$AI_VLLM_MAX_NUM_SEQS" \
    --max-num-batched-tokens "$AI_VLLM_MAX_NUM_BATCHED_TOKENS" \
    --gpu-memory-utilization "$AI_VLLM_GPU_MEMORY_UTILIZATION"
}

cmd_serve_odoo() {
  load_env_if_exists
  local origin="${1:-${AI_GATEWAY_ALLOWED_ORIGIN:-http://localhost:15173}}"
  export AI_GATEWAY_ENV="production"
  export AI_GATEWAY_ALLOWED_ORIGIN="$origin"
  export AI_GATEWAY_COOKIE_SECURE="1"
  export AI_GATEWAY_COOKIE_SAMESITE="None"
  export AI_GATEWAY_REDIS_URL="redis://127.0.0.1:${REDIS_PORT}/0"
  export AI_MEMORY_ENCRYPTION_KEY
  export AI_VLLM_CHAT_API_BASE="http://127.0.0.1:8000/v1"
  export PYTHONWARNINGS="ignore:.*SwigPyPacked.*:DeprecationWarning,ignore:.*SwigPyObject.*:DeprecationWarning,ignore:.*swigvarlink.*:DeprecationWarning"
  log "SERVE_ODOO_FOREGROUND origin=$origin"
  exec "$VENV/bin/python" "$ODOO_SRC/odoo-bin" -c "$ODOO_CONF" -d "$DB_NAME"
}

cmd_serve_frontend() {
  load_env_if_exists
  log "SERVE_FRONTEND_FOREGROUND"
  cd "$APP/frontend"
  [ -d node_modules ] || npm install --no-audit --no-fund
  export VITE_API_PROXY_TARGET="http://127.0.0.1:${ODOO_PORT}"
  export VITE_CHAT_STREAMING="${VITE_CHAT_STREAMING:-0}"
  exec npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT"
}

cmd_serve_cloudflare() {
  load_env_if_exists
  command -v cloudflared >/dev/null 2>&1 || die "cloudflared not found"
  mkdir -p "$WS/cf-home"
  log "SERVE_CLOUDFLARE_FOREGROUND"
  HOME="$WS/cf-home" exec cloudflared tunnel --protocol http2 --url "http://127.0.0.1:${FRONTEND_PORT}"
}

cmd_health() {
  load_env_if_exists
  set +e
  for url in \
    "http://127.0.0.1:${PG_PORT}" \
    "http://127.0.0.1:${ODOO_PORT}/web/login" \
    "http://127.0.0.1:${FRONTEND_PORT}" \
    "http://127.0.0.1:8000/v1/models"; do
    printf '%-45s ' "$url"
    curl -fsSI --max-time 5 "$url" >/dev/null && echo OK || echo DOWN
  done
}

case "$CMD" in
  install) cmd_install "$@" ;;
  serve-vllm) cmd_serve_vllm "$@" ;;
  serve-odoo) cmd_serve_odoo "$@" ;;
  serve-frontend) cmd_serve_frontend "$@" ;;
  serve-cloudflare) cmd_serve_cloudflare "$@" ;;
  health) cmd_health "$@" ;;
  *)
    cat <<EOF
Usage: $0 {install|serve-vllm|serve-odoo [public-origin]|serve-frontend|serve-cloudflare|health}
EOF
    exit 2
    ;;
esac
