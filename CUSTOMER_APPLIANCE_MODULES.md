# Customer appliance module flow

## Product contract

Each customer receives one appliance with one database and one isolated
installation. The administrator configures that appliance from the product
Admin Console; no customer-selection switch is used inside a shared database.

The **Business Apps** tab lists selectable applications available in the
installed module source. Selecting an application sends one audited install
request at a time to the platform's own module lifecycle. Dependencies are
handled by that lifecycle. The browser never executes a shell command and the
server never accepts an arbitrary ORM model, method, or command from the
browser.

After the install transaction completes:

1. the post-commit module hook schedules automatic onboarding;
2. the restart-safe onboarding cron refreshes the module registry;
3. models, views, menus, safe fields, capabilities, event mappings and the
   audit baseline are recorded;
4. visible menus are filtered by the current user's native groups and appear in
   the product shell under **Business Apps**;
5. menu actions with a safe window view open a generic read-only workspace over
   the real records, still under the user's native ACL and record rules;
6. the module workspace links back to the AI Workspace with the same user
   authorization boundary.

No second manual discovery or synchronization command is part of the customer
handoff flow. A failed install is recorded as failed and is not represented as
an active checkbox.

## Accounting and other sensitive applications

The official business application remains the source of truth for accounting,
sales, inventory, purchasing, HR, manufacturing and other business records.
This product does not replace those models with a demo screen.

Automatic onboarding is deliberately conservative:

- read inventory, bounded read summaries, lifecycle metadata, audit and event
  baseline can be created automatically;
- create, update, delete, approve, payment, reconciliation, stock movement and
  other side effects require a reviewed adapter and capability/risk contract;
- production eligibility additionally requires live certification on the
  target appliance.

Installing Accounting therefore makes its real menus and records available on
that appliance, but it does not silently claim that every financial action is
AI-enabled. Chart of accounts, localization, journals, taxes, users and other
customer configuration are still part of the setup checklist.

## Runtime handoff gate

Before delivery of an appliance, run the real target-stack checks rather than
relying on source verification:

```bash
# Run from the repository checkout on the appliance, with the approved venv.
AI_GATEWAY_ENV=production ./08_deployment_checklist.sh

# After the application and database are running:
/opt/odoo/venv/bin/python /opt/odoo/src/odoo/odoo-bin shell \
  -c /etc/odoo/odoo.conf -d <customer_db> \
  < 48_auto_integration_certification.py
```

The certification runner is fail-closed. A source PASS is not runtime proof;
module installation, menu visibility, AI operation coverage, backups/restore,
TLS, tenant boundary and capacity still need evidence from the actual device.
