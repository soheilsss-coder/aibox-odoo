#!/usr/bin/env bash
# Foreground service runner for hosts without Docker/systemd (CI, dev boxes,
# this repo's own review sandbox): starts the sidecars in the background
# (Redis for the fail-closed rate limiter, the Nova brain chat server, the
# deterministic embedding double) and then execs Odoo in the foreground so the
# supervisor owns ONE process that keeps the whole stack alive.
#
#   AIBOX_WS=/path/to/ws sandbox/run_services_fg.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WS="${AIBOX_WS:-$REPO/.repro-ws}"
VENV="$WS/venv"
SRC="$WS/src"
LOGS="$WS/logs"
REDIS_PORT="${AIBOX_REDIS_PORT:-16379}"
CHAT_PORT="${AIBOX_MOCK_CHAT_PORT:-8000}"
EMB_PORT="${AIBOX_MOCK_EMB_PORT:-8002}"
mkdir -p "$LOGS"

export AI_LLM_API_BASE="${AI_LLM_API_BASE:-http://127.0.0.1:$CHAT_PORT/v1}"
export AI_LLM_MODEL="${AI_LLM_MODEL:-nova-local-brain}"
export AI_LLM_API_KEY="${AI_LLM_API_KEY:-mock-key-1234567890}"
export AI_EMBEDDING_API_BASE="${AI_EMBEDDING_API_BASE:-http://127.0.0.1:$EMB_PORT/v1}"
export AI_EMBEDDING_MODEL="${AI_EMBEDDING_MODEL:-mock-embedding-model}"
export AI_EMBEDDING_API_KEY="${AI_EMBEDDING_API_KEY:-$AI_LLM_API_KEY}"
export AI_RAG_EMBEDDING_DIM="${AI_RAG_EMBEDDING_DIM:-384}"
export AI_GATEWAY_ENV="${AI_GATEWAY_ENV:-development}"
export AI_GATEWAY_REDIS_URL="${AI_GATEWAY_REDIS_URL:-redis://127.0.0.1:$REDIS_PORT/0}"
export AI_GATEWAY_ALLOW_LOCAL_LIMITER="${AI_GATEWAY_ALLOW_LOCAL_LIMITER:-1}"
export PYTHONWARNINGS=ignore

if ! (echo >/dev/tcp/127.0.0.1/$REDIS_PORT) 2>/dev/null; then
  RS="$("$VENV/bin/python" -c "import redislite,os;print(os.path.join(os.path.dirname(redislite.__file__),'bin','redis-server'))")"
  mkdir -p "$WS/redis"
  nohup "$RS" --port "$REDIS_PORT" --bind 127.0.0.1 --dir "$WS/redis" \
      --save '' --appendonly no --loglevel notice >"$LOGS/redis.log" 2>&1 &
  echo "redis pid $! on 127.0.0.1:$REDIS_PORT"
  sleep 1
fi

if ! (echo >/dev/tcp/127.0.0.1/$CHAT_PORT) 2>/dev/null; then
  if [ "${AIBOX_CHAT_BRAIN:-1}" = "1" ]; then
    echo "Nova brain chat on 127.0.0.1:$CHAT_PORT (real tool calling)"
    nohup "$VENV/bin/python" "$REPO/runtime_workers/nova_brain_server.py" \
        --port "$CHAT_PORT" --served-model "$AI_LLM_MODEL" >"$LOGS/nova-brain.log" 2>&1 &
  else
    echo "mock chat double on 127.0.0.1:$CHAT_PORT"
    nohup "$VENV/bin/python" "$REPO/runtime_workers/mock_llm_server.py" \
        --port "$CHAT_PORT" --served-model "$AI_LLM_MODEL" \
        --embedding-dim "$AI_RAG_EMBEDDING_DIM" --latency-ms 120 >"$LOGS/mock-chat.log" 2>&1 &
  fi
  sleep 1
fi

if ! (echo >/dev/tcp/127.0.0.1/$EMB_PORT) 2>/dev/null; then
  echo "embedding double on 127.0.0.1:$EMB_PORT"
  nohup "$VENV/bin/python" "$REPO/runtime_workers/mock_llm_server.py" \
      --port "$EMB_PORT" --served-model "$AI_EMBEDDING_MODEL" \
      --embedding-model "$AI_EMBEDDING_MODEL" --embedding-dim "$AI_RAG_EMBEDDING_DIM" \
      >"$LOGS/mock-emb.log" 2>&1 &
  sleep 1
fi

echo "odoo (foreground) on 0.0.0.0:18069"
exec "$VENV/bin/python" "$SRC/odoo/odoo-bin" -c "$WS/conf/odoo.conf"
