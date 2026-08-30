# v36 — Durable Event Bus completion

## Implemented

1. Transactional database outbox with unique event identity.
2. Correlation/causation metadata and event sequence support.
3. Multi-worker safe event claiming using PostgreSQL `FOR UPDATE SKIP LOCKED`.
4. Durable subscription delivery records.
5. Database idempotency for every `event_key + handler_key` delivery.
6. Delivery leases and stale-worker recovery.
7. Exponential retry/backoff persisted in PostgreSQL.
8. Dead-letter state after maximum attempts.
9. First-class subscribers for workflow, notification, audit, Buzz/realtime bus, Telegram, memory, RAG and Calendar.
10. Dynamic workflow subscriptions are materialized automatically from active workflow definitions.
11. Task stage/escalation events now publish through the central durable event bus instead of directly calling `bus.bus`.
12. Approval approved/rejected/cancelled events are emitted into the same bus.
13. Core subscriptions are seeded for audit, notification, Buzz and RAG.

## Delivery semantics

The bus is **at-least-once**. Database state is idempotent, but an external side effect (for example Telegram HTTP delivery) cannot be made mathematically atomic with PostgreSQL without an external provider idempotency key. Such handlers therefore raise on failure so the delivery is retried and eventually dead-lettered.

## Validation performed in this build

- Python AST validation: PASS
- Python bytecode compilation: PASS
- XML parsing: PASS
- subscription uniqueness review: PASS
- source audit for direct task `bus.bus` publishing: PASS

Full runtime validation still requires a real Odoo + PostgreSQL deployment with multiple workers; this environment does not provide that runtime.
