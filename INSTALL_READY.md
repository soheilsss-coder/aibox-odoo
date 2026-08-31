# Install-ready release

This archive is the consolidated pre-install release. All roadmap code paths are shipped together; no manual source patching is required before installation.

## What `deploy.sh` actually does (and does not do)
`deploy.sh` is **only** two things: (1) it copies `custom_addons/*` into
`$ODOO_ADDONS_PATH`, and (2) it runs the static `FINAL_PRODUCTION_GATE.py`
check plus, in production mode, verifies immutable-artifact env vars are
set. **It does not install or start Odoo, PostgreSQL, Redis, or vLLM, and
it does not run Odoo module installation (`-i`).** Running `deploy.sh`
alone gives you validated source sitting in the addons path - nothing is
live yet. This distinction was previously unclear in this document; the
literal step order below is the fix.

## Install — literal, ordered command sequence
Run these in exactly this order. Each step is a real script in this
archive; none of them are optional shortcuts for each other.

1. **Provision the native runtime stack** — pinned Odoo 18 and odoo-llm
   source, PostgreSQL/Redis OS packages (when `INSTALL_OS_DEPS=1`), vLLM,
   and the AI addon Python dependencies. No Docker is used:
   ```bash
   export ODOO_COMMIT_SHA="<immutable Odoo commit>"
   export ODOO_LLM_REPO="<pinned odoo-llm repository>"
   export ODOO_LLM_COMMIT_SHA="<immutable odoo-llm commit>"
   export VLLM_VERSION="<validated GB10-compatible vLLM release>"
   export PGVECTOR_PACKAGE="postgresql-16-pgvector"
   export ODOO_ADMIN_PASSWORD="<secret supplied by the secret manager>"
   INSTALL_OS_DEPS=1 ./01_setup_base.sh
   ```
   This step installs the pinned Odoo/vLLM Python runtime and stages native
   systemd units. It does not start services; `deploy.sh` below is still only
   the source-copy/static-gate step.

2. **Set the required environment variables** before touching `deploy.sh`:
   ```bash
   export AI_GATEWAY_ALLOWED_ORIGIN="https://YOUR-FRONTEND-DOMAIN"
   export AI_GATEWAY_ENV="production"
   ```
   In production mode (`AI_GATEWAY_ENV=production`), `deploy.sh` will also
   require: `ODOO_COMMIT_SHA`, `ODOO_LLM_COMMIT_SHA`, `VLLM_VERSION`,
   `PYTHON_RUNTIME_VERSION`, `NODE_RUNTIME_VERSION`, `PGVECTOR_PACKAGE`,
   `MODEL_REVISION_QWEN`, `MODEL_REVISION_GLIMMER`, `MODEL_REVISION_VISION`,
   `MODEL_REVISION_EMBEDDING` - it fails closed (refuses to run) if any of
   these immutable native-artifact pins are missing,
   rather than silently deploying unpinned versions. See
   `DEPLOYMENT_ARTIFACTS.lock` for where to record the actual values once
   you've validated them for your target hardware.

3. **Copy addons into place and run the static production gate:**
   ```bash
   ./deploy.sh
   ```
   (See "What `deploy.sh` actually does" above - this is a copy + static
   check step, not a service install.)

4. **Install the Odoo modules for real** (this is the step that actually
   turns the copied addon source into running Odoo modules):
   ```bash
   ./02_install_modules.sh
   ```
   For a subsequent registry upgrade, use `AI_MODULE_MODE=upgrade
   ./02_install_modules.sh`; the mode is also accepted by the consolidated
   `00_final_production_install.sh` entrypoint.
   > `ai_business_tools` hard-depends on the Odoo **Manufacturing
   > (mrp)** application (its role templates imply
   > `mrp.group_mrp_manager`). `mrp` is in the installer's `-i` module
   > list, so make sure the Odoo artifact you ship contains it, or this
   > install step aborts.

5. **Start the native services** (Odoo and durable event/RAG workers;
   start the separately configured vLLM model units only after the GB10
   memory/latency plan has been validated):
   ```bash
   ./03_start_all.sh
   ```
   `03_start_all.sh` enables PostgreSQL/Redis and the checked-in systemd
   units. vLLM is installed by step 1 but model serving is intentionally a
   runtime capacity decision, not a hard-coded model/weight download.

6. **Run the deterministic acceptance suite** (ORM-level permission/
   security scenarios, no live traffic needed):
   ```bash
   source /opt/odoo/venv/bin/activate
   /opt/odoo/src/odoo/odoo-bin shell -c /etc/odoo/odoo.conf -d company_ai < 05_acceptance_tests.py
   ```

7. **Run full runtime certification** on the real target environment -
   this is the stage that actually exercises Odoo + PostgreSQL + Redis +
   pgvector + vLLM + Buzz + Telegram + SSO/SCIM + every installed ERP
   module together, and is what the release documents (`FINAL_RELEASE_V57.md`,
   `FINAL_RELEASE_STATUS.md`) mean by "runtime certification required":
   ```bash
   python3 48_auto_integration_certification.py
   ```
   plus the full checklist in `PRODUCTION_E2E_RUNBOOK.md` (auth matrix,
   workflow scenarios, file/RAG ACL scenarios, Telegram/Buzz scenarios,
   ERP module certification per installed app, and model benchmark/
   promotion gate). Production promotion requires every check there to be
   PASS - none of it is claimed as already passing inside this archive,
   because none of it can honestly be tested without the real stack
   running (see `FINAL_RELEASE_V57.md`'s "Important runtime boundary").

The package is intentionally fail-closed: it will not invent production credentials, wildcard CORS, floating model promotion, or fake runtime PASS results.

## What remains after installation
Only environment-dependent execution gates: database migration/install, real Odoo module discovery, Redis multi-worker tests, vLLM/Hermes/tool calling, SSO/SCIM against the customer IdP, Telegram/Calendar/Buzz connectivity, RAG negative ACL tests, backup/restore and DGX/model benchmarks. These are tests of the shipped code, not missing roadmap source files.
