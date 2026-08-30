# v44 — RAG / Event Integration

## What changed

v44 moves document indexing onto the Control Plane event contract:

```text
Document.create/write
        |
        v
Domain Event: document.created / document.updated
        |
        v
Durable Event Outbox
        |
        v
Event Subscription
        |
        v
ai.rag.event.subscriber
        |
        v
Async ai.document.index.job
        |
        v
Extract/OCR -> Context Firewall -> Chunk -> Embedding -> pgvector
```

The Document transaction does **not** call the embedding service. A failed/rolled-back
Document transaction therefore cannot leave an orphan vector index operation behind.

The subscriber is an explicit `_handle_event` contract, not a dynamic arbitrary callable.

## Additional subscribers

- Calendar: `task.created`, `leave.approved` when a `calendar_event` payload is supplied.
- Memory: `memory.capture.requested` through the existing memory policy helper.

## Important boundary

This release is still not Production Certified. Real Odoo runtime, multi-worker delivery,
embedding service, pgvector, calendar, and memory integration tests must pass before the
E2E gate can be green.
