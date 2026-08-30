# v56 Canonical Roadmap Matrix

| Phase | Requirement | Source status |
|---|---|---|
| 1 | Integration Registry + Module Discovery | PASS |
| 2 | Capability Registry | PASS |
| 3 | Universal Authorization RBAC/ABAC/FGA | PASS |
| 4 | Generic Read + restricted writes + Business Action Adapters | PASS |
| 5 | Durable Event Bus + 9 subscriber families | PASS |
| 6 | Event-driven Workflow + recovery-only cron | PASS |
| 7 | Buzz Adapter + user/agent identity | PASS |
| 8 | Capability-aware Frontend | PASS |
| 9 | Document Authorization + async RAG | PASS |
| 10 | Capability/Tool unification + Hermes gateway | PASS |
| 11 | Model Registry + benchmark-gated Router | PASS |
| 12 | Auto Module Integration | PASS source + certification runner |
| 13 | Business Adapters: HR/Accounting/Inventory/Purchase/Sales/CRM/Project/MRP/Documents/Calendar | PASS |
| 14 | Integration Test + Universal Certification | PASS source + live gate required |
| 15 | Evaluation / Security / Tool / Role / RAG / Vision / Latency / Canary / Rollback pipeline | PASS source; benchmark/runtime execution required |
| 16 | Customer Deployment Wizard + final module certification | PASS source; live runtime required |

## Final security chain

`User / Agent Identity`

→ `Authorization (RBAC + ABAC + FGA)`

→ `Policy`

→ `Risk`

→ `Approval`

→ `Commit-Time Authorization + Target Re-check`

→ `Tool Gateway`

→ `Business Tool`

→ `ERP Adapter`

→ `Odoo ACL / Record Rule`

→ `ERP Core`

Hermes, Memory, RAG, Vision, Workflow, Documents, Buzz, Telegram and Frontend are attached to the same Control Plane rather than creating parallel authorization paths.
