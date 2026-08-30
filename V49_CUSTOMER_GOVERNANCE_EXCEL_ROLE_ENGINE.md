# v49 — Customer Governance + Excel Role Engine

v49 is additive on top of v48.

## Goals
- Complete the customer-facing Excel Role Engine as an explicit Validate -> Preview -> Approve -> Commit flow.
- Block unknown roles; there is no silent Employee fallback.
- Keep imports atomic with a PostgreSQL savepoint.
- Add an auditable SHA-256 file fingerprint and commit audit event.
- Make Access Review revocation change authorization facts (temporary/delegated grants), not merely record a decision.
- Harden SCIM so an IdP cannot create arbitrary global Odoo groups; only pre-mapped groups are SCIM-managed.

## Release invariant
No v48 file may be removed. v49 is accepted only when the release integrity check reports zero missing v48 files.

## Runtime boundary
This release is not declared Production Certified until the Odoo/PostgreSQL runtime harness executes successfully against a real customer database.
