# Release v35 — Enterprise Automation Completion Pack

This release is built on v34 and adds the missing production contracts identified in the v34 review.

## Added

- Durable workflow model with queued/running/waiting/completed/failed states, retries, backoff and DB idempotency keys.
- Event-to-workflow enqueue hook in the existing outbox dispatcher.
- Collaboration workspaces and messages for private/team/department/company scopes with membership checks.
- Secure file-intelligence job model that records SHA-256, MIME type and requester before parsing/indexing.
- Official correspondence templates and required-field validation before generation/approval.
- Production certification records and privileged release-certification endpoint.
- Workflow, collaboration, correspondence and production API contracts.
- Structural production contract test suite.
- Installer now installs the new addons and pins document-generation Python dependencies.

## Existing v34 capabilities retained

- AI Control Plane / Capability / Risk / Authorization
- Module Discovery / Integration Registry
- RAG ACL gating / ORM memory
- Telegram/Buzz bridges
- Role-aware agents
- Artifact generation
- File analysis
- Semantic APIs
- Customer deployment tooling
- Model registry and tuning release gate

## Important certification boundary

This release does **not** claim that live Odoo/PostgreSQL/vLLM/Buzz/Telegram services were executed inside this build environment. The included tests validate Python/XML/manifest/security/contract integrity. A real customer certification must run the E2E suite against the actual Odoo database, vLLM model servers, Buzz, Telegram and DGX GB10 runtime.

A release must not be marked `Certified` merely because structural tests pass; live checks must populate `ai.production.check` and only then should `ai.release.certification` be promoted.
