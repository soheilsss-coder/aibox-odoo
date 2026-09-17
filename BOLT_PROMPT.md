# BOLT.NEW — FULL FRONTEND REBUILD SPEC (فارسی RTL)

> **How to use this file (for the human):** import this GitHub repository into
> [bolt.new](https://bolt.new), then paste this as your first message:
> «Read `BOLT_PROMPT.md` at the repo root and follow it exactly. Rebuild the
> frontend complete from scratch under `frontend/` — touch nothing else.»
> Everything Bolt needs is in this file: scope, API contract, pages, design.

---

## 1. Mission

Rebuild the **entire frontend** of this product from scratch inside
`frontend/`. The current `frontend/src` is a *reference for API usage only* —
you are NOT patching it, you are replacing it with a production-grade UI.

**Out of scope — DO NOT TOUCH anything outside `frontend/`:**
`custom_addons/` (Odoo backend modules), all `*.sh` / `*.py` scripts, docs,
`README.md`, CI files, nothing. The backend API is **frozen**; shapes below
are the contract. Never invent new endpoints and never put business logic or
authorization decisions in the frontend — the backend is authoritative.

**Never mention the underlying ERP/platform (Odoo) anywhere in the UI.** This
is a white-labeled product; end users must only ever see the brand returned by
`/api/admin/branding`.

## 2. Product context (what you are building)

An **AI-native enterprise operating system** (فارسی، راست‌چین) checked against
Odoo via the `ai_gateway` / `ai_semantic_api` HTTP API. Employees chat with a
role-aware AI assistant that executes real work (tasks, leave requests, HR
decrees, document search) after the backend checks identity, role, risk and
workflow. The UI is the product a company buys as "a box" — it must feel like
a premium SaaS (think Linear / Notion / Vercel dashboard quality), not like an
ERP admin panel.

Core areas (left sidebar navigation, Persian labels):
**خانه** (Home/Control Center) · **AI Workspace** (چت) · **کارها** (Tasks) ·
**تقویم** (Calendar) · **دپارتمان‌ها** · **اسناد** (Document Center) ·
**Knowledge** · **تأییدها** (Approvals) · **Agents** · **اعلان‌ها** ·
**اتصالات** (Integrations) · **مرخصی‌ها** (Leaves) · **مدیریت** (Admin Console —
visible only with the `admin.console.read` capability).

## 3. Tech stack (fixed)

- **Vite 5 + React 18 + react-router-dom v6**, plain ES modules (no TypeScript
  enforcement required; JSX is fine). Package name `ai-erp-frontend`.
- **Styling:** hand-rolled CSS with CSS custom properties (design tokens) —
  OR Tailwind *if you keep the same theming hooks*. Whichever you choose, ALL
  colors/radii/spacing MUST come from CSS variables so a white-label customer
  re-themes by editing one file (`src/styles/tokens.css`). Dark theme is the
  default; provide a light theme toggle persisted in `localStorage`.
- **No backend calls hardcoded to a host** — always same-origin relative
  `/api/...`. Vite dev config proxies it (keep this exact proxy):

```js
// frontend/vite.config.js  (KEEP this behavior)
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    allowedHosts: true,           // required for sandbox/preview surfaces
    port: 5173,
    proxy: { "/api": { target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8069", changeOrigin: true } },
  },
});
```

- `index.html` MUST stay `<html lang="fa" dir="rtl">`. Load the **Vazirmatn**
  webfont (CDN `@font-face` is fine) with `system-ui, sans-serif` fallback.

## 4. Authentication & session (critical — read carefully)

The backend supports **two** credential paths; the frontend must implement
both, exactly like this:

1. **Cookie session (primary):** `POST /api/login {login, password}` → on
   success sets `ai_session` **HttpOnly cookie** and returns
   `{ authenticated: true, user: { id, name, login }, expires_at }`. All later
   fetches use `credentials: "include"`.
2. **Header fallback (REQUIRED):** some responses may also carry an
   `api_key` field (the dev mock does). When present, store it
   (`sessionStorage`, wrapped in try/catch — storage is blocked in some
   iframes; then keep it in-memory) and send it on **every** request as
   `X-API-Key: <key>` (matching what the real gateway accepts natively).
   **Why it's mandatory:** preview surfaces (bolt.new's own preview, sandbox
   iframes) are third-party contexts where browsers drop cookies even with
   `SameSite=None; Secure` and `credentials: "include"`. Without the header
   path, login works and the very next request 401s with
   «نشست معتبر نیست؛ لطفاً وارد شوید.»

