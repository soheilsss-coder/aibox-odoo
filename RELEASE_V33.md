# Release v33 — Universal Integration & Enterprise Hardening

This release implements the remaining architecture from the supplied project plan.

## Implemented
- Central Authorization Engine with RBAC + policy scopes + FGA relations.
- Capability Registry is the common language between AI, frontend, workflow, audit and ERP.
- Universal Integration Registry and Odoo module discovery.
- Reviewed adapters for HR, Inventory, Accounting, Purchase, Sales, CRM, Project, Manufacturing and Documents.
- Dynamic **read-only** capabilities are discovered; write/approve operations require reviewed capabilities.
- Durable domain-event outbox and dispatcher with low-risk workflow reactions.
- Async RAG indexing jobs; embedding is no longer performed inside document create/write transactions.
- Enterprise ORM-backed memory with company/department/personal scopes and retention cleanup. SQLite is no longer the authoritative memory store.
- Optional TencentDB/MemoryCore enrichment remains isolated from authorization decisions.
- Browser login now uses an HttpOnly secure session cookie; API keys remain for service/M2M/agent identities.
- Generic RPC is disabled by default for the product surface.
- Temporary/delegated access is limited to product-defined roles and preserves permanent memberships.
- Approval records have integrity hashing, expiry, immutable core fields and commit-time authorization checks.
- Sensitive attendance, identity and access-review tools are restricted.
- Excel onboarding blocks unknown roles and supports safe deterministic inference from explicit department/job-title rules.
- Model Registry + Router for chat/reasoning/vision/embedding, with Qwen AWQ represented as the production chat profile and Glimmer as a configurable reasoning candidate.
- Hermes/Buzz bridge no longer exposes raw ORM/RPC; it exposes bootstrap, capability discovery and policy-aware chat.
- Customer deployment wizard and tuning release gate added.

## Verification performed in this environment
- Python AST parsing: PASS
- Python bytecode compilation: PASS
- XML parsing: PASS
- Manifest parsing: PASS
- CSV parsing: PASS
- Shell syntax (`bash -n`): PASS
- Node syntax checks for plain JS/Vite config: PASS
- Existing static security audit: PASS
- Forbidden generic assistant assignment audit: PASS
- Query-string API-key audit: PASS
- ZIP build/integrity: will be checked after packaging

## Not honestly claimed here
A real Odoo/PostgreSQL/vLLM deployment, browser session, Buzz runtime, pgvector, or live model endpoint is not available in this execution environment. Therefore this release does not claim a live end-to-end production test that was not actually run. The package contains the code, tests, installers and release gates required for that environment.
