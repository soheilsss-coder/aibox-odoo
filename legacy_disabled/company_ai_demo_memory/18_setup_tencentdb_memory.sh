#!/bin/bash
# =============================================================================
# TencentDB Agent Memory - MemoryCore setup + verification.
#
# HONEST STATE (as of writing this): public docs/blog posts describe
# MemoryCore as running independently with an HTTP Gateway + Python SDK
# for "custom applications" (not just OpenClaw/Hermes), but I could not
# verify from here whether MemoryCore itself needs Docker or has a
# from-source/npm path - the box's known constraint is: no Docker
# (nested virtualization disabled). This script does NOT guess - it
# clones the real repo and reads ITS OWN current install docs, then
# tells you exactly what's true right now, because the project is very
# new (open-sourced May 2026) and instructions may already have moved
# past what any blog post describes.
# =============================================================================
set -e

INSTALL_DIR="/opt/tencentdb-agent-memory"

echo "=== [1/3] Node.js version check (project requires >= 22.16.0) ==="
if command -v node > /dev/null; then
  NODE_VERSION=$(node -v)
  echo "Found: ${NODE_VERSION}"
else
  echo "Node.js not found. Installing Node.js 22 LTS via NodeSource..."
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi

echo ""
echo "=== [2/3] Cloning the actual repo (so we read ITS current docs, not a cached summary) ==="
if [ ! -d "$INSTALL_DIR" ]; then
  git clone https://github.com/TencentCloud/TencentDB-Agent-Memory.git "$INSTALL_DIR"
else
  echo "Already cloned - pulling latest."
  git -C "$INSTALL_DIR" pull
fi

echo ""
echo "=== [3/3] Checking whether a Docker-free path exists for MemoryCore specifically ==="
echo "Searching the repo's own docs for a non-Docker MemoryCore install path..."
echo ""
FOUND_NONDOCKER=0
for f in "$INSTALL_DIR"/MemoryCore/README*.md "$INSTALL_DIR"/INSTALL*.md "$INSTALL_DIR"/README*.md; do
  if [ -f "$f" ]; then
    if grep -qiE "npm (run )?(build|start)|node (dist|index|server)|without docker|no docker" "$f" 2>/dev/null; then
      echo "Possible non-Docker instructions found in: $f"
      FOUND_NONDOCKER=1
    fi
  fi
done

echo ""
echo "======================================================================"
if [ "$FOUND_NONDOCKER" = "1" ]; then
  echo "A non-Docker path MIGHT exist - open the file(s) listed above and"
  echo "read the exact steps yourself before running anything else; this"
  echo "script deliberately does NOT auto-run untested install steps from"
  echo "a project this new without a human reading them first."
  echo ""
  echo "Once MemoryCore is running (however you started it), confirm with:"
  echo "  curl http://localhost:8125/v3/tools/list"
  echo "If that returns JSON, note the port and continue to the Odoo side:"
  echo "  see custom_addons/company_ai_demo/models/agent_memory.py, which"
  echo "  is already wired to call this - just confirm MEMORY_CORE_URL"
  echo "  matches (env var, defaults to http://127.0.0.1:8125)."
else
  echo "No clearly non-Docker path was found in this pass. That means, as"
  echo "of right now, MemoryCore most likely needs Docker for this repo"
  echo "version - which conflicts with this box's known constraint (no"
  echo "nested virtualization). Before giving up on it, check three things"
  echo "yourself (I cannot verify these from here):"
  echo "  1. ${INSTALL_DIR}/MemoryCore/ - is there a package.json with a"
  echo "     'build'/'start' script that runs on plain Node.js?"
  echo "  2. Does 'docker' on this box actually fail, or does it only fail"
  echo "     for nested-VM scenarios? Plain 'docker run' on bare Linux"
  echo "     does NOT require nested virtualization at all - only running"
  echo "     Docker INSIDE another VM without nested-virt support fails."
  echo "     Test directly: docker run hello-world"
  echo "  3. podman (Docker-CLI-compatible, no persistent daemon, often"
  echo "     works where Docker doesn't in cloud-rental environments):"
  echo "     apt-get install -y podman && podman run hello-world"
fi