- **Boot:** on app start call `GET /api/me`. 200 → render the shell with that
  user; 401 → render the Login page.
- **Login page:** email + password, «ورود». In `import.meta.env.DEV` the form
  may be pre-filled with `sara@example.com` / `demo` (production builds must
  compile to an empty form).
- **Logout:** clear stored key, then `POST /api/logout`, then back to Login.
- Every API response may be `{ error: "..." }` with non-200 — show the
  `error` text (it arrives in Persian) in a dismissible alert.

## 5. Complete API contract (frozen — do not change)

All endpoints return JSON; cookies/headers as above. `?` marks optional
fields. Sample values are illustrative.

### Auth & identity
| Method & path | Body → Response |
|---|---|
| `POST /api/login` | `{login, password}` → `{authenticated, user:{id,name,login}, api_key?, expires_at}` |
| `GET /api/me` | → `{id, name, login, company, is_manager?, is_admin?, capabilities: string[]}` |
| `POST /api/logout` | → `{ok:true}` |
| `GET /api/me/capabilities` | → `{capabilities: string[]}` (items may be strings or `{name}` objects — handle both) |
| `GET /api/workspace` | → `{department?: {id, name}}` |

### Workspace data
| Method & path | Response |
|---|---|
| `GET /api/departments` | `{departments:[{id,name,member_count}]}` |
| `GET /api/agents` | `{agents:[{id,name,description?,tools:number}]}` |
| `GET /api/tasks` / `POST /api/tasks` | `{tasks:[{id,name,state}]}` / body `{name}` → `{task}` |
| `GET /api/approvals` | `{approvals:[{id,name,requester,risk:number,state}]}` |
| `GET /api/notifications` | `{notifications:[{id,subject,body(html),date,is_read}]}` |
| `GET /api/models` | `{models:[{name,provider,active}]}` |

### Chat (the heart of the product)
- `POST /api/chat` (non-streaming fallback): `{message, thread_id?}` →
  `{reply, thread_id}`.
- `POST /api/chat/stream` — **SSE** (`Content-Type: text/event-stream`).
  Frame format: `event: <name>\ndata: <json>\n\n`. Events in order:
  1. `thinking` `{"status":"routing"}` → show «در حال فکر کردن…» indicator
  2. repeated `delta` `{"text":"…"}` → append text into ONE assistant bubble
     (typewriter effect)
  3. `done` `{"thread_id":"…"}` → persist `thread_id` for the next message
  4. or `error` `{"error":"…"}` → remove the empty assistant bubble, show alert
  Read with `resp.body.getReader()` + `TextDecoder`; parse on `\n\n` bounds.
- `POST /api/files/analyze` (chat attachments): `{filename, data_base64,
  question}` → `{analysis}`. Flow: user attaches a file → read as base64 →
  analyze → prepend analysis to the visible prompt → then stream chat. Show
  attached-file chips above the composer; allow removing before send.
- **Voice input** (optional but present in the old UI): Web Speech API
  (`window.SpeechRecognition || webkitSpeechRecognition`, `lang="fa-IR"`);
  append transcript into the composer. If unsupported, alert nicely.

### HR leaves
| Method & path | Shapes |
|---|---|
| `GET /api/hr/leaves` | `{leaves:[{id,date_from,date_to,leave_type,reason,status}]}` |
| `POST /api/hr/leaves` | `{date_from,date_to,reason?}` → `{leave}` |
| `POST /api/hr/leaves/{id}/cancel` | → `{ok:true}` |

`status` ∈ `draft | pending_approval | approved | rejected | cancelled` →
labels: پیش‌نویس / در انتظار تایید / تایید شده / رد شده / لغو شده. The cancel
button only shows on `draft`/`pending_approval`.

