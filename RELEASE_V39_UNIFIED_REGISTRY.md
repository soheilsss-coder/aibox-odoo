# v39 — Unified Capability → Tool → Risk → Business Adapter

This release continues from v38 and implements the next integration layer.

## Implemented

- Unified operation registry: `ai.integration.operation`
- Stable mapping: Tool → Module → Capability → Risk → Reviewed Handler
- Central gateway can execute reviewed ERP adapter operations when no `llm.tool` Python method exists
- Direct registry callers are still forced through the central execution gate
- Reviewed business handlers for HR Leave, Project Task, Sales Order, Purchase RFQ, Stock Transfer confirmation and Accounting posting
- Capability and risk records for those operations
- Universal module certification records and runner
- Certification checks installation, adapter, capabilities, business operations, risk registration, capability/model availability, event subscriptions, central gate and optional RAG/workflow services
- Hourly certification cron

## Verification

- Python compile: PASS
- XML parse: PASS
- Static audit: PASS
- ZIP integrity: PASS

## Honest limitation

This is not a claim that every Odoo module is universally business-complete. Generic discovery remains read-only by design. Mutating operations require a reviewed adapter operation and certification. Real Odoo/PostgreSQL/vLLM multi-worker execution must still be run in the target deployment before production certification.
