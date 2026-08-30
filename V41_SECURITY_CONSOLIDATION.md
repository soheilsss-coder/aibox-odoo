# v41 — Security & Control Plane Consolidation

This release is a hardening step on top of v40. It is **not** falsely marked as
full Production Certification until the runtime E2E suite is executed against
Odoo/PostgreSQL and the external services required by the roadmap.

## Implemented in this drop

- Generic `/api/rpc` is permanently disabled for Product use and returns `410`.
- Browser login remains on the secure HttpOnly `ai_session` cookie path.
- Browser session rotation/revocation is implemented in `ai.gateway.session`.
- Plaintext API-key storage is removed from the ORM model; the migration clears
  the legacy `key` column before upgrade.
- Production CORS fails closed when `AI_GATEWAY_ALLOWED_ORIGIN` is missing.
- Rate limiting is shared through Redis in production; local fallback is only
  permitted when explicitly enabled for development.
- Central execution gate remains the mandatory boundary for registered tools.
- Static CI checks are included for the P0 security invariants.

## Required production configuration

```text
AI_GATEWAY_ENV=production
AI_GATEWAY_ALLOWED_ORIGIN=https://your-frontend.example
AI_GATEWAY_REDIS_URL=redis://redis:6379/0
```

Do not set `AI_GATEWAY_ALLOW_LOCAL_LIMITER=1` in production.

## Still intentionally not called certified

The roadmap's final certification requires real runtime tests for:

- RBAC + ABAC + FGA + delegation
- durable/event-driven Workflow with human tasks and recovery
- complete Event Subscriber matrix
- SSO/OIDC/SAML + SCIM
- customer customization/deployment plane
- model benchmark/tuning/canary/rollback
- Purchase, Stock, Accounting, Manufacturing, CRM and HR E2E integration
- multi-worker, backup/restore and disaster-recovery tests

Those are gates, not claims that a model/file exists.
