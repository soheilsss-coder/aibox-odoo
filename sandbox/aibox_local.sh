#!/usr/bin/env bash
# AIBOX bring-up for a machine with no Docker and no root package manager.
#
# The shipped installer (install_aibox_onefile.sh) needs Docker for PostgreSQL
# and Redis and systemd for the services. A lot of real targets - CI runners,
# shared dev boxes, restricted VPS images, this repository's own review
# sandbox - have neither. This script produces the same running product on
# such a box using only pip, npm and git:
#
#   * PostgreSQL comes from the `pgserver` wheel, which ships the server
#     binaries inside the package (no download at install time).
#   * `pg_trgm` and `unaccent` are not in that wheel and Odoo 18 refuses to
#     start without pg_trgm, so they are compiled from the matching
#     postgres/postgres tag with the wheel's own pgxs and server headers.
#   * Redis comes from the `redislite` wheel, which ships a real redis-server
#     binary. The gateway's rate limiter is fail-closed without Redis, so this
#     is not optional - see custom_addons/ai_gateway/controllers/rate_limit.py.
#   * Odoo and the odoo-llm framework are shallow-cloned from GitHub.
#
# Usage:
#   sandbox/aibox_local.sh install     # venv, deps, postgres, db, modules  (once)
#   sandbox/aibox_local.sh seed        # apply the LLM API configuration
#   sandbox/aibox_local.sh demo        # seed demo departments/users/documents
#   sandbox/aibox_local.sh start       # postgres + redis + mock LLM + odoo + frontend
#   sandbox/aibox_local.sh status      # what is listening, what answers
#   sandbox/aibox_local.sh stop
#
# Environment (all optional, all have working defaults):
#   AIBOX_WS            workspace root            (default /tmp/aibox)
#   AIBOX_ODOO_BRANCH   Odoo branch               (default 18.0)
#   AIBOX_DB            database name             (default aibox)
#   AI_LLM_API_BASE     chat API base URL         (default local mock)
#   AI_LLM_API_KEY      chat API key
#   AI_LLM_MODEL        chat model name
#   AI_EMBEDDING_API_BASE / AI_EMBEDDING_MODEL / AI_EMBEDDING_DIM
#   AIBOX_MOCK_LLM=1    run the offline mock LLM API (default 1)
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS="${AIBOX_WS:-/tmp/aibox}"
SRC="$WS/src"
VENV="$WS/venv"
LOGS="$WS/logs"
DB="${AIBOX_DB:-aibox}"
DB_USER="${AIBOX_DB_USER:-aibox}"
DB_PASSWORD="${AIBOX_DB_PASSWORD:-aibox}"
PGDATA="${AIBOX_PGDATA:-$WS/pgdata}"
ODOO_BRANCH="${AIBOX_ODOO_BRANCH:-18.0}"
ODOO_PORT="${AIBOX_ODOO_PORT:-18069}"
FRONTEND_PORT="${AIBOX_FRONTEND_PORT:-15173}"
REDIS_PORT="${AIBOX_REDIS_PORT:-16379}"
MOCK_CHAT_PORT="${AIBOX_MOCK_CHAT_PORT:-8000}"
MOCK_EMB_PORT="${AIBOX_MOCK_EMB_PORT:-8002}"
MOCK_LLM="${AIBOX_MOCK_LLM:-1}"

# The LLM defaults point at the offline mock. Point these at a real vendor and
# the same code path runs against it - nothing else changes.
export AI_LLM_API_BASE="${AI_LLM_API_BASE:-http://127.0.0.1:$MOCK_CHAT_PORT/v1}"
export AI_LLM_MODEL="${AI_LLM_MODEL:-mock-chat-model}"
export AI_EMBEDDING_API_BASE="${AI_EMBEDDING_API_BASE:-http://127.0.0.1:$MOCK_EMB_PORT/v1}"
export AI_EMBEDDING_MODEL="${AI_EMBEDDING_MODEL:-mock-embedding-model}"
export AI_EMBEDDING_API_KEY="${AI_EMBEDDING_API_KEY:-${AI_LLM_API_KEY:-mock-key-1234567890}}"
export AI_LLM_API_KEY="${AI_LLM_API_KEY:-mock-key-1234567890}"
export AI_RAG_EMBEDDING_DIM="${AI_RAG_EMBEDDING_DIM:-${AI_EMBEDDING_DIM:-384}}"

