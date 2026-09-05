# frontend (roadmap #43-47 — appliance module flow added)

A standalone React app (Vite) that talks ONLY to the Odoo box's
`/api/*` endpoints — never a raw Odoo model name, never the Odoo web
client's own routes/assets. This is what makes white-labeling (item
55) and swapping the ERP underneath (item 44's actual point) possible
without touching this code.

## The rule this whole folder follows

**Only `src/api/client.js` is allowed to know a URL.** Every page
(`src/pages/*.jsx`) imports functions like `listLeaves()` or
`searchDocuments()` from that one file and never calls `fetch()`
directly. If you add a new page, add a function to `client.js` first,
then use it — don't inline a new `fetch("/api/...")` call in a
component. That's the whole enforcement mechanism: it's a convention,
not a lint rule (adding one is a reasonable follow-up).

The same rule now also applies to markup: **reach for a component in
`src/components/` before writing a raw `<button>`/`<input>`/table.**
See `src/components/README.md` for the full list (roadmap #45).

## Setup

```bash
cd frontend
npm install
npm run dev
```

By default `vite.config.js` proxies `/api/*` to
`http://127.0.0.1:8069` (Odoo's default port) — override with
`VITE_API_PROXY_TARGET` if Odoo is running elsewhere, or set
`AI_GATEWAY_ALLOWED_ORIGIN` on the Odoo side and call a fully-qualified
API base instead if you deploy this frontend on a different domain
(e.g. Vercel) than the Odoo box.

## Login

The login screen uses the customer's normal username/password once at
`/api/login`, which issues the short-lived HttpOnly product session. There is
no separate frontend-only user database. Machine clients may still use the
existing API-key header contract. `GET /api/me` returns `is_admin` (true for
System Admin/Executive/Security roles — the same privileged set `/api/metrics`
already uses) so the app knows whether to show the Admin Console nav link; the
backend re-checks this independently on every `/api/admin/*` call regardless.

## Pages (phase 7 status)

| Page | Route | Roadmap item | Status |
|------|-------|--------------|--------|
| Leaves | `/leaves` | — | unchanged since phase 6 |
| Document Center | `/documents` | #47 | **done this round** — browse by access level (tabs), semantic search, upload (with department/group picker scoped to what the caller is actually allowed to restrict to), delete own/admin-owned documents |
| Chat | `/chat` | — | unchanged, restyled with the component library |
| Admin Console | `/admin` (privileged only) | #46 | **done this round** — Roles, Access Grants (create/revoke), org-wide Documents overview, Agents (tool registry + risk + model info), Branding, Observability, and Business Apps installation |
| Module workspace | `/modules/:id` and `/modules/:id/menus/:menuId` | appliance flow | **source-complete** — installed application menus are filtered by native groups and safe window actions open a read-only workspace over real records; mutations remain on reviewed adapters |

Design System (#45): `src/components/` — see its own README for the
component list, the styling convention (`ds-*` classes in
`app.css`, still reading from `tokens.css` variables), and its honest
limits (no Storybook, no accessibility audit, `Table`/`Modal` are
intentionally minimal for this app's current data volume).

## Module tools are connected to the agent

After an application is installed, automatic onboarding creates a durable
connection between that application and the one Company Assistant agent. The
agent's tool catalog is refreshed from installed, explicitly owned tool and
operation contracts. Each chat thread narrows that catalog again by the
current user's capability, native ACL, risk, and approval state. The UI shows
whether the module is connected and how many registered tools/operations it
has.

This is not a blanket permission grant and it is not a fake module screen. A
module with only automatic discovery is connected with no invented mutation
tools; an uninstalled module's tools are removed from the agent catalog and
rejected by the execution gate.

## What's still intentionally limited

The Business Apps flow can install the real application, discover its native
menus, and provide a safe generic read workspace. It does **not** invent a
full custom clone of every application's form and workflow. Create/update/
delete/approve operations are exposed only through named, reviewed adapters
and the AI capability/risk/approval gate. A newly installed application with
no reviewed adapter therefore remains read/audit/event baseline only.

Adding a new operational domain is mechanical but still needs review: add a
semantic endpoint or reviewed adapter, register its capability/risk contract,
add the matching function/page, and run live certification on the target
appliance. Source presence alone is not a production claim.

## Honest limits of this round's #46/#47 work

- **Document Center upload** sends the whole file as base64 in one
  JSON request body (`FileReader.readAsDataURL` → strip the data:
  prefix → `file_base64`). Fine for the document sizes an org
  document library actually has (policies, forms, decrees); there is
  no chunked/resumable upload, so a very large file would need one
  in a future round.
- **Admin Console → Access Grants** lets an admin grant ANY role to
  ANY user with no upper bound beyond the privileged check itself —
  unlike `grant_temporary_access` (the AI tool in
  `access_review_tools.py`), which restricts a non-Executive/
  non-SysAdmin caller to delegating only a role they themselves hold.
  This is intentional, not an oversight: an admin using the Admin
  Console IS already in the privileged set the AI tool's extra check
  exists to gate around, so the same restriction here would just be
  friction with no additional safety - but it's worth knowing the two
  paths to the same model enforce different things, for the same
  reason `/api/rpc` and `/api/admin/*` enforce different things.
- **Admin Console → Branding** only edits the two placeholder values
  `ai_debrand`'s data file sets (`ai.brand.name`, `ai.brand.domain`) - the
  logo image and login-page template text are still a manual step,
  same as item #55 already said before this round.
- **No end-to-end test pass against a live Odoo instance yet** - same
  caveat as before phase 7: this was written and syntax-checked
  (`esbuild` resolves every import cleanly, no bundler errors) without
  a running Odoo box to click through. Before a customer sees it, do
  one real pass: login → leaves → upload a document in each access
  level → semantic search → delete a document → (if admin) create and
  revoke an access grant → edit branding → chat round-trip.
