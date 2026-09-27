#!/usr/bin/env bash
# ============================================================================
# Tiny REAL local LLM — OpenAI-compatible, no API key, no account, no card.
# llama.cpp serving a Qwen2.5-1.5B-Instruct quant (~1 GB, downloaded once).
# Works anywhere outbound HTTPS reaches huggingface.co (e.g. Codespaces',
# VPS). OpenAI-style /v1/chat/completions + /v1/models on $PORT.
# ============================================================================
set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WS="${AIBOX_LOCAL_LLM_WS:-$REPO_ROOT/.local-llm}"
PORT="${AIBOX_LOCAL_LLM_PORT:-8010}"
MODEL_NAME="${AIBOX_LOCAL_LLM_MODEL:-qwen2.5-1.5b-instruct-q4_k_m.gguf}"
MODEL_URL="${AIBOX_LOCAL_LLM_URL:-https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/$MODEL_NAME}"
THREADS="${AIBOX_LOCAL_LLM_THREADS:-2}"
CTX="${AIBOX_LOCAL_LLM_CTX:-4096}"

mkdir -p "$WS"

if [ ! -d "$WS/venv" ]; then
  echo "[local-llm] creating python venv..."
  python3 -m venv "$WS/venv"
fi
"$WS/venv/bin/pip" install -q --disable-pip-version-check --upgrade pip
"$WS/venv/bin/pip" install -q --disable-pip-version-check "llama-cpp-python>=0.2.85"

if [ ! -f "$WS/$MODEL_NAME" ]; then
  echo "[local-llm] downloading $MODEL_NAME (~1 GB, one time)..."
  curl -fSL --retry 3 --retry-delay 5 -o "$WS/$MODEL_NAME.part" "$MODEL_URL"
  mv "$WS/$MODEL_NAME.part" "$WS/$MODEL_NAME"
fi

echo "[local-llm] serving $MODEL_NAME on 0.0.0.0:$PORT (threads=$THREADS ctx=$CTX)"
exec "$WS/venv/bin/python" -m llama_cpp.server \
  --host 0.0.0.0 --port "$PORT" \
  --model "$WS/$MODEL_NAME" \
  --n_ctx "$CTX" --n_threads "$THREADS" --log_disable
