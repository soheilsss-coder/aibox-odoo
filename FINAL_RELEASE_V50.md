# v50 — Final Release Candidate

This release is additive on top of v49. No prior file may be deleted.

## What was completed in-code
- Final release audit and preservation gate.
- Workflow human-task mutation path hardened: workflow emits a durable event instead of directly creating `mail.activity` with `sudo()`.
- Deterministic model benchmark/promotion gate: registration alone cannot promote a model.
- Universal module certification matrix for Purchase, Stock, Accounting, Manufacturing, CRM, HR and the other declared modules.
- Fail-closed production promotion gate requiring every module gate and every external runtime dependency to PASS.

## Runtime truth
This ZIP is the **final release candidate**, not a falsely labelled production-certified build. Production certification can only be PASS after the supplied runtime harness is executed against the real Odoo/PostgreSQL/Redis/vector/LLM environment. Any missing runtime dependency or failed module gate blocks promotion.

## Required final certification command flow
1. Run the existing v48 runtime E2E harness against the target database.
2. Run module certification for every installed target module using `57_v50_module_certification_matrix.json`.
3. Run model benchmark/promotion gate for each candidate.
4. Produce a single JSON certification report.
5. Run `58_v50_production_gate.py report.json`.
6. Promote only when it exits 0 and reports `production_eligible: true`.