export AI_GATEWAY_ENV="${AI_GATEWAY_ENV:-development}"
export AI_GATEWAY_REDIS_URL="${AI_GATEWAY_REDIS_URL:-redis://127.0.0.1:$REDIS_PORT/0}"
export AIBOX_REPO="$REPO"
export PYTHONWARNINGS=ignore

MODULES="${AIBOX_MODULES:-web,mail,hr,hr_attendance,hr_holidays,project,stock,account,mrp,sales_team,sale_management,purchase,llm,llm_tool,llm_openai,llm_thread,llm_assistant,llm_knowledge,company_ai_demo,ai_gateway,ai_business_tools,ai_control_plane,ai_integration,ai_rag,ai_customer_plane,ai_semantic_api,ai_correspondence,ai_document_intelligence,ai_workflow,ai_collaboration,ai_production,ai_experience,ai_telegram_bridge,ai_debrand}"

log()  { printf '\n\033[1m===== %s =====\033[0m\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

PG_INSTALL() { python3 -c "import pgserver,os;print(os.path.join(os.path.dirname(pgserver.__file__),'pginstall'))" 2>/dev/null; }

odoo_bin() { "$VENV/bin/python" "$SRC/odoo/odoo-bin" "$@"; }

write_conf() {
  mkdir -p "$WS/conf" "$LOGS" "$WS/filestore"
  cat > "$WS/conf/odoo.conf" <<EOF
[options]
addons_path = $SRC/odoo/addons,$SRC/odoo-llm,$REPO/custom_addons
data_dir = $WS/filestore
db_host = $PGDATA
db_port = False
db_user = $DB_USER
db_password = $DB_PASSWORD
db_name = $DB
dbfilter = ^$DB\$
http_port = $ODOO_PORT
http_interface = 0.0.0.0
proxy_mode = True
workers = 0
max_cron_threads = 1
limit_time_cpu = 600
limit_time_real = 1200
log_level = info
logfile = $LOGS/odoo.log
EOF
  echo "wrote $WS/conf/odoo.conf"
}

pg_up() {
  # pgserver starts the bundled server and leaves it running after the Python
  # process exits (cleanup_mode=None), so this returns immediately.
  "$VENV/bin/python" - "$PGDATA" <<'PY'
import sys, time
import pgserver
srv = pgserver.get_server(sys.argv[1], cleanup_mode=None)
print("postgres ready:", srv.get_uri())
time.sleep(1)
PY
}

pg_ext() {
  "$VENV/bin/python" - "$PGDATA" "$DB" "$DB_USER" "$DB_PASSWORD" <<'PY'
import sys, psycopg2
pgdata, dbname, user, password = sys.argv[1:5]
admin = psycopg2.connect("dbname=postgres user=%s password=%s host=%s" % (user, password, pgdata))
admin.autocommit = True
cur = admin.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (dbname,))
if not cur.fetchone():
    cur.execute('CREATE DATABASE "%s" OWNER "%s"' % (dbname, user))
    print("created database", dbname)
conn = psycopg2.connect("dbname=%s user=%s password=%s host=%s" % (dbname, user, password, pgdata))
conn.autocommit = True
c = conn.cursor()
for ext in ("vector", "pg_trgm", "unaccent"):
    c.execute("CREATE EXTENSION IF NOT EXISTS %s" % ext)
    c.execute("SELECT extversion FROM pg_extension WHERE extname=%s", (ext,))
    print("extension", ext, "->", c.fetchone()[0])
PY
}

