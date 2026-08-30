# v45 — Customer Control Plane + Security Consolidation

## Implemented
- Hard 410 shutdown of generic `/api/rpc`; the legacy route can no longer execute.
- Workflow `activity` action no longer mutates arbitrary ERP records with `sudo()`; it emits `workflow.activity.requested` and a dedicated subscriber creates only `mail.activity`.
- Customer configuration profiles for role/capability/approval/document/agent/tool/workflow policy.
- Delegation model with time bounds, explicit capability/resource, revocation and delegator-authority check.
- Access review and decision records.
- OIDC/SAML provider metadata with external-secret references only.
- SCIM 2.0 bearer-token model with hashed tokens and company-scoped Users/Groups provisioning endpoints.
- Static security tests for the above invariants.

## Certification boundary
This release is **not** called Production Certified until Odoo runtime tests prove:
1. SCIM group membership changes are tenant/company isolated.
2. OIDC/SAML token validation is performed by a trusted provider library and mapped to the correct tenant/user.
3. Delegation is evaluated by the same central authorization engine as ordinary grants.
4. Purchase/Stock/Accounting/Manufacturing/CRM/HR E2E certification passes with multiple workers.
5. DR/backup/restore, Redis rate limiting, audit immutability and key rotation tests pass.

Source roadmap requirements are preserved from the supplied "مشکلات جدید (1).docx".
