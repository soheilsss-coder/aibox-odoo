#!/bin/bash
# =============================================================================
# Soup (roadmap #58, checklist item 2: soup train inside the isolated
# Incus container, not on the main host).
#
# WHAT THIS DOES: copies /opt/soup-workspace (soup.yaml + the curated
# training data - see 21_soup_export_training_data.py's own docstring
# for why that export is deliberately NOT ready-to-train on its own)
# into the SAME Incus container used for Hermes (roadmap #14), runs
# `soup train` and `soup ship` INSIDE that container (never on the
# Odoo host), then copies only the resulting adapter back out to a
# clearly-separate, clearly-timestamped candidate directory. It never
# writes to /opt/start_vllm.sh or anything else the production model
# reads from - see 23_soup_evaluate_candidate.sh / 24_soup_promote_
# candidate.sh for the (separate, manual) steps that touch that.
#
# WHY the Hermes container specifically: this project already has one
# Incus container carved out at a lower trust level than the Odoo host
# (roadmap #14, because Hermes is agent-facing). Soup is a young,
# single-maintainer project with no independent security audit -
# giving it the SAME container/trust boundary (not a new one, and
# definitely not the Odoo host, which has the real DB credentials and
# customer data) is the same reasoning, reused, not a new decision.
#
# WHAT THIS SCRIPT DOES NOT DO: provision the Incus container itself
# (see roadmap #14 - that's a manual, one-time setup step this project
# has never had a script for) or touch the production vLLM process in
# any way. It only produces a candidate adapter directory; nothing
# reads from it until you run the next two scripts by hand.
#
# Usage:
#   SOUP_INCUS_CONTAINER=hermes ./22_soup_train_isolated.sh
# =============================================================================
set -euo pipefail

CONTAINER="${SOUP_INCUS_CONTAINER:-hermes}"
WORKSPACE="${SOUP_WORKSPACE:-/opt/soup-workspace}"
CANDIDATES_DIR="${SOUP_CANDIDATES_DIR:-${WORKSPACE}/candidates}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
REMOTE_WORKSPACE="/root/soup-workspace"

echo "=== [0/4] Sanity checks ==="
if ! command -v incus >/dev/null 2>&1; then
  echo "incus CLI not found on this host. This step MUST run inside the"
  echo "isolated container - install/configure incus first, do not fall"
  echo "back to running soup directly on this host."
  exit 1
fi
if ! incus info "$CONTAINER" >/dev/null 2>&1; then
  echo "Incus container '$CONTAINER' not found (checked with 'incus info')."
  echo "Set SOUP_INCUS_CONTAINER to the name of the container you set up"
  echo "for Hermes (roadmap #14) - that container is provisioned manually,"
  echo "there is no setup script for it in this project."
  exit 1
fi
if [ ! -f "${WORKSPACE}/soup.yaml" ]; then
  echo "${WORKSPACE}/soup.yaml not found - run 09_setup_soup_finetune.sh"
  echo "first, then edit soup.yaml (model.base / data.path) before this step."
  exit 1
fi

echo ""
echo "=== [1/4] Copying soup workspace INTO the isolated container ==="
incus exec "$CONTAINER" -- mkdir -p "$REMOTE_WORKSPACE"
incus file push -r "${WORKSPACE}/." "${CONTAINER}${REMOTE_WORKSPACE}/"

echo ""
echo "=== [2/4] Installing soup-cli inside the container (if not already) ==="
incus exec "$CONTAINER" -- bash -lc '
  set -e
  if ! command -v soup >/dev/null 2>&1; then
    python3 -m venv /opt/soup
    source /opt/soup/bin/activate
    pip install -U pip
    pip install "soup-cli[train]"
    echo "export PATH=/opt/soup/bin:\$PATH" >> /root/.bashrc
  fi
'

echo ""
echo "=== [3/4] soup train && soup ship (runs INSIDE the container) ==="
# `soup ship` is Soup's own quality gate (tool-calling/JSON schema
# didn't regress) - if it fails, this script fails too, on purpose:
# a candidate that doesn't pass Soup's own gate should never reach
# 23_soup_evaluate_candidate.sh at all.
incus exec "$CONTAINER" -- bash -lc "
  set -e
  source /opt/soup/bin/activate 2>/dev/null || true
  cd '${REMOTE_WORKSPACE}'
  soup train
  soup ship
"

echo ""
echo "=== [4/4] Copying ONLY the resulting adapter back to the host ==="
LOCAL_CANDIDATE="${CANDIDATES_DIR}/${TIMESTAMP}"
mkdir -p "$LOCAL_CANDIDATE"
# Soup's own docs are the source of truth for the exact output dir name
# per template; adjust the remote path below if your template differs
# from the default ("chat") used by 09_setup_soup_finetune.sh.
incus file pull -r "${CONTAINER}${REMOTE_WORKSPACE}/output/." "$LOCAL_CANDIDATE/" \
  || {
    echo "Could not find the expected output/ dir inside the container.";
    echo "Check 'incus exec $CONTAINER -- ls ${REMOTE_WORKSPACE}' and adjust";
    echo "the incus file pull path above to match Soup's actual output layout.";
    exit 1;
  }

echo ""
echo "Done. Candidate adapter: $LOCAL_CANDIDATE"
echo "This directory is NOT used by anything yet. Next step (manual, on"
echo "purpose): 23_soup_evaluate_candidate.sh $LOCAL_CANDIDATE"
