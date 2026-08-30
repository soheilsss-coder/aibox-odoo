# Release v38 — Gateway-Level Risk & Policy Enforcement

## Scope
This release completes the next hardening stage after the durable Event Bus (v36) and Workflow Engine (v37): a single execution gate for AI tools.

## What changed
- Added `ai.gateway.execution.gate` as the central execution boundary.
- Unknown/unregistered AI tools are deny-by-default.
- Capability authorization is evaluated centrally when a capability is registered.
- RISK_5 is always human-only and blocked before the business method.
- RISK_3/RISK_4 create a durable human approval containing the exact tool name and arguments.
- Approval execution re-enters the same gate and uses a one-time approval context; the business tool cannot bypass the gate.
- Added approval idempotency key for identical user/tool/argument requests.
- Added `/api/tool/execute` as the canonical gateway execution API for integrations/workflows.
- Existing `ai.gateway.tool.risk.enforce()` is now only a compatibility shim delegating to the central gate.
- High-risk tools no longer require the requester to be in the approver group; only the configured approver must have that group.
- Tool allowlisting now uses capability authorization for risk-registered tools.
- Added static risk gateway contract tests.

## Execution path

```text
User / Agent / Integration
        |
        v
AI Gateway
        |
        v
Execution Gate
  |       |       |
Registry Capability Risk
  |       |       |
  +-------+-------+
          |
    RISK 0-2 -> execute
    RISK 3-4 -> durable approval -> human decision -> exact replay
    RISK 5   -> deny
          |
          v
Business Tool
```

## Important production note
The code and static contracts are hardened, but real multi-worker execution must still be exercised on the customer's Odoo/PostgreSQL runtime. In particular, approval replay, concurrent duplicate requests, and transaction rollback must be part of the live E2E certification suite.
