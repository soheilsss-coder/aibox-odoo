# frontend (roadmap #43-47 — Phase 7 complete)

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

The login screen asks for an API key — the same kind created in
`ai.gateway.api.key` (Settings, see `ai_gateway` module) that the
`/api/rpc` and `/api/chat` endpoints already use. There is no separate
frontend-only auth system. `GET /api/me` now also returns `is_admin`
(true for System Admin/Executive/Security roles — the same privileged
set `/api/metrics` already used) so the app knows whether to show the
Admin Console nav link; the backend re-checks this independently on
every `/api/admin/*` call regardless.

## Pages (phase 7 status)

| Page | Route | Roadmap item | Status |
|------|-------|--------------|--------|
| Leaves | `/leaves` | — | unchanged since phase 6 |
| Document Center | `/documents` | #47 | **done this round** — browse by access level (tabs), semantic search, upload (with department/group picker scoped to what the caller is actually allowed to restrict to), delete own/admin-owned documents |
| Chat | `/chat` | — | unchanged, restyled with the component library |
| Admin Console | `/admin` (privileged only) | #46 | **done this round** — Roles, Access Grants (create/revoke), org-wide Documents overview, Agents (tool registry + risk + model info), Branding, Observability |

Design System (#45): `src/components/` — see its own README for the
component list, the styling convention (`ds-*` classes in
`app.css`, still reading from `tokens.css` variables), and its honest
limits (no Storybook, no accessibility audit, `Table`/`Modal` are
intentionally minimal for this app's current data volume).

## What's still NOT covered

Still only reachable via `/api/rpc` with a raw model name, which is
exactly the thing item 44 says a frontend shouldn't do:
- Tasks/projects, timesheets, attendance, anything in `account`

Extending coverage is mechanical: add one semantic endpoint per domain
in `ai_semantic_api/controllers/semantic_api.py` (copy the
`hr/leaves` or `documents` pattern), add the matching function to
`client.js`, add a page. Each new domain is its own small, low-risk
unit of work — same reasoning the roadmap uses elsewhere for not
batching unrelated big items together.

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
