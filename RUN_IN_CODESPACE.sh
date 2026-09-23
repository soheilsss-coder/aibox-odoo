#!/usr/bin/env bash
# ============================================================================
# RUN THE FULL AIBOX PLATFORM INSIDE YOUR GITHUB CODESPACE - ONE LINE, NO CARD
# ----------------------------------------------------------------------------
# Your personal GitHub account already includes FREE Codespaces hours every
# month (no credit card, no new account, works from any browser).
#
#   1. Open your repo on github.com -> green "Code" button -> "Codespaces"
#      tab -> "Create codespace on arena/01a0a69b-aibox-odoo"
#   2. When the browser IDE opens, press Ctrl+` to open the terminal and run:
#
#          ./RUN_IN_CODESPACE.sh
#
#   3. The script builds the appliance (first time: 15-40 min on the free
#      2-core machine), starts it, makes the port public and prints your URL:
#
#          https://<your-codespace-name>-8080.app.github.dev
#
#      Login: admin / admin   (change it after first login)
#
# The free tier gives ~60 hours of runtime per month on the 2-core machine;
# the codespace pauses when idle and restarts from github.com/codespaces.
# ============================================================================
set -e
cd "$(dirname "$0")"

# Docker daemon can lag behind the codespace's own boot when this script is
# fired automatically (devcontainer postStartCommand).
for i in $(seq 1 40); do
  docker info >/dev/null 2>&1 && break
  sleep 5
done

URL="https://${CODESPACE_NAME}-8080.app.github.dev"
IMAGE="aibox"

echo "=============================================================="
echo " AIBOX in Codespace: ${CODESPACE_NAME:-unknown}"
echo " Target URL: ${URL}"
echo "=============================================================="

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not available - make sure you opened a Codespace" >&2
  echo "(github.com > repo > Code > Codespaces > Create)." >&2
  exit 1
fi

# Keep the machine awake while you work (no-op if the flag is unsupported).
gh codespace edit --codespace "${CODESPACE_NAME}" --idle-timeout 240m >/dev/null 2>&1 || true

if [ "$(docker image inspect "${IMAGE}" >/dev/null 2>&1 && echo yes)" != "yes" ]; then
  echo "[1/5] Building the appliance image (first run only - grab a coffee)..."
  docker build --pull -t "${IMAGE}" .
else
  echo "[1/5] Image already built - skipping."
fi

echo "[2/5] Background services..."
docker rm -f "${IMAGE}" >/dev/null 2>&1 || true

# Real, tiny, FREE local LLM (llama.cpp + Qwen2.5-1.5B, no API key/card) on
# the codespace host - HF is reachable from codespace egress even when other
# sandboxes block it. Fallback: the bundled deterministic mock chat server.
LLM_ARGS=()
if [ "${AIBOX_LOCAL_LLM:-1}" = "1" ]; then
  echo "      starting tiny local LLM (llama.cpp, Qwen2.5-1.5B) on :8010 ..."
  nohup bash runtime_workers/local_llm_server.sh > /workspaces/aibox-odoo/local-llm.log 2>&1 &
  LLM_ARGS+=(
    --add-host=host.docker.internal:host-gateway
    -e "AI_LLM_API_BASE=http://host.docker.internal:8010/v1"
    -e "AI_LLM_MODEL=${AIBOX_LOCAL_LLM_MODEL:-qwen2.5-1.5b-instruct-q4_k_m.gguf}"
  )
fi

echo "[3/5] (Re)starting the appliance container..."
docker run -d --name "${IMAGE}" --restart unless-stopped \
  -e PORT=8080 \
  -e AI_GATEWAY_ALLOWED_ORIGIN="${URL}" \
  -e AI_GATEWAY_ALLOWED_ORIGINS="${URL},https://soheilsss-coder.github.io" \
  "${LLM_ARGS[@]}" \
  -p 8080:8080 \
  "${IMAGE}"

echo "[3/4] Making port 8080 public..."
gh codespace ports visibility 8080:public --codespace "${CODESPACE_NAME}" >/dev/null 2>&1 || true

echo "[5/5] First boot is installing Odoo modules into the database;"
echo "      give it several minutes and then open:"
echo ""
echo "      ${URL}"
echo ""
echo "      login:  admin"
echo "      pass :  admin"
echo "=============================================================="
echo "Live logs follow (Ctrl+C only stops the log view, not the app):"
set +e
docker logs -f --tail 50 "${IMAGE}"
state=$(docker inspect -f 'exit={{.State.ExitCode}} oom={{.State.OOMKilled}}' "${IMAGE}" 2>/dev/null || echo "exit=? oom=?")
if [ "${state%% *}" != "exit=0" ]; then
  echo ""
  echo "###############  BOOT FAILED - ${state}  ###############"
  echo "Last 80 log lines (paste these back - or simply re-run the script, it RESUMES):"
  echo "------------------------------------------------------------"
  docker logs --tail 80 "${IMAGE}" 2>&1
  echo "------------------------------------------------------------"
fi
