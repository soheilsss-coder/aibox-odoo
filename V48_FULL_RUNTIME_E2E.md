# v48 — Full Runtime E2E Certification Harness

v48 continues v47 additively. No previous release file is removed.

## Purpose

v47 established Universal Auto Integration Certification. v48 adds a live
Odoo runtime harness that proves the control-plane path against installed
business modules instead of treating model/file presence as runtime proof.

## Required runtime chain

`Install → Discover → Models → Groups → Capabilities → Adapter → Tool → Authorization → Risk → Approval → Commit → Event → Workflow → Notification → Audit → AI → RAG → Frontend → Security → E2E`

The harness is fail-closed. Missing services, missing contracts, unknown-tool
acceptance, or failed probes block the release.

## Safety

Business mutations are disabled by default. Set
`AI_V48_ALLOW_BUSINESS_MUTATIONS=1` only in a disposable certification
PostgreSQL database after the control-plane probes pass. This prevents a
certification run from silently creating purchase orders, posting invoices,
confirming transfers, or otherwise mutating production data.

## Run

```bash
odoo-bin shell -c /etc/odoo.conf -d <certification_db> < 51_v48_runtime_e2e.py
python3 52_v48_runtime_e2e_tests.py
```

A PASS means the live control-plane probes passed. It does **not** by itself
claim DGX/vLLM/Buzz/Telegram external-system certification; those remain
separate environment tests.