### Document Center (ACL-aware)
| Method & path | Shapes |
|---|---|
| `GET /api/documents?query=&access_level=` | `{documents:[{id,name,description?,access_level,department?,group?,owner?,file_name?,create_date,is_mine}]}` |
| `GET /api/documents/options` | `{departments:[{id,name}], groups:[{id,name}], own_department_id}` |
| `POST /api/documents/search` | `{query, top_k}` → `{results:[{document_id,document_name,similarity,excerpt}]}` |
| `POST /api/documents` | `{name, description?, access_level, department_id?, group_id?, file_base64?, file_name?}` → `{document}` |
| `GET /api/documents/{id}` | → `{document}` |
| `DELETE /api/documents/{id}` | → `{ok:true}` |

`access_level` ∈ `company | department | group | personal` → labels: کل سازمان
/ دپارتمان / گروه محدود / شخصی. The page has these tabs plus «همه». Upload
modal: name, description, access level select; when `department` → department
select (default `own_department_id`); when `group` → group select (show the
«شما عضو هیچ گروه محدودی نیستید» hint if empty); optional file → base64.
**Delete button only when** `d.is_mine` **or the user has the**
`document.admin.manage` **capability.** Semantic search box on top: «سوال
بپرسید، نه فقط کلیدواژه»; results show `document_name`, `similarity`
percentage and a ~220-char excerpt.

### Admin Console (`/admin`, gated by capability `admin.console.read`)
Non-admin users hitting this route see a friendly «دسترسی مجاز نیست» page.
Seven tabs:
1. **نقش‌ها** — `GET /api/admin/roles` → `{roles:[{name,comment,implied_roles:string[],member_count,members:[{name}]}]}`
2. **دسترسی موقت / تفویض** — `GET /api/admin/access-grants` →
   `{grants:[{id,to_user,role,delegated_from?,expires_on,state}]}`;
   create modal posts `POST /api/admin/access-grants
   {to_user_id,group_id,expires_on,reason}`;
   revoke: `POST /api/admin/access-grants/{id}/revoke`. `state` ∈
   `active|revoked|expired`. User list from `GET /api/admin/users` → `{users:[{id,name,login}]}`.
3. **اسناد** — `GET /api/admin/documents` (same doc shape; columns: نام، سطح
   دسترسی، دپارتمان، گروه، مالک، تاریخ ثبت).
4. **ایجنت‌ها** — `GET /api/admin/agents` → `{agents:[{id,name,model?,provider?,tool_count,active}],
   tools:[{name,risk_level,requires_approval_from?,description}]}` (two tables).
5. **برندینگ** — `GET /api/admin/branding` → `{brand_name,brand_domain,company_name,has_logo}`;
   edit name+domain, `POST` same body back. Show «تنظیمات ذخیره شد.» on success.
6. **مانیتورینگ** — `GET /api/metrics` → `{requests_last_hour,
   requests_last_24h, errors_last_24h, error_rate_24h, avg_duration_ms_24h,
   top_actions_24h:[{action,calls}]}` (stat cards + table, refresh button).
7. **Control Plane** — `GET /api/admin/control-plane` → `{users, departments,
   positions, designers, access_reviews, scim_active_tokens, sections:string[],
   sso:[{name,protocol,active}], configuration_profiles:[{name,state,version}]}`.

### Integrations (Telegram linking flow)
- `GET /api/integrations/telegram` → `{available, linked, linked_date?,
  last_message_date?}`. If `!available` show an empty-state: «یکپارچه‌سازی
  تلگرام روی این سیستم نصب نشده…».
- If not linked: «اتصال تلگرام» button → `POST
  /api/integrations/telegram/code` → `{code, bot_username, expires_in_minutes}`.
  Show `/link CODE` text + `@bot_username`, a **live countdown**, and poll the
  status endpoint every 3s until `linked` flips true.
- If linked: show dates (format with
  `new Date(v.replace(" ","T")+"Z").toLocaleString("fa-IR")`) and a «قطع اتصال»
  flow with a confirmation modal → `POST /api/integrations/telegram/unlink`.

## 6. Dev mock server (keeps the preview alive without Odoo)

