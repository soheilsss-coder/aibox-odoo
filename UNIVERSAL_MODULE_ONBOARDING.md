# Universal module onboarding

## Contract

Every module in the installed registry is onboarded without an administrator
registration step. The post-transaction module hook makes the onboarding cron
due immediately; the one-minute cron remains the restart-safe fallback.

Onboarding records:

- installed version and lifecycle state;
- an explicit connection to the single Company Assistant agent, including
  connection state, attached tool count, and operation count;
- model, menu, view, and security-group inventory;
- per-model company, department, employee, and user scope signals;
- bounded read-only capability and read-summary operation contracts;
- lifecycle event mappings and the audit/event baseline;
- counts of discovered versus source-reviewed operations.

## Agent tool connection

The installed registry is also the source for the agent's tool catalog. The
onboarding service creates one durable `ai.integration.agent.module` binding
per installed module and the single Company Assistant. Reviewed operation
contracts are attached through `run_reviewed_operation` (or an explicitly
registered first-class tool), while legacy named tools carry an explicit owner
such as `hr_holidays`, `project`, or `calendar`. The assistant record's
`tool_ids` is refreshed from these bindings; a per-user thread then narrows it
again using capability, native ACL, risk, and approval checks.

The binding is intentionally not a permission grant. A module can be
`connected_no_tools` when only discovery exists, and a missing model/adapter is
reported as `error`. When a module is uninstalled, its binding remains in audit
history but is deactivated and its tools are removed from the assistant
catalog. The execution gate independently checks the owning module, so stale
risk metadata cannot execute a tool for an absent module.

## Safety boundary

Discovery never creates a business mutation. The generated operation is
`discovered_read` only. Its model and safe field list are stored in the
registry; the caller can provide only a bounded `limit`. The handler does not
accept a model, field list, domain, method name, or arbitrary ORM payload.
Native ACLs and record rules still run in the authenticated user's environment.

Create, update, delete, approve, financial, stock, and other side-effecting
operations require all of the following:

1. a source-reviewed adapter;
2. a reviewed capability and risk contract;
3. a registered handler (third-party modules can extend the handler selection
   through the normal adapter contract);
4. central authorization, risk, and approval checks; and
5. live runtime certification before production promotion.

A module without that contract is explicitly `discovered_read_only` in the
registry and each uncovered business mutation kind is marked
`adapter-required`. Even a module with one reviewed operation keeps every
other uncovered mutation kind marked, so it is never silently reported as
fully operationally certified.

## Event and audit baseline

The onboarding layer installs idempotent database triggers for installed model
tables. Triggers persist metadata only: model, record id, lifecycle operation,
company id, actor id, and timestamp. They do not copy business fields or
secrets. A durable worker converts these rows into the normal event outbox;
reviewed or discovered event mappings select the event type, and the existing
allowlisted subscribers provide audit and downstream event handling.

Trigger installation failure marks the module's event and audit baseline
inactive and leaves the module in a warning state. This is fail-closed rather
than a false readiness result.

## Certification states

- `discovered_read_only`: automatic inventory, bounded reads, authorization
  baseline, and event/audit baseline are available.
- `reviewed_operational`: a reviewed adapter and at least one reviewed
  operational contract are present; this still requires live runtime evidence
  for production certification.
- `blocked`: the module is not installed or its adapter/contract is disabled.

Source checks are not runtime proof. Run the live module certification and
native deployment probes on the target environment before making any claim
about complete business-operation coverage, tenant isolation, capacity, or
production readiness.
