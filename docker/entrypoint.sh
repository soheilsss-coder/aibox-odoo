#!/usr/bin/env bash
# Container entrypoint for the AIBOX appliance.
#
# Order matters: nginx is started FIRST so the platform's health check passes
# within a second, then the database is brought up. On a first boot with an
# empty /data/pgdata the Odoo module install takes several minutes, and a
# platform that sees no listener during that window will kill the container.
#
# The heavy lifting is delegated to sandbox/aibox_local.sh (install / demo),
# which is the same script that was exercised end to end in the workspace.
set -Eeuo pipefail

REPO="${AIBOX_REPO:-/opt/aibox}"
WS="${AIBOX_WS:-/opt/aibox-ws}"
SRC="$WS/src"
VENV="$WS/venv"
PGDATA="${AIBOX_PGDATA:-/data/pgdata}"
DB="${AIBOX_DB:-aibox}"
ODOO_PORT="${AIBOX_ODOO_PORT:-18069}"
REDIS_PORT="${AIBOX_REDIS_PORT:-16379}"
PORT="${PORT:-8080}"
MOCK_PORT="${AIBOX_MOCK_PORT:-8000}"
MOCK_EMB_PORT="${AIBOX_MOCK_EMB_PORT:-8002}"

log() { printf '\n\033[1m===== %s =====\033[0m\n' "$*"; }

# ---------------------------------------------------------------- nginx first
sed "s/__PORT__/${PORT}/g" /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
mkdir -p /run
nginx
log "nginx listening on :$PORT (health check will pass from here on)"

# ------------------------------------------------------------- gateway origin
# ai_gateway refuses to boot without AI_GATEWAY_ALLOWED_ORIGIN, and in
# production it insists on a concrete HTTPS origin rather than '*'. Both
# platforms publish the public hostname as an env var; fall back to the
# permissive development mode when neither is present (e.g. local docker run).
if [ -z "${AI_GATEWAY_ALLOWED_ORIGIN:-}" ]; then
  if [ -n "${RAILWAY_PUBLIC_DOMAIN:-}" ]; then
    export AI_GATEWAY_ALLOWED_ORIGIN="https://${RAILWAY_PUBLIC_DOMAIN}"
  elif [ -n "${RENDER_EXTERNAL_URL:-}" ]; then
    export AI_GATEWAY_ALLOWED_ORIGIN="${RENDER_EXTERNAL_URL}"
  fi
fi
if [ -n "${AI_GATEWAY_ALLOWED_ORIGIN:-}" ]; then
  export AI_GATEWAY_ENV="${AI_GATEWAY_ENV:-production}"
  export AI_GATEWAY_COOKIE_SECURE="${AI_GATEWAY_COOKIE_SECURE:-1}"
  export AI_GATEWAY_COOKIE_SAMESITE="${AI_GATEWAY_COOKIE_SAMESITE:-Lax}"
else
  export AI_GATEWAY_ENV="${AI_GATEWAY_ENV:-development}"
fi
export AI_GATEWAY_REDIS_URL="${AI_GATEWAY_REDIS_URL:-redis://127.0.0.1:${REDIS_PORT}/0}"
export AIBOX_REPO="$REPO"
export PYTHONWARNINGS=ignore

# The appliance ships pointing at the bundled stand-in so the product is
# explorable immediately. Replace it from Admin > "مدل زبانی": saving a real
# provider there deactivates the loopback one, and Delete brings it back.
if [ "${AIBOX_START_MOCK_LLM:-1}" = "1" ]; then
  export AI_LLM_API_BASE="${AI_LLM_API_BASE:-http://127.0.0.1:${MOCK_PORT}/v1}"
  export AI_LLM_MODEL="${AI_LLM_MODEL:-mock-chat-model}"
  export AI_EMBEDDING_API_BASE="${AI_EMBEDDING_API_BASE:-http://127.0.0.1:${MOCK_EMB_PORT}/v1}"
  export AI_EMBEDDING_MODEL="${AI_EMBEDDING_MODEL:-mock-embedding-model}"
  export AI_LLM_API_KEY="${AI_LLM_API_KEY:-mock-key-1234567890}"
  export AI_EMBEDDING_API_KEY="${AI_EMBEDDING_API_KEY:-${AI_LLM_API_KEY}}"
  export AI_RAG_EMBEDDING_DIM="${AI_RAG_EMBEDDING_DIM:-384}"
fi

# --------------------------------------------------------- memory headroom
# Free container tiers are 512MB-1GB, which is tight for Odoo + PostgreSQL +
# Redis in one image. AIBOX_LITE=1 drops the six heaviest Odoo modules
# (stock/mrp/account/purchase/sales_team/sale_management); the AI product
# itself - gateway, semantic API, RAG, assistant, admin console - is untouched.
# sandbox/aibox_local.sh already reads AIBOX_MODULES, so no other change is
# needed to make the shorter list take effect.
if [ "${AIBOX_LITE:-0}" = "1" ] && [ -z "${AIBOX_MODULES:-}" ]; then
  export AIBOX_MODULES="web,mail,hr,hr_attendance,hr_holidays,project,llm,llm_tool,llm_openai,llm_thread,llm_assistant,llm_knowledge,company_ai_demo,ai_gateway,ai_business_tools,ai_control_plane,ai_integration,ai_rag,ai_customer_plane,ai_semantic_api,ai_correspondence,ai_document_intelligence,ai_workflow,ai_collaboration,ai_production,ai_experience,ai_telegram_bridge,ai_debrand"
  log "AIBOX_LITE=1: installing 28 modules instead of 34"
