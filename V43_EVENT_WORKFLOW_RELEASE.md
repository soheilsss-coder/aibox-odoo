# v43 — Durable Event Subscriber + Workflow Control Plane

This release continues from v42 and closes the next architectural gap without
claiming Production Certification.

## Implemented

### Event Bus
- Durable outbox remains authoritative.
- Durable per-subscriber deliveries remain idempotent.
- Subscriber contracts are now explicit with `subscriber_model` + `subscriber_method`.
- Arbitrary Python methods are rejected; subscriber methods must use `_handle_event` or `_handle_event_*`.
- Delivery executes the registered subscriber contract rather than relying only on a monolithic dispatcher target switch.
- PostgreSQL `FOR UPDATE SKIP LOCKED` remains the multi-worker claim mechanism.
- Delivery leases, retries, exponential backoff and dead-letter state remain durable.

### Workflow
- Workflow definitions can execute business tools only through `ai.gateway.execution.gate`.
- Workflow tool execution preserves the event actor as the authorization identity.
- Workflow supports escalation through the Event Bus.
- Workflow runs have explicit `dead_letter` terminal state after retry exhaustion.
- Compensation remains idempotently guarded.
- Human approval has an explicit timeout field and `timed_out` state.

### Correctness fix
- Business adapter event emission now uses the actual `ai.control.event.publish(..., user=...)` contract.

## Still NOT certified

This release does not claim that every Odoo business event has been wired to every
subscriber in a live environment. It also does not claim full external-system E2E.
The remaining acceptance target is the source roadmap's Purchase → Stock →
Accounting → Manufacturing → CRM/HR certification chain.
