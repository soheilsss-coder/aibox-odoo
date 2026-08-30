# Canonical Requirements and Line-by-Line Audit Map

This file is the consolidated interpretation of the roadmap/release documents shipped in v52. Historical release notes are retained for traceability, but this file and `FINAL_RELEASE_V54.md` are the canonical final status.

## Security chain

Every AI mutation must resolve through:

`Authorization → Capability → Policy/Data Classification/FGA → Risk → Approval when required → Execution Gate → Unified Operation Registry → Reviewed Adapter → ERP`

No generic RPC fallback is permitted.

## Identity and roles

Role sources are represented centrally as:

1. direct user role;
2. department role;
3. position/job role;
4. temporary grant;
5. delegated grant.

Temporary/delegated grants are authorization facts and never mutate Odoo group membership.

## Documents and RAG

Document visibility supports company, group, team, department, personal, restricted and confidential scopes. RAG first resolves readable `company.document` records through Odoo authorization and only then executes the raw pgvector query against those IDs.

FGA supports explicit user/resource relations and time-bounded project/folder/resource relations.

## Event architecture

The durable PostgreSQL outbox is authoritative. Event Bus subscribers are explicit and independently registered for Workflow, Audit, Notification, Buzz, Telegram, Memory, RAG, Calendar and AI. Event/RAG processing uses dedicated workers; scheduled jobs are limited to maintenance/recovery semantics.

## Memory

The Odoo memory record is the only authoritative provider. Values are encrypted with the deployment-managed Fernet key. Retention, deletion, tenant/company boundary and residency metadata are stored with the record. The TencentDB adapter, if enabled later, is an external indexing/provider integration and is not an authorization source or fallback database.

## Excel

The only valid path is:

`Parse → Validate → Normalize → Preview → Approve → Atomic Commit`

Unknown roles block the import. Existing users are not silently overwritten. Passwords, API keys, bearer tokens and reset tokens are never exported.

## Enterprise identity

OIDC uses authorization-code flow, state, nonce, token exchange, JWKS signature validation and issuer/audience checks before mapping an external subject to a company-scoped Odoo user/session. SAML has a dedicated ACS validation path. SCIM bearer tokens are hashed and company-scoped; SCIM groups must be pre-mapped and cannot create arbitrary global groups.

## Deployment

The production installer requires immutable Odoo/PostgreSQL+pgvector/Redis/vLLM/model/frontend artifact revisions. It installs the shipped addons, configures TLS/backups/frontend and starts the durable Event/RAG workers. Missing infrastructure artifacts fail the install instead of silently selecting floating versions.

## Final test boundary

The only remaining state is **runtime execution**, not missing source architecture. A production promotion is blocked until the live environment proves the full module certification matrix and external integrations.
