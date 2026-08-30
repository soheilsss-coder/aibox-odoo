#!/bin/bash
# =============================================================================
# Soup (roadmap #58, checklist item 4: a MANUAL, not automatic, switch
# to replace the production model - only after human review).
#
# This is the ONLY script in the whole Soup pipeline that is allowed
# to modify /opt/start_vllm.sh. It refuses to run unless BOTH:
#   1. --confirm is passed explicitly (typing the flag is not enough
#      review by itself, see the interactive re-confirmation below)
#   2. --report points at a real report file from 23_soup_evaluate_
#      candidate.sh containing "SOUP_CANDIDATE_EVAL: PASS" - this
#      script actually parses the file for that marker, it does not
#      just trust the flag. A report with FAIL, or no report at all,
#      is refused, no override flag exists for that on purpose.
#
# It NEVER restarts vLLM itself. It writes a new start_vllm.sh (backing
# up the old one first) and prints the same manual Ctrl+C / restart
# instructions every other script in this pipeline uses - stopping and
# starting the production GPU process is always a human's hands on the
# keyboard, never a line in a script, per the GOLDEN RULE in
# 01_setup_base.sh.
#
# Usage:
#   ./24_soup_promote_candidate.sh \
#       --candidate /opt/soup-workspace/candidates/<timestamp> \
#       --report /opt/soup-workspace/reports/candidate-eval-<timestamp>.txt \
#       --confirm
# =============================================================================
set -euo pipefail

CANDIDATE_DIR=""
REPORT_FILE=""
CONFIRM=0

while [ $# -gt 0 ]; do
  case "$1" in
    --candidate) CANDIDATE_DIR="$2"; shift 2 ;;
    --report) REPORT_FILE="$2"; shift 2 ;;
    --confirm) CONFIRM=1; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [ -z "$CANDIDATE_DIR" ] || [ -z "$REPORT_FILE" ]; then
  echo "Usage: $0 --candidate <dir> --report <file> --confirm"
  exit 1
fi
if [ ! -d "$CANDIDATE_DIR" ]; then
  echo "Candidate directory not found: $CANDIDATE_DIR"
  exit 1
fi
if [ ! -f "$REPORT_FILE" ]; then
  echo "Report file not found: $REPORT_FILE"
  echo "Run 23_soup_evaluate_candidate.sh first - there is no way to"
  echo "promote a candidate that was never evaluated."
  exit 1
fi

echo "=== Verifying the report actually says PASS (not trusting flags alone) ==="
if ! grep -q "SOUP_CANDIDATE_EVAL: PASS" "$REPORT_FILE"; then
  echo "Report does not contain 'SOUP_CANDIDATE_EVAL: PASS'."
  echo "Refusing to promote. Re-run 23_soup_evaluate_candidate.sh and fix"
  echo "whatever failed - there is no override for this check."
  exit 1
fi
if grep -q "^\[FAIL\]" "$REPORT_FILE"; then
  echo "Report's overall line says PASS, but individual [FAIL] lines were"
  echo "found inside it (check the report manually - a hard gate script"
  echo "bug could theoretically produce this). Refusing to promote."
  exit 1
fi
echo "Report verified: $REPORT_FILE"

if [ "$CONFIRM" -ne 1 ]; then
  echo ""
  echo "This was a dry run (no --confirm passed). Nothing was changed."
  echo "Re-run with --confirm once you have personally read the report"
  echo "above, not just seen this script say PASS."
  exit 0
fi

echo ""
echo "You passed --confirm. Final interactive check (this cannot be"
echo "scripted around - it is not read from the flag):"
read -rp "Type the candidate directory name to proceed [$(basename "$CANDIDATE_DIR")]: " TYPED
if [ "$TYPED" != "$(basename "$CANDIDATE_DIR")" ]; then
  echo "Input did not match. Refusing to promote."
  exit 1
fi

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/opt/start_vllm.sh.bak-${TIMESTAMP}"

echo ""
echo "=== Backing up current /opt/start_vllm.sh -> $BACKUP ==="
cp /opt/start_vllm.sh "$BACKUP"

echo "=== Writing new /opt/start_vllm.sh (base model unchanged, LoRA added) ==="
cat > /opt/start_vllm.sh << VLLMEOF
#!/bin/bash
# Promoted by 24_soup_promote_candidate.sh on ${TIMESTAMP}.
# Candidate: ${CANDIDATE_DIR}
# Eval report: ${REPORT_FILE}
# Rollback: restore ${BACKUP} over this file (no adapter, base model
# only, exactly what was running before this promotion).
source /opt/vllm/bin/activate
export HF_HOME=/workspace/hf_cache
vllm serve cpatonn/Qwen3-30B-A3B-Instruct-2507-AWQ \\
  --host 127.0.0.1 --port 8000 \\
  --enable-auto-tool-choice --tool-call-parser hermes \\
  --served-model-name local-model \\
  --max-model-len 131072 \\
  --gpu-memory-utilization 0.6 \\
  --enable-lora --lora-modules candidate=${CANDIDATE_DIR}
VLLMEOF
chmod +x /opt/start_vllm.sh

echo ""
echo "============================================================"
echo " Written. NOTHING is running differently yet."
echo "============================================================"
echo "1. Go to the session running the OLD /opt/start_vllm.sh and stop"
echo "   it yourself: Ctrl+C, wait for full exit (GOLDEN RULE, never"
echo "   kill -9)."
echo "2. Start the new one yourself: /opt/start_vllm.sh"
echo "3. Rollback if anything looks wrong: cp $BACKUP /opt/start_vllm.sh"
echo "   then repeat steps 1-2 with that file."