fi

# ------------------------------------------------------- install (first boot)
mkdir -p "$PGDATA" "$WS/logs"
if [ ! -f "$WS/.installed" ]; then
  log "first boot: creating the database and installing modules (several minutes)"
  bash "$REPO/sandbox/aibox_local.sh" install
  touch "$WS/.installed"
else
  log "existing database found at $PGDATA"
  # install also starts postgres; on a warm boot nothing has started it yet.
  bash "$REPO/sandbox/aibox_local.sh" status >/dev/null 2>&1 || true
  "$VENV/bin/python" - "$PGDATA" <<'PY' || true
import sys, pgserver
srv = pgserver.get_server(sys.argv[1], cleanup_mode=None)
print("postgres ready:", srv.get_uri())
PY
fi

# PostgreSQL defaults (shared_buffers 128MB, max_connections 100) are sized for
# a dedicated database box. This one shares the container with Odoo, Redis and
# nginx, so trim it once - after initdb has written postgresql.conf.
if [ -f "$PGDATA/postgresql.conf" ] && ! grep -q "AIBOX container tuning" "$PGDATA/postgresql.conf"; then
  cat >> "$PGDATA/postgresql.conf" <<'PGCONF'

# --- AIBOX container tuning ---
shared_buffers = 64MB
max_connections = 40
work_mem = 4MB
maintenance_work_mem = 32MB
effective_cache_size = 256MB
PGCONF
  log "applied PostgreSQL memory tuning for a shared container"
fi

if [ ! -f "$WS/.demo" ]; then
  log "seeding demo data"
  bash "$REPO/sandbox/aibox_local.sh" demo || echo "demo seed skipped (non-fatal)"
  touch "$WS/.demo"
fi

# --------------------------------------------------------------------- redis
if ! "$VENV/bin/python" -c "import socket,os,sys
s=socket.socket(); s.settimeout(1)
sys.exit(0 if s.connect_ex(('127.0.0.1', ${REDIS_PORT}))==0 else 1)" 2>/dev/null; then
  RS="$("$VENV/bin/python" -c "import redislite,os;print(os.path.join(os.path.dirname(redislite.__file__),'bin','redis-server'))")"
  mkdir -p "$WS/redis"
  nohup "$RS" --port "$REDIS_PORT" --bind 127.0.0.1 --dir "$WS/redis" \
      >"$WS/logs/redis.log" 2>&1 &
  log "redis on 127.0.0.1:$REDIS_PORT"
fi

# ------------------------------------------------------------- stand-in LLM
# Mirrors cmd_start in sandbox/aibox_local.sh exactly: one mock_llm_server.py
# for chat and a second one for embeddings, because the embedding endpoint has
# to stay on a pinned dimension. Replacing either from Admin > "مدل زبانی"
# deactivates the loopback provider without a redeploy.
if [ "${AIBOX_START_MOCK_LLM:-1}" = "1" ]; then
  nohup "$VENV/bin/python" "$REPO/runtime_workers/mock_llm_server.py" \
      --port "$MOCK_PORT" --served-model "${AI_LLM_MODEL:-mock-chat-model}" \
      --embedding-dim "${AI_RAG_EMBEDDING_DIM:-384}" --latency-ms 120 \
      >"$WS/logs/mock-chat.log" 2>&1 &
  nohup "$VENV/bin/python" "$REPO/runtime_workers/mock_llm_server.py" \
      --port "$MOCK_EMB_PORT" --served-model "${AI_EMBEDDING_MODEL:-mock-embedding-model}" \
      --embedding-model "${AI_EMBEDDING_MODEL:-mock-embedding-model}" \
      --embedding-dim "${AI_RAG_EMBEDDING_DIM:-384}" \
      >"$WS/logs/mock-emb.log" 2>&1 &
  sleep 1
  log "stand-in LLM on :$MOCK_PORT and :$MOCK_EMB_PORT (replace from Admin > مدل زبانی)"
fi

# ---------------------------------------------------------------------- odoo
log "starting odoo on 127.0.0.1:$ODOO_PORT"
nohup "$VENV/bin/python" "$SRC/odoo/odoo-bin" \
    -c "$WS/conf/odoo.conf" -d "$DB" \
    --http-port "$ODOO_PORT" --http-interface 127.0.0.1 \
    >"$WS/logs/odoo.log" 2>&1 &

# Keep PID 1 attached to something that surfaces failures: stream Odoo's log and
# exit if either Odoo or nginx dies, so the platform restarts the container
# instead of serving a green health check over a dead backend.
ODOO_PID=$!
echo "odoo pid=$ODOO_PID"
while true; do
  if ! kill -0 "$ODOO_PID" 2>/dev/null; then
    echo "odoo exited; last 40 log lines:" >&2
    tail -40 "$WS/logs/odoo.log" >&2 || true
    exit 1
  fi
  if ! pgrep -x nginx >/dev/null 2>&1; then
    echo "nginx exited" >&2
    exit 1
  fi
  sleep 5
done
