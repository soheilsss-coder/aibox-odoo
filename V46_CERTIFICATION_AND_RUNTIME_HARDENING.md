# Release v46 — Certification Gate + Runtime Hardening

v46 is strictly additive on top of v45. No previous module or source file is intentionally removed.

## v46 goals
- Make the unified Capability → Tool → Risk contract mandatory at execution time.
- Make business-action idempotency atomic at the database boundary.
- Make approval execution concurrency-safe and bind replay to the immutable approved arguments.
- Make module certification fail closed: existence of a component is not enough; every required contract must be present and internally consistent.
- Add a deterministic certification manifest for Purchase, Stock, Accounting, Manufacturing, CRM, HR and other registered modules.
- Harden SCIM group provisioning so a tenant cannot mutate arbitrary global Odoo groups.

## Certification rule
A module is production-eligible only if every required check is PASS. Warnings are not promotion.

The runner distinguishes structural checks, contract checks, and runtime checks. Runtime checks are explicitly marked NOT_RUN until a live Odoo/PostgreSQL environment executes them. A module with any NOT_RUN runtime check is **not certified**.

## Preservation invariant
The release is produced by copying v45 and applying only additive/targeted edits. The build verification checks that all v45 source paths remain in v46.