`frontend/dev/mock-api.mjs` (zero-dependency Node, port 8069) already
implements **everything above** with Persian demo data — login with any
email/password, SSE chat, documents, the whole admin console. Keep it working
and extend it if needed; the bolt.new preview should run BOTH processes:

```
node dev/mock-api.mjs     # terminal 1  (mock backend on 127.0.0.1:8069)
npm install && npm run dev # terminal 2  (Vite on 5173, proxies /api → 8069)
```

Auth in the mock mirrors production: `mock_sid` cookie (`Secure; SameSite=None`)
plus `X-API-Key`/`Bearer` header acceptance, `api_key` returned from login.

## 7. Design & UX requirements

- **Language & direction:** 100% Persian UI copy, `dir="rtl"`, `lang="fa"`.
  Numbers/dates where localized use `fa-IR` formatting. English names like
  *AI Workspace / Knowledge / Agents / Control Plane* are intentional brand
  terms — keep them.
- **Feel:** premium, fast, calm. Dark default (deep charcoal, not pure
  black), one accent color (indigo-blue family, `#4f8cff` starting point),
  soft borders, generous whitespace, 10px radii, subtle shadows, 150–250ms
  easings. Everything themeable via `tokens.css` variables.
- **Layout:** right-hand sidebar (RTL → brand block top, user card, nav with
  active-state pill, «اعلان‌ها» unread badge, bottom: مدیریت + خروج). Main
  column: page header (eyebrow + title + subtitle + primary action), content
  grid. Mobile: sidebar collapses to a drawer; tables scroll horizontally.
- **Component library to build once, reuse everywhere:** Card (title,
  actions slot), Button (primary/ghost/danger, sizes, loading spinner state),
  Input/TextArea/Select (labels, focus rings), Badge/Pill (neutral|info|
  success|warning|danger tones), Table (columns config + render fns), Tabs,
  Modal (RTL-aware, ESC/backdrop close), Alert (dismissible), Spinner,
  EmptyState (icon + text), Chat bubble, Composer with attach/voice/send.
- **States everywhere:** every list has skeleton/spinner loading, empty state
  («…ثبت نشده»), and error alert. Never a blank white area.
- **Capability-driven UI:** hide/lock what the user's `capabilities` don't
  allow (admin nav item, delete buttons). Never rely on hiding alone —
  backend re-checks — but the UI must not tease dead features.
- **Accessibility:** focus-visible rings, `aria-label`s on icon buttons,
  semantic landmarks, color-contrast ≥ WCAG AA, full keyboard navigation.
- **Micro-interactions:** sidebar nav hover/active transition, card lift on
  hover, button press scale, chat typewriter with a blinking caret, thinking
  dots animation, toast/alert slide-in.
- **Login screen:** centered card over a soft gradient/aurora background with
  the brand mark; this is the first impression — make it beautiful.

## 8. Acceptance checklist (must all pass before you finish)

1. `node dev/mock-api.mjs` + `npm run dev` → the whole app works with **zero
   console errors**; login `sara@example.com`/`demo` lands on خانه.
2. Kill the mock → every page still renders its error state, no white screen.
3. Chat: thinking indicator → typewriter stream → thread continuity (second
   message reuses `thread_id`); error event handled; file attach chip flow.
4. Hard refresh on `/documents`, `/admin`, `/chat` works (SPA fallback).
5. Every table/list shows loading → data and loading → empty correctly.
6. `admin` route hidden for users without `admin.console.read` (toggle the
   capability in the mock to test); delete buttons respect `is_mine` /
   `document.admin.manage`.
7. Light/dark toggle persists across reload; zero hardcoded colors outside
   tokens.
8. `npm run build` succeeds; preview of the build behind any static server
   + the mock works identically (relative `/api`).
9. Only files under `frontend/` changed. `git status` outside `frontend/` is
   clean (except this file's own addition).
10. The final UI looks like a product worth paying for — not a styled admin
    template.

## 9. Reference (old implementation, API usage only)

The previous UI lives in `frontend/src` (App.jsx has all routes + inline page
components; `src/api/client.js` is the API layer; `src/pages/*` the screens).
Mine it for exact API call patterns, then replace it wholesale.
