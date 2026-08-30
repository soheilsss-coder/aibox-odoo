# Integration hardening in this build

This build adds a central `ai_control_plane` addon and closes the main integration/security gaps found during the code audit.

## What is now wired

- Installed-module discovery and integration registry (`ai.control.module`).
- Capability registry and per-user effective capability endpoint (`/api/capabilities`).
- Integration registry endpoint (`/api/control-plane/integrations`) plus privileged manual sync (the semantic admin surface keeps `/api/integrations`).
- Five-minute module discovery repair job.
- Durable domain-event table (`ai.control.event`) with event publishing from leave/task/approval business actions.
- Chat tool surface is deny-by-default: only tools present in the explicit risk registry are attached; generic framework ORM tools are excluded.
- Per-user tool filtering is applied again when a chat thread is created/refreshed.
- Generic gateway create/write/unlink is disabled for non-system users; generic RPC also fails closed when its policy module is absent.
- Temporary/delegated access records remember whether they actually added membership, so revocation cannot remove a pre-existing role; concurrent grants are respected.
- Temporary access is restricted to the product role allowlist.
- Approval records protect their immutable action identity fields and reject already-decided/missing targets at commit time.
- Ambiguous task assignees no longer silently choose the first matching user.
- Leave requests reject an inverted date range.
- Production CORS no longer defaults to `*`; set `AI_GATEWAY_ALLOWED_ORIGIN` to the exact frontend origin.

## Validation performed in this environment

- Python syntax compilation: passed.
- XML parsing: passed.
- Shell syntax (`bash -n`): passed.
- Static searches for the previously dangerous assistant-wide generic-tool assignment and API-key query-string fallback: no matches.

## Important runtime validation

The supplied archive does not include an Odoo runtime, PostgreSQL, vLLM, or the third-party LLM addons, so this environment cannot execute an actual Odoo install or end-to-end browser/LLM test. The deployment package therefore includes the code and static checks, but production acceptance must still run against the exact pinned Odoo/LLM environment.

## Required production configuration

- `AI_GATEWAY_ALLOWED_ORIGIN=https://<customer-frontend-origin>`
- HTTPS/TLS enabled.
- A real identity provider/session strategy for browser clients; API keys should be reserved for machine-to-machine use.
- Redis/shared rate limiting for multi-worker deployments.
- A production memory provider instead of SQLite fallback.
