# v58 Final Release Status

**Release candidate:** `v58` (`RELEASE_CANDIDATE_VERSION.txt`)

## Source verification

The source release currently passes:

- `22/22` upgrade contract tests.
- `25_static_audit.py`, `28_release_audit.py`, `29_production_e2e.py`.
- `50_v47_static_security_tests.py` and `59_v57_hardening_audit.py` (`21/21`).
- `FINAL_PRODUCTION_GATE.py` (`94` checks) and
  `FINAL_EXHAUSTIVE_SOURCE_AUDIT.py`.
- Queue self-test (`10/10`) and inference-policy self-test.
- Native frontend dependency install, Vite build in a temporary directory,
  and high-severity dependency audit.
- SHA256 release manifest (`411` listed entries, zero hash mismatch).

## v58 product changes

- Native systemd lifecycle for chat, embedding and vision vLLM services;
  model weights and build/cache artifacts stay outside the repository.
- Configurable, benchmark-gated model routing with an explicit registry
  promotion transition, health state, bounded local queue and Redis-backed
  cross-worker inference leases.
- Durable approval API consolidated to one canonical route family, with
  company-scoped approval records, integrity re-sealing on upgrade and
  re-authorization at decision/execution time.
- Company-scoped documents, RAG chunks and index snapshots; hybrid retrieval
  filters authorization before SQL ranking and filters the active index
  revision.
- Real API-backed Calendar, Tasks, Documents, Approvals, Notifications,
  Integrations and Chat surfaces with visible loading/error/empty states.
- Universal automatic module onboarding: model/menu/view/security-group and
  scope discovery, bounded read-only contracts, metadata-only change outbox,
  event mappings, and explicit `adapter-required` certification for mutations.
- Live installed-module certification harness for reviewed adapters,
  capabilities, risk contracts, handlers and promotion status.

## Runtime boundary

`RUNTIME_CERTIFICATION_REQUIRED: YES`.

This checkout has no running target Odoo/PostgreSQL/Redis/pgvector/vLLM/IdP,
DGX or external-integration stack. Therefore this report does **not** claim
production-ready status, zero defects in an untested deployment, or a user
capacity number. Production promotion requires, on the real native target:

1. `62_v58_module_certification.py` and `48_auto_integration_certification.py`
   in an Odoo shell, with every installed business module passing.
2. `60_v58_llm_benchmark.py` for representative chat, tool, RAG, approval,
   vision and embedding scenarios, enriched with same-run GPU, queue,
   PostgreSQL and Redis evidence.
3. `61_v58_capacity_gate.py` with measured latency/error thresholds and an
   explicitly recorded workload/configuration.
4. The end-to-end security, failure-recovery and upgrade probes in
   `PRODUCTION_E2E_RUNBOOK.md`.

Until those steps pass, the correct release state is **source-verified,
runtime-blocked**.
