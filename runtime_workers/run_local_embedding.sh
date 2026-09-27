#!/usr/bin/env bash
# CPU embedding worker for the RAG stack (see local_embedding_server.py).
set -euo pipefail

: "${AI_CHAT_SERVER_BIN:=/workspace/vllm-venv/bin/python}"
: "${AI_EMBEDDING_SERVER_SCRIPT:=$(dirname "$0")/local_embedding_server.py}"
: "${AI_VLLM_EMBEDDING_MODEL_PATH:=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2}"
: "${AI_VLLM_HOST:=127.0.0.1}"
: "${AI_VLLM_PORT:?Set AI_VLLM_PORT in the service environment}"
: "${AI_VLLM_EMBEDDING_MODEL:?Set AI_VLLM_EMBEDDING_MODEL in the service environment}"

[[ -x "$AI_CHAT_SERVER_BIN" ]] || { echo "Missing python: $AI_CHAT_SERVER_BIN" >&2; exit 1; }
[[ -f "$AI_EMBEDDING_SERVER_SCRIPT" ]] || { echo "Missing server script: $AI_EMBEDDING_SERVER_SCRIPT" >&2; exit 1; }

export AI_VLLM_EMBEDDING_MODEL_PATH
export AI_VLLM_HOST
export AI_VLLM_PORT
export AI_VLLM_EMBEDDING_MODEL

exec "$AI_CHAT_SERVER_BIN" "$AI_EMBEDDING_SERVER_SCRIPT"