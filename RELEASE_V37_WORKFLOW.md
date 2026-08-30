# v37 — Durable Workflow Engine

Implemented on top of v36 Event Bus.

- Multi-worker safe workflow-run claiming with PostgreSQL `FOR UPDATE SKIP LOCKED`.
- Durable run state machine: queued/running/waiting/completed/failed/cancelled.
- Durable wait and wait-until steps.
- Conditions with all/any and comparison operators.
- Branch/jump steps.
- Human approval records with DB idempotency and decision-time authorization.
- Human task creation through Odoo activities.
- Notification actions emit durable events rather than calling external channels synchronously.
- Event chaining with correlation/causation IDs.
- Retry/backoff and terminal failure.
- Compensation steps on terminal failure, guarded by compensation_started.
- Workflow definition validation before activation.
- Run and approval API endpoints.
- Contract tests for definition validation and event/run idempotency.

Delivery semantics remain at-least-once. Workflow actions must be idempotent or use stable business idempotency keys.

Runtime certification still requires real Odoo/PostgreSQL multi-worker execution.
