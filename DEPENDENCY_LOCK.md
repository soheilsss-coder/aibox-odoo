# Immutable dependency contract

The package never silently chooses a floating production Odoo/vLLM/model artifact.
Set immutable image/git digests in the deployment environment or compose override before production installation.

Application pins are in `requirements.lock`.

Required infrastructure artifacts:
- Odoo 18.0 image or immutable source commit
- PostgreSQL 16 + pgvector image digest
- Redis 7.x image digest
- vLLM image digest
- Chat/reasoning/vision/embedding model revisions
- Frontend Node build artifact digest


## Immutable artifact contract (fail-closed)
Production must provide these exact environment variables before `00_final_production_install.sh` can certify the runtime:
- `ODOO_COMMIT_SHA`
- `ODOO_LLM_COMMIT_SHA`
- `VLLM_IMAGE_DIGEST`
- `PYTHON_RUNTIME_VERSION`
- `NODE_RUNTIME_VERSION`
- `MODEL_REVISION_QWEN`
- `MODEL_REVISION_GLIMMER`
- `MODEL_REVISION_VISION`
- `MODEL_REVISION_EMBEDDING`
- `PGVECTOR_IMAGE_DIGEST`
No floating git branch or `pip install -U` is permitted by the production gate.
