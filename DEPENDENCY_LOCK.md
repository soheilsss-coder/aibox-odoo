# Immutable native dependency contract

The package never silently chooses a floating production Odoo, Python, vLLM,
PostgreSQL/pgvector, Redis, or model artifact. Production installation is
native/bare-metal only; Docker and compose are not part of the deployment
path.

Application Python pins are in `requirements.lock` and frontend pins are in
`frontend/package-lock.json`.

## Required production values

Set and review these exact environment variables before running
`00_final_production_install.sh`:

- `ODOO_COMMIT_SHA` — immutable Odoo source commit
- `ODOO_LLM_REPO` and `ODOO_LLM_COMMIT_SHA` — immutable AI addon source
- `VLLM_VERSION` — validated, immutable vLLM Python package version
- `PYTHON_RUNTIME_VERSION` and `NODE_RUNTIME_VERSION`
- `PGVECTOR_PACKAGE` — native PostgreSQL pgvector package name
- `MODEL_REVISION_QWEN`
- `MODEL_REVISION_GLIMMER`
- `MODEL_REVISION_VISION`
- `MODEL_REVISION_EMBEDDING`

The native installer consumes `PGVECTOR_PACKAGE` in its apt transaction and
installs vLLM with `vllm==${VLLM_VERSION}`. No floating git branch or
`pip install -U` is permitted by the production gate. PostgreSQL, Redis and
vLLM model-serving service versions must be recorded in
`DEPLOYMENT_ARTIFACTS.lock` for the target host before runtime certification.
