# Final Release v57 — Direct Source Hardening / Source Complete / Fail-Closed

**This document supersedes `FINAL_RELEASE_V56.md` as the canonical release-status
document. `FINAL_RELEASE_V56.md` is kept in the archive unchanged as the
historical v56 record (see the superseded-notice banner now at its top) - it
is not deleted, only no longer canonical.**

## Basis audited
This release is a direct source-hardening pass on top of
`odoo-ai-rebuild-v56` (see `V57_HARDENING_NOTES.md` for the itemized diff).
It was reviewed against the actual source tree, not only against
release-status documents, and against the same two roadmap/audit documents
v56 was checked against:

- `مشکلات جدید.docx` — the 37-item security/architecture review plus Phases 1–16.
- `مشکلات جدید ۲.docx` — the follow-up audit covering Gateway Risk, unified
  Capability/Tool registry, real Business Adapters, Universal Module
  Certification, Calendar/Buzz/Hermes, Model Router/benchmark, Customer
  Control Plane, SSO/SCIM, Delegation, Excel Role Engine and production
  E2E gaps.

## What changed since v56 (see `V57_HARDENING_NOTES.md` for full detail)
1. Central execution gate: fixed a real runtime defect (`authorize()`
   referenced an undefined `binding` variable) - now resolves
   `ai.control.tool.binding` and falls back to the central risk registry
   for native `llm.tool` methods correctly.
2. Approval execution: fixed an unbound approval-target variable; row
   locking, immutable payload hashing, and one-shot execution checks
   retained.
3. Generic read adapter: added a strict read-only `generic_read` tool for
   newly installed Odoo models (ORM search/read only, `ast.literal_eval`
   domain parsing, capped clauses/result size, sensitive-field stripping,
   no create/write/unlink/method execution).
4. Telegram media: document/photo ingestion via `ir.attachment` with real-
   user ownership, and local voice transcription via pinned
   `faster-whisper==1.2.1`. Telegram remains a thin relay into the same
   user-authenticated AI gateway.
5. Chat attachment security: `/api/chat` now validates attachment ownership
   before associating an attachment with a user-owned thread.
6. RAG model routing: embedding requests now go through the benchmark-
   certified Model Router and reject embedding-dimension mismatches.
7. Deployment: Redis is installed by the native base installer and
   enabled/health-checked by the native start gate; vLLM installation requires
   an explicit validated `VLLM_VERSION` (fail-closed,
   not a silent default); `faster-whisper` pinned.
8. **Release integrity (this pass):** `SHA256MANIFEST.json` regenerated
   from the actual current source tree (392 entries, missing historical
   entries removed, current native install scripts, migration hook, upload
   policy, output firewall and contract tests included), independently
   reverified against disk with zero mismatches).
9. **Release metadata (this pass):** this document created so
   `RELEASE_CANDIDATE_VERSION.txt` (`v57`), `FINAL_RELEASE_STATUS.md`, and
   the canonical final-release document now agree - see the previous
   ambiguity this replaces in the superseded-notice on `FINAL_RELEASE_V56.md`.
10. **Install sequence documentation (this pass):** `INSTALL_READY.md`
    rewritten to state the full, literal, ordered command sequence
    (base setup → deploy → module install → service start → runtime
    certification) instead of implying `deploy.sh` alone performs a full
    deployment - see that file for the corrected sequence.

## Source completion
`FINAL_EXHAUSTIVE_SOURCE_AUDIT.py` checks 94 source contracts; `59_v57_hardening_audit.py`
adds the direct-source hardening checks above. Current result:

- **94/94 PASS** (`FINAL_EXHAUSTIVE_SOURCE_AUDIT.py`)
- **21/21 PASS** (`FINAL_PRODUCTION_GATE.py`)
- **13/13 PASS** (`tests/test_upgrade_contracts.py`)
- **PASS** (`59_v57_hardening_audit.py`)
- Python AST/syntax: PASS · XML parse: PASS · Shell syntax: PASS
- SHA256MANIFEST.json: PASS (392/392, zero mismatch, reverified this pass)
- No active generic ORM assistant assignment
- `/api/rpc`: permanent HTTP 410 tombstone
- Central Capability → Tool → Policy → Risk → Approval → Commit-Time → Gateway path
- Temporary access uses Role Assignment/Grant records; never edits permanent `res.groups.users`
- Approval payload/target/policy snapshot is immutable; approval history is durable
- Time-of-commit authorization and target re-check are mandatory
- Browser authentication uses secure session cookies; API keys are M2M/agent credentials only
- API key hash/expiry/rotation/revocation history is stored without plaintext secrets
- RBAC + ABAC + FGA and delegation are connected to the central authorization engine
- Memory is canonical encrypted Odoo ORM storage; old external/SQLite paths are inactive legacy artifacts
- Excel Role Policy Engine uses Department + Position + Job Level + Manager + Location + Employment Type and blocks unknown/unmatched roles
- Excel output is a non-secret audit manifest only
- Event Bus + nine subscriber classes are present
- Workflow Cron is recovery/deadline-only
- RAG indexing is asynchronous and ACL/FGA-filtered, now routed through the Model Router
- Model Registry/Router is benchmark-gated
- Hermes exposes only the gateway identity/capability/chat surfaces
- Customer Control Plane has its required source models/API and a dedicated frontend overview
- SSO OIDC/SAML + SCIM user/group provisioning surfaces are present; SCIM role mappings restricted to product roles
- Universal module certification is fail-closed

## Important runtime boundary (unchanged from v56 — still true)
A ZIP/source audit cannot honestly certify a live installation. The
following require the actual customer runtime and are deliberately
**fail-closed rather than fabricated as PASS**:

`Odoo + PostgreSQL + Redis + pgvector + vLLM + model artifacts + IdP + Buzz + Telegram + real customer ERP modules + real hardware/DGX`

Run `48_auto_integration_certification.py` inside the real Odoo shell. It
must PASS every installed target module before production promotion.
Model promotion must also pass the benchmark gate. This is not an
unfinished source requirement; it is the required live certification
stage from the roadmap - see `INSTALL_READY.md` for the exact command
sequence to reach that stage.
