# Release v47 — Auto Integration Certification

v47 is an additive continuation of v46. No v46 source file is removed.

Added:
- `48_auto_integration_certification.py` — live fail-closed certification entrypoint.
- `V47_AUTO_INTEGRATION_CERTIFICATION.md` — certification contract.
- `49_v47_release_integrity.py` — verifies v46→v47 preservation.
- `50_v47_static_security_tests.py` — verifies certification and execution invariants.

The release is **not** called Production Certified merely because these files exist. A real Odoo/PostgreSQL runtime must execute the certification runner and return PASS for every installed target.