build_pg_ext() {
  # Odoo 18 needs pg_trgm; the pgserver wheel does not ship contrib. Build the
  # missing extensions from the tag that matches the bundled server, using the
  # wheel's own pgxs and headers.
  local pgc pgi ver tag
  pgi="$(PG_INSTALL)"
  pgc="$pgi/bin/pg_config"
  [ -x "$pgc" ] || die "pg_config not found at $pgc"
  if [ -f "$pgi/share/postgresql/extension/pg_trgm.control" ]; then
    echo "pg_trgm already present"
    return 0
  fi
  need gcc; need make
  ver="$("$pgc" --version | grep -oE '[0-9]+\.[0-9]+' | head -1)"
  tag="REL_$(echo "$ver" | tr '.' '_')"
  log "building pg_trgm + unaccent for PostgreSQL $ver ($tag)"
  [ -d "$SRC/pg-contrib" ] || git clone --depth 1 --branch "$tag" --filter=blob:none --sparse \
      https://github.com/postgres/postgres.git "$SRC/pg-contrib"
  git -C "$SRC/pg-contrib" sparse-checkout set contrib/pg_trgm contrib/unaccent
  for ext in pg_trgm unaccent; do
    make -C "$SRC/pg-contrib/contrib/$ext" USE_PGXS=1 PG_CONFIG="$pgc" >/dev/null
    make -C "$SRC/pg-contrib/contrib/$ext" USE_PGXS=1 PG_CONFIG="$pgc" install >/dev/null
    echo "built $ext"
  done
}

redis_up() {
  local rs
  rs="$("$VENV/bin/python" -c "import redislite,os;print(os.path.join(os.path.dirname(redislite.__file__),'bin','redis-server'))")"
  [ -x "$rs" ] || die "redis-server not found in the redislite wheel"
  mkdir -p "$WS/redis"
  nohup "$rs" --port "$REDIS_PORT" --bind 127.0.0.1 --dir "$WS/redis" \
      --save '' --appendonly no --loglevel notice >"$LOGS/redis.log" 2>&1 &
  echo "redis pid $! on 127.0.0.1:$REDIS_PORT"
  sleep 1
}

cmd_install() {
  need python3; need git; need npm; need gcc; need make
  mkdir -p "$SRC" "$LOGS"
  log "1/6 python venv"
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip wheel setuptools

  log "2/6 sources"
  [ -d "$SRC/odoo" ] || git clone --depth 1 --branch "$ODOO_BRANCH" https://github.com/odoo/odoo.git "$SRC/odoo"
  [ -d "$SRC/odoo-llm" ] || git clone --depth 1 --branch "$ODOO_BRANCH" https://github.com/apexive/odoo-llm.git "$SRC/odoo-llm"

  log "3/6 dependencies"
  # python-ldap needs libldap and python3-dev headers and is only used by the
  # optional auth_ldap module; psycopg2 (source) needs pg_config, so the binary
  # wheel is installed separately.
  "$VENV/bin/pip" install -q pgserver redislite
  grep -vE '^(psycopg2|python-ldap)' "$SRC/odoo/requirements.txt" > "$WS/odoo-reqs.txt"
  "$VENV/bin/pip" install -q -r "$WS/odoo-reqs.txt"
  "$VENV/bin/pip" install -q psycopg2-binary redis requests numpy openpyxl jdatetime \
      pgvector openai 'pydantic>=2' jsonschema markdown2 markdownify emoji PyMuPDF \
      authlib cryptography mcp pyyaml jinja2
  "$VENV/lib/python3.11/site-packages" >/dev/null 2>&1 || true
  local sp; sp="$("$VENV/bin/python" -c 'import site;print(site.getsitepackages()[0])')"
  echo "$SRC/odoo" > "$sp/odoo-src.pth"
  echo "$SRC/odoo/addons" > "$sp/odoo-addons.pth"

  log "4/6 postgresql + contrib extensions"
  pg_up
  build_pg_ext
  "$VENV/bin/python" - "$PGDATA" "$DB_USER" "$DB_PASSWORD" <<'PY'
import sys, psycopg2
pgdata, user, password = sys.argv[1:4]
c = psycopg2.connect("dbname=postgres user=postgres host=%s" % pgdata); c.autocommit = True
cur = c.cursor()
cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (user,))
if cur.fetchone():
    cur.execute('ALTER ROLE "%s" LOGIN SUPERUSER CREATEDB PASSWORD %%s' % user, (password,))
else:
    cur.execute('CREATE ROLE "%s" LOGIN SUPERUSER CREATEDB PASSWORD %%s' % user, (password,))
