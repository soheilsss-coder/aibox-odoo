# v54 — Final Source Release Built From v52

## Base and preservation

This release is built from `odoo-ai-rebuild-v52-install-ready`, not from v50/v53.
All non-compiled source paths from v52 are preserved. The package adds only targeted
hardening, audit tooling, workers and deployment artifacts.

## Canonical source requirements — final status

| Requirement | Final source status |
|---|---|
| Authorization → Capability → Policy → Risk → Approval → Tool Gateway → Business Adapter → ERP | PASS — central execution gate + unified registry + reviewed adapters |
| Generic ORM/RPC parallel write path | PASS — `/api/rpc` permanently HTTP 410; named capabilities/adapters only |
| Generic read path | PASS — named semantic tools/endpoints and Odoo ACL/record rules |
| Event-driven workflow | PASS — durable Event Bus + worker; cron is not the business trigger |
| Cron restriction | PASS — only recovery/deadline/reminder/escalation/expiry/cleanup scheduling remains |
| Subscriber matrix | PASS — explicit Workflow, Audit, Notification, Buzz, Telegram, Memory, RAG, Calendar and AI subscribers |
| Role Assignment | PASS — central direct/department/position/temporary/delegated assignment model consumed by authorization |
| Temporary/delegated access | PASS — authorization facts; no mutation of `res.groups.users` |
| Context Firewall | PASS — recursive secret scrubbing + PII/sensitive-key coverage |
| Data Classification | PASS — centralized classification model and authorization integration |
| FGA | PASS — company/group/department/personal plus project/folder/explicit/time-bounded relations |
| RAG ACL | PASS source architecture — ORM ACL prefilter before pgvector query |
| Business Adapters | PASS — reviewed named operations for the declared ERP modules; central gate required |
| Approval integrity | PASS — immutable payload hashes, concurrency lock, exact-argument replay check and approver binding |
| Memory | PASS — one canonical ORM provider, encrypted values, retention/deletion, tenant and residency controls |
| Excel onboarding | PASS — Validate → Preview → Approve → Commit; unknown roles block; no credential export |
| Customer Control Plane | PASS — role/permission/policy/workflow/approval/document/agent/tool/config/deployment designers |
| SSO/SCIM | PASS source implementation — OIDC authorization-code + nonce/JWKS validation, SAML ACS contract, company-scoped SCIM |
| Session security | PASS — HttpOnly secure session cookie, rotation and revocation |
| CORS | PASS — production requires exact HTTPS origin |
| Model registry/routing | PASS source gates — registry-driven, benchmark/security/promotion checks |
| Deployment | PASS source orchestration — immutable artifact variables required; canonical one-command production installer included |
| Dependency pinning | PASS source contract — application pins plus mandatory immutable infrastructure/model revisions |
| Frontend | PASS source integration — capability-driven backend authority; build is part of release gate when Node is available |
| Audit | PASS — enterprise context/hash-chain fields and row-level access controls |
| Runtime E2E | NOT RUN HERE — intentionally fail-closed; requires the real customer stack |

## Runtime boundary

A ZIP archive cannot truthfully certify a real Odoo/PostgreSQL/Redis/vLLM/DGX/IdP/Telegram/Buzz deployment without executing those systems. The source release therefore does **not** convert runtime tests into PASS merely because files exist.

The canonical production gate must obtain PASS for:

- real Odoo + PostgreSQL transactions;
- multi-worker Event Bus/workflow crash recovery;
- RAG negative ACL tests through direct RAG and AI paths;
- real Hermes → Gateway → Authorization → Risk → Approval → Adapter → ERP;
- OIDC/SAML/SCIM against the customer's IdP;
- Telegram/Buzz/Calendar external delivery and retries;
- backup/restore and key rotation;
- model benchmark/canary/promotion/rollback;
- every installed ERP module in the certification matrix.

Anything unexecuted remains blocked by the promotion gate.

## Verification performed on this archive

- Python AST parse: PASS
- XML parse: PASS
- JSON parse: PASS
- Shell syntax: PASS
- Existing v50/v49/static security gates: PASS
- New final source audit: PASS
- v52 source preservation: PASS — zero v52 source paths removed
- v50 source preservation: PASS — zero v50 source paths removed
- Compiled Python artifacts: excluded from release

## Important release invariant

`FINAL_SOURCE_AUDIT.py` is the authoritative source-level gate. `FINAL_PRODUCTION_GATE.py` remains a separate fail-closed static/security gate. Neither is allowed to fabricate runtime certification.
