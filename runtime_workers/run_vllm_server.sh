#!/usr/bin/env bash
# Native vLLM service wrapper. One systemd unit invokes this per workload
# (chat, embedding or vision) with a separate EnvironmentFile.
set -euo pipefail

: "${AI_VLLM_BIN:=/opt/odoo/venv/bin/vllm}"
: "${AI_VLLM_MODEL_PATH:?Set AI_VLLM_MODEL_PATH in the service environment}"
: "${AI_VLLM_HOST:=127.0.0.1}"
: "${AI_VLLM_PORT:?Set AI_VLLM_PORT in the service environment}"
: "${AI_VLLM_SERVED_MODEL:?Set AI_VLLM_SERVED_MODEL in the service environment}"
: "${AI_VLLM_MAX_MODEL_LEN:=32768}"
: "${AI_VLLM_MAX_NUM_SEQS:=32}"
: "${AI_VLLM_MAX_NUM_BATCHED_TOKENS:=8192}"
: "${AI_VLLM_GPU_MEMORY_UTILIZATION:=0.60}"
: "${AI_VLLM_RUNNER:=generate}"
: "${AI_VLLM_DTYPE:=auto}"

[[ -x "$AI_VLLM_BIN" ]] || { echo "Missing vLLM executable: $AI_VLLM_BIN" >&2; exit 1; }
[[ "$AI_VLLM_MODEL_PATH" != *$'\n'* ]] || { echo "Model path contains a newline" >&2; exit 1; }
[[ "$AI_VLLM_SERVED_MODEL" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid served model alias" >&2; exit 1; }
[[ "$AI_VLLM_PORT" =~ ^[0-9]+$ && "$AI_VLLM_PORT" -ge 1024 && "$AI_VLLM_PORT" -le 65535 ]] || { echo "Invalid vLLM port" >&2; exit 1; }
[[ "$AI_VLLM_MAX_MODEL_LEN" =~ ^[0-9]+$ && "$AI_VLLM_MAX_MODEL_LEN" -ge 256 && "$AI_VLLM_MAX_MODEL_LEN" -le 2000000 ]] || { echo "Invalid max model length" >&2; exit 1; }
[[ "$AI_VLLM_MAX_NUM_SEQS" =~ ^[0-9]+$ && "$AI_VLLM_MAX_NUM_SEQS" -ge 1 && "$AI_VLLM_MAX_NUM_SEQS" -le 4096 ]] || { echo "Invalid max sequence count" >&2; exit 1; }
[[ "$AI_VLLM_MAX_NUM_BATCHED_TOKENS" =~ ^[0-9]+$ && "$AI_VLLM_MAX_NUM_BATCHED_TOKENS" -ge 256 && "$AI_VLLM_MAX_NUM_BATCHED_TOKENS" -le 2000000 ]] || { echo "Invalid max batched token count" >&2; exit 1; }
[[ "$AI_VLLM_GPU_MEMORY_UTILIZATION" =~ ^[0-9]+([.][0-9]+)?$ ]] || { echo "Invalid GPU memory utilization" >&2; exit 1; }
awk "BEGIN { exit !(${AI_VLLM_GPU_MEMORY_UTILIZATION} >= 0.10 && ${AI_VLLM_GPU_MEMORY_UTILIZATION} <= 0.99) }" || { echo "Invalid GPU memory utilization" >&2; exit 1; }

args=(serve "$AI_VLLM_MODEL_PATH"
  --host "$AI_VLLM_HOST"
  --port "$AI_VLLM_PORT"
  --served-model-name "$AI_VLLM_SERVED_MODEL"
  --max-model-len "$AI_VLLM_MAX_MODEL_LEN"
  --max-num-seqs "$AI_VLLM_MAX_NUM_SEQS"
  --max-num-batched-tokens "$AI_VLLM_MAX_NUM_BATCHED_TOKENS"
  --gpu-memory-utilization "$AI_VLLM_GPU_MEMORY_UTILIZATION"
  --dtype "$AI_VLLM_DTYPE"
  --disable-log-requests)

if [[ "${AI_VLLM_ENABLE_PREFIX_CACHING:-1}" == "1" ]]; then
  args+=(--enable-prefix-caching)
fi
if [[ "${AI_VLLM_ENABLE_CHUNKED_PREFILL:-1}" == "1" ]]; then
  args+=(--enable-chunked-prefill)
fi
if [[ "$AI_VLLM_RUNNER" != "generate" ]]; then
  args+=(--runner "$AI_VLLM_RUNNER")
fi
if [[ "${AI_VLLM_TRUST_REMOTE_CODE:-0}" == "1" ]]; then
  args+=(--trust-remote-code)
fi
# Speculative decoding is deliberately opt-in and benchmark-gated. Different
# vLLM releases accept different JSON schemas, so the deployment pins the
# schema in this environment variable rather than guessing a draft model.
if [[ -n "${AI_VLLM_SPECULATIVE_CONFIG:-}" ]]; then
  [[ "${AI_VLLM_SPECULATIVE_CONFIG}" != *$'\n'* ]] || { echo "Speculative config contains a newline" >&2; exit 1; }
  args+=(--speculative-config "$AI_VLLM_SPECULATIVE_CONFIG")
fi

exec "$AI_VLLM_BIN" "${args[@]}"
