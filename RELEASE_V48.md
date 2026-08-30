# v48 — Full Runtime E2E Harness

v48 is an additive continuation of v47.

### Added
- Live Odoo runtime certification harness for installed business modules.
- Fail-closed unknown-tool gateway probe.
- Per-module adapter, operation, capability, model, handler and unified-contract probes.
- Durable Event Outbox publish probe.
- RAG pipeline contract probe.
- Explicit opt-in guard for business mutations in disposable certification databases.
- Static tests for the runtime harness.

### Preservation
The v48 release must contain every file from v47 unchanged or extended; no
previous release file may be deleted.

### Certification boundary
Static checks and structural discovery are not production certification.
Live Odoo/PostgreSQL execution is required, followed by external-system and
module-specific E2E certification.
