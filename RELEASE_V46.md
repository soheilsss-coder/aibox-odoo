# Release v46 — Certification Gate + Runtime Hardening

## What v46 changes
- Keeps the complete v45 tree and all previous modules.
- Makes `ai.integration.operation` the mandatory execution contract for Capability → Tool → Risk.
- Cross-checks the unified operation against the legacy risk registry and active capability before execution.
- Adds atomic PostgreSQL idempotency claiming with `ON CONFLICT DO NOTHING`.
- Makes high-risk approval decisions row-locked and binds replay to the exact stored tool arguments.
- Adds a payload integrity hash to approvals while retaining the old approval hash for backward compatibility.
- Makes the universal certification runner fail closed: structural presence alone can never certify production.
- Adds explicit runtime certification gates for gateway, authorization, risk/approval, event delivery, workflow recovery, RAG ACL, frontend capabilities and audit.
- Restricts SCIM group management to explicitly company-mapped groups.

## Preservation guarantee
v46 was created by copying v45 and applying targeted changes. No previous module is intentionally removed. `46_v46_manifest_check.py` checks the preserved module set; the release build also compares the complete v45/v46 file manifests.

## Certification truth
A result of `PASS` is reserved for a live runtime where every structural, contract and runtime check passes. Static tests are not a substitute for Odoo/PostgreSQL E2E certification.
