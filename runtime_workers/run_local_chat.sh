#!/usr/bin/env bash
# CPU fallback for the chat workload: serves the exact AWQ chat model through
# an OpenAI-compatible transformers endpoint (see local_chat_server.py).
# This replaces the CUDA-only vLLM invocation on machines without a GPU.
set -euo pipefail

: "${AI_CHAT_SERVER_BIN:=/workspace/vllm-venv/bin/python}"
: "${AI_CHAT_SERVER_SCRIPT:=$(dirname "$0")/local_chat_server.py}"
: "${AI_VLLM_MODEL_PATH:?Set AI_VLLM_MODEL_PATH in the service environment}"
: "${AI_VLLM_HOST:=127.0.0.1}"
: "${AI_VLLM_PORT:?Set AI_VLLM_PORT in the service environment}"
: "${AI_VLLM_SERVED_MODEL:?Set AI_VLLM_SERVED_MODEL in the service environment}"

[[ -x "$AI_CHAT_SERVER_BIN" ]] || { echo "Missing python: $AI_CHAT_SERVER_BIN" >&2; exit 1; }
[[ -f "$AI_CHAT_SERVER_SCRIPT" ]] || { echo "Missing server script: $AI_CHAT_SERVER_SCRIPT" >&2; exit 1; }

export AI_VLLM_MODEL_PATH
export AI_VLLM_HOST
export AI_VLLM_PORT
export AI_VLLM_SERVED_MODEL
export AI_VLLM_MAX_MODEL_LEN="${AI_VLLM_MAX_MODEL_LEN:-32768}"

exec "$AI_CHAT_SERVER_BIN" "$AI_CHAT_SERVER_SCRIPT"