print("role ready:", user)
PY

  log "5/6 database + modules"
  write_conf
  pg_ext
  odoo_bin -c "$WS/conf/odoo.conf" -d "$DB" -i "$MODULES" --without-demo=all --stop-after-init
  grep -cE "CRITICAL|Traceback" "$LOGS/odoo.log" | xargs -I{} echo "CRITICAL/Traceback lines in the log: {}"

  log "6/6 frontend"
  ( cd "$REPO/frontend" && npm install --no-audit --no-fund )
  echo
  echo "INSTALL OK. Next:  sandbox/aibox_local.sh seed && sandbox/aibox_local.sh start"
}

cmd_seed() {
  odoo_bin shell -c "$WS/conf/odoo.conf" -d "$DB" --no-http < "$REPO/runtime_workers/seed_api_inference.py"
}

cmd_demo() {
  odoo_bin shell -c "$WS/conf/odoo.conf" -d "$DB" --no-http < "$REPO/04_seed_demo_data.py"
}

cmd_verify() {
  "$VENV/bin/python" "$REPO/runtime_workers/verify_llm_api.py" "$@"
}

cmd_start() {
  pg_up
  redis_up
  if [ "$MOCK_LLM" = "1" ]; then
    log "mock LLM API (offline stand-in for the real vendor)"
    nohup "$VENV/bin/python" "$REPO/runtime_workers/mock_llm_server.py" \
        --port "$MOCK_CHAT_PORT" --served-model "$AI_LLM_MODEL" \
        --embedding-dim "$AI_RAG_EMBEDDING_DIM" --latency-ms 120 \
        >"$LOGS/mock-chat.log" 2>&1 &
    nohup "$VENV/bin/python" "$REPO/runtime_workers/mock_llm_server.py" \
        --port "$MOCK_EMB_PORT" --served-model "$AI_EMBEDDING_MODEL" \
        --embedding-model "$AI_EMBEDDING_MODEL" --embedding-dim "$AI_RAG_EMBEDDING_DIM" \
        >"$LOGS/mock-emb.log" 2>&1 &
    sleep 1
  fi
  log "odoo on 0.0.0.0:$ODOO_PORT"
  nohup odoo_bin -c "$WS/conf/odoo.conf" -d "$DB" --http-port "$ODOO_PORT" \
      --http-interface 0.0.0.0 >"$LOGS/odoo-stdout.log" 2>&1 &
  sleep 8
  log "frontend on 0.0.0.0:$FRONTEND_PORT"
  ( cd "$REPO/frontend" && VITE_API_PROXY_TARGET="http://127.0.0.1:$ODOO_PORT" \
      nohup npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" >"$LOGS/frontend.log" 2>&1 & )
  sleep 6
  cmd_status
}

cmd_status() {
  printf '\n%-34s %s\n' "ENDPOINT" "RESULT"
  for pair in \
      "odoo /web/login|http://127.0.0.1:$ODOO_PORT/web/login" \
      "gateway /api/health|http://127.0.0.1:$ODOO_PORT/api/health" \
      "frontend|http://127.0.0.1:$FRONTEND_PORT/" \
      "llm /v1/models|$AI_LLM_API_BASE/models" \
      "embedding /v1/models|$AI_EMBEDDING_API_BASE/models" ; do
    local name="${pair%%|*}" url="${pair##*|}"
    printf '%-34s ' "$name"
    curl -sS -m 8 -o /dev/null -w 'HTTP %{http_code}\n' "$url" 2>/dev/null || echo DOWN
  done
  echo
  echo "logs: $LOGS/"
}

cmd_stop() {
  pkill -f "odoo-bin -c $WS/conf/odoo.conf" 2>/dev/null || true
  pkill -f "mock_llm_server.py" 2>/dev/null || true
  pkill -f "redis-server.*$REDIS_PORT" 2>/dev/null || true
  pkill -f "vite.*$FRONTEND_PORT" 2>/dev/null || true
  echo "stopped application services (postgres left running: pg_ctl -D $PGDATA stop)"
}

case "${1:-help}" in
  install) cmd_install ;;
  seed)    cmd_seed ;;
  demo)    cmd_demo ;;
  verify)  shift; cmd_verify "$@" ;;
  start)   cmd_start ;;
  status)  cmd_status ;;
  stop)    cmd_stop ;;
  *) sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
esac
