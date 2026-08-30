
## Current release: v57 — Production Stabilization (release candidate)

Canonical version marker lives in `RELEASE_CANDIDATE_VERSION.txt`
(`v57`); see `FINAL_RELEASE_STATUS.md` for the current release state.
# Odoo AI System — Final Complete Package

Everything built across this whole project: Odoo 18 Community
(bare-metal, no Docker) + local vLLM + odoo-llm AI framework + a
custom module with role-based demo users, full-format file reading
(OCR included), internet search, accurate date awareness, an HR
decree/leave workflow the AI can execute end-to-end, and an
`ai_gateway` module exposing exactly 3 generic endpoints
(`/api/bootstrap`, `/api/rpc` (permanently disabled; use named capabilities), `/api/chat`) for a decoupled React/
Emergent/Lovable frontend.

This version has every fix discovered through extensive real-world
testing baked directly into the code - not left as manual steps.

## A note on scope (read this if you're wondering about "enterprise architecture")

A much larger enterprise-architecture proposal was considered for this
project (multi-tenant SSO/SCIM, OpenFGA fine-grained authorization,
Temporal workflows, separate microservices for identity/workflow/
memory/documents, etc.). That was deliberately NOT implemented here.
That level of architecture is for products serving many large
organizations simultaneously - this project sells one device to one
company at a time, and that complexity would multiply build time and
risk without solving a problem you actually have yet. Instead, four
concrete, scoped improvements were made this round:

1. **Security hardening**: random DB password generated per install
   (no more hardcoded `change_me`), CORS origin configurable via
   `AI_GATEWAY_ALLOWED_ORIGIN` env var (defaults open for local dev,
   lock it down before selling), API key no longer accepted via URL
   query string (header/Bearer only - query strings leak into logs),
   basic per-key rate limiting, and the destructive `DROP DATABASE`
   step moved out of the main install script into a separate
   confirmation-gated `reset_dev.sh`.
2. **Self-service leave requests**: a new `create_leave_request` tool
   lets any employee request time off for themselves; it goes through
   Odoo's own existing approval/notification flow to their manager -
   no new notification system needed. Kept separate from
   `generate_hr_decree`, which is for a manager/HR acting on someone
   else's behalf.
3. **Ask instead of guess, but only for writes**: the assistant will
   now ask one short clarifying question when required information
   (like a date) is genuinely missing for a write operation (leave,
   task, decree) - but still never asks for confirmation/permission on
   read operations, and never asks more than once.
4. **Vision tool**: a new `analyze_image` tool + optional second vLLM
   instance (`/opt/start_vllm_vision.sh`, Qwen2.5-VL, its own port so
   it doesn't fight the main model for GPU memory) lets the assistant
   reason about the actual content of an image (e.g. "how much rebar
   does this blueprint need"), not just extract text from it like
   `read_attached_file` does.

## Install (fresh server / fresh instance)

```bash
unzip odoo-ai-rebuild-final.zip
cd rebuild_final
chmod +x 01_setup_base.sh 02_install_modules.sh 03_start_all.sh reset_dev.sh
./01_setup_base.sh
cp -r custom_addons/company_ai_demo \
       custom_addons/ai_gateway \
       custom_addons/ai_business_tools \
       custom_addons/ai_rag \
       custom_addons/ai_semantic_api \
       custom_addons/ai_control_plane \
       custom_addons/ai_integration \
       custom_addons/ai_correspondence \
       custom_addons/ai_document_intelligence \
       custom_addons/ai_experience \
       custom_addons/ai_workflow \
       custom_addons/ai_collaboration \
       custom_addons/ai_production \
       custom_addons/ai_customer_plane \
       custom_addons/ai_telegram_bridge \
       custom_addons/ai_debrand \
       /opt/odoo-custom-addons/
./02_install_modules.sh
```

> **Prerequisite:** `ai_business_tools` requires the Odoo **Manufacturing
> (mrp)** application — its role templates imply the
> `mrp.group_mrp_manager` group. `02_install_modules.sh` includes `mrp`
> in its install list; make sure the Odoo artifact you ship contains it.

The installer never prints AI Gateway API keys — M2M secrets are
deliberately never written to stdout (see `02_install_modules.sh`).
Users get their key through the browser-side `/api/login` session flow
instead. The Postgres password is randomly generated per install (not
hardcoded) and saved to `/opt/.db_password` for your own reference if
you ever need to connect to the database directly.

## Start everything

```bash
./03_start_all.sh
```
This starts Postgres and prints the exact 3 commands to run in 3
separate terminals (vLLM, Odoo, tunnel) - each needs to stay in the
foreground so you can see when it's actually ready, not just launched.

⚠️ **GOLDEN RULE**: never `kill -9` the vLLM process. On this class of
hardware (unified CPU/GPU memory, e.g. NVIDIA GB10/DGX Spark) that can
leave an orphaned memory allocation that persists even after the
process is gone - only a full instance reboot releases it. Always stop
vLLM with a single `Ctrl+C` and wait for clean shutdown.

## Demo logins (Odoo web UI)
| Role | Login | Password |
|---|---|---|
Demo users are disabled for production by default. Generate credentials through the secure provisioning/session flow only.

## AI Gateway (for your React/Lovable/Emergent frontend)
See the API contract (exact JSON shapes for bootstrap/rpc/chat) - it's
unchanged from before, still 3 endpoints, still one API key per user.
Test directly before wiring up any frontend:
```bash
curl -H "X-API-Key: <a key>" https://<tunnel-url>/api/bootstrap
```
Don't have a key handy? Trade a real login/password for one (v24):
```bash
Browser/API login returns a short-lived HttpOnly `ai_session` cookie. API keys are reserved for machine-to-machine use and are never returned by browser login.
```
CORS is fail-closed and API credentials are accepted only through the
X-API-Key header or Authorization: Bearer header. Query-string credentials
are permanently disabled.

## Client onboarding from Excel (roadmap #36/#37)
`onboarding/onboard_from_excel.py` - see inline docstring for usage.
Reads a client's employee list and auto-creates every user + department
+ position + manager link + Role Template group + API key. Full
pipeline: Parse -> Validate -> Normalize -> Department -> Position ->
Manager -> Role Mapping -> Preview -> Approval -> Import. Nothing is
written until you type `IMPORT` at the preview prompt (or set
`ONBOARD_YES=1` once you've already reviewed one), and the whole write
happens inside one Postgres savepoint - `ONBOARD_DRY_RUN=1` runs the
real import logic and then rolls it back on purpose, so you can
sanity-check a client's real file with zero risk to the database. See
`onboarding/sample_employees.xlsx.csv` for the expected format
(`name`, `email` required; `role`, `department`, `job_title`,
`manager_email` optional).

## Persistent cross-conversation memory (new)
Two new tools, `save_memory` and `recall_memory`, let the assistant
remember things across completely separate conversations/threads for
the same user (e.g. "این‌رو یادت بمونه که..."). Deliberately built as
a canonical ORM-backed memory with an optional external provider adapter; the
Odoo record is the authoritative source of truth and retention/deletion
policies are enforced centrally. Both tools are capped at "once per turn" in their own
instructions to avoid the tool-call loop issue documented below.

## Every bug this package fixes for you (the complete history)

**Installation / environment:**
1. odoo-llm's own `requirements.txt` installed, not just Odoo's.
2. `web_json_editor` and `account_invoice_import_llm` folders (don't
   start with "llm", easy to miss when copying addons).
3. Postgres `localhost` can resolve to IPv6, which `pg_hba.conf` may
   not authenticate the same way as IPv4 - config uses `127.0.0.1`.
4. **`mcp` package pinned to `<2.0.0`** - newer major versions removed
   the `mcp.server.fastmcp` submodule that odoo-llm's tool-schema code
   depends on, causing every tool to silently fail to register with
   `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`.
5. Module install list must include `llm_thread`, `llm_assistant`,
   `llm_knowledge` explicitly, or you get "Model 'llm.thread' does not
   exist in registry."
6. A failed/partial module install can leave the DB in a broken state -
   the install script now drops and recreates the DB cleanly every run.

**vLLM / GPU memory (the big one):**
7. Generic CRUD tools' `domain` field didn't accept list values,
   breaking any `"in"` filter (e.g. `state in ('sale','done')`).
8. Temperature hardcoded to 0.2 in the OpenAI provider for more
   faithful, less hallucinated answers.
9. vLLM needs `--enable-auto-tool-choice --tool-call-parser hermes` or
   every tool call 400s.
10. **Full-precision (bf16) checkpoints can transiently need ~2x their
    file size in RAM while loading** on this container filesystem type
    (OVERLAY, not a network FS vLLM can stream-optimize) - a 57GB
    checkpoint can spike past 110GB and crash the box. Fixed by using
    an AWQ (quantized) build of the exact same model - same
    architecture, same 128K context, same capabilities, ~17GB on disk.
11. GPU "Out of Memory" errors that don't match any visible process
    (`nvidia-smi`/`ps` show nothing) are a known characteristic of
    unified-memory hardware like GB10 - `nvidia-smi` cannot attribute
    memory per-process on this hardware at all. Use
    `torch.cuda.mem_get_info(0)` for a real reading instead.
12. Killing a CUDA process with `-9` instead of `Ctrl+C` can orphan a
    memory allocation that no tool inside the container can see or
    free - only a full instance reboot clears it. This is now
    documented as a hard rule, not just a one-off fix.
13. sentence-transformers embedder forced onto CPU explicitly
    (`device="cpu"`) so it never competes with vLLM for GPU memory.

**AI Gateway (frontend integration):**
14. CORS headers + OPTIONS preflight handling added to all 3 endpoints -
    without this, browsers block every request before it's even sent,
    with no useful error message beyond a generic network failure.
15. API key now accepted via `X-API-Key` header, `Authorization:
    Bearer` header, or query-string API credentials (disabled) - some frontend
    builders/proxies strip custom headers, so this triple fallback
    avoids a repeat of "invalid or missing API key" for a technically
    correct key.

**Application logic:**
16. Odoo model names don't always match what you'd guess (`hr.leave`
    not `hr.holidays`) - baked into the Assistant's instructions.
17. Leave requests need an Allocation unless `requires_allocation` is
    `'no'` on the leave type - pre-created for you.
18. The model would invent today's date from outdated training
    knowledge and miscalculate Jalali conversion itself - fixed by
    computing both calendars in Python (`jdatetime`).
19. Scanned (image-only) PDFs return almost no text from
    `unstructured` - detected automatically and OCR'd page-by-page as
    a fallback (RapidOCR).
20. The AI Assistant's tools only copy to a Thread at Thread-creation
    time, NOT dynamically - the post-install script syncs all existing
    threads too. **Remember**: any time you add a new tool by hand
    later, re-run that same sync loop.

## Acceptance tests (run before every delivery)
```bash
source /opt/odoo-venv/bin/activate
/opt/odoo/odoo-bin shell -c /opt/odoo.conf -d company_ai < 05_acceptance_tests.py
```
Deterministic, no LLM involved - calls the tool methods directly as
each demo user and checks the exact permission scenarios you
described (CEO approves ✓ / employee can't approve their own or
someone else's leave ✗ / documents filtered by access level /
idempotency key blocks a duplicate task / HR decree needs a *second*
person's approval), PLUS (as of v11) 6 deliberate security-bypass
attempts per roadmap item #50 - allowlist denial, RISK_5 hard block,
Context Firewall redaction, audit-log row isolation, wrong-group
approval denial, direct-write ACL denial. Rolls back everything it
creates - safe to run on a real database. Exits non-zero if anything
fails - wire this into your deployment checklist (roadmap item #54)
before shipping a box.

## v8: چهار مورد فوری از خلاصه‌ی اولویت نقشه‌راه
- **Self-approval guard**: `approve_leave`/`reject_leave` دیگر اجازه
  نمی‌دهند یک مدیر مرخصی خودش را تایید/رد کند، حتی اگر عضو گروه HR
  Manager باشد - این چک در کد است چون ACL به‌تنهایی نمی‌تواند این را
  بگوید.
- **`ai.gateway.approval`**: `generate_hr_decree` دیگر بلافاصله اثر
  ندارد - فقط یک تاییدیه‌ی معلق می‌سازد که باید یک HR Manager *دیگر*
  (نه خود درخواست‌دهنده) آن را در Settings > AI Approvals تایید کند.
- **`ai.gateway.idempotency`**: پارامتر اختیاری `idempotency_key` روی
  `create_task`/`create_leave_request`/`approve_leave`/`reject_leave` -
  یک retry شبکه دیگر باعث دوبار ثبت‌شدن یک عملیات نمی‌شود.
- **`05_acceptance_tests.py`**: تست پذیرش خودکار بالا.

## v9: ۵ مورد بعدی نقشه‌راه (موارد ۵، ۲۵، ۴۰، ۴۱، ۴۲)
- **Role Templates (مورد ۵)**: ۱۱ گروه آماده (`ai_business_tools/data/role_templates_data.xml`)
  - Employee, Manager, HR Staff, HR Manager, Finance Staff/Manager,
  Warehouse Staff/Manager, Project Manager, Executive, Security,
  System Administrator - هرکدام با `implied_ids` گروه‌های واقعی Odoo
  را خودکار می‌گیرند، پس اضافه‌کردن یک نفر به «Role: HR Manager» یعنی
  همون لحظه هم `approve_leave` کار می‌کنه هم `generate_hr_decree` قابل
  تایید می‌شه - چیزی دستی تنظیم نمی‌کنی.
  ⚠️ این نام‌های گروه (`account.group_account_invoice` و مشابه) از
  روی الگوی استاندارد Odoo نوشته شدن ولی روی یک Odoo زنده تست نشدن -
  اولین نصب `-i` را با دقت چک کن، اگر یکی از این external idها در
  نسخه‌ی دقیق تو فرق داشت، خطای واضحی موقع نصب می‌دهد و به‌راحتی قابل
  اصلاح است.
- **Memory scope (مورد ۲۵)**: `save_memory`/`recall_memory` حالا سه سطح
  دارند: `personal` (پیش‌فرض، فقط خودش)، `department` (بخش سازمانی
  خودش)، `company` (فقط HR Manager به بالا می‌تواند بنویسد، همه
  می‌خوانند).
- **Access Review (مورد ۴۰)**: ابزار `list_elevated_access` - لیست
  همه‌ی دارندگان نقش‌های مدیریتی + دسترسی‌های موقت فعال.
- **Delegation + Temporary Access (موارد ۴۱-۴۲)**: مدل واحد
  `ai.gateway.access.grant` + ابزار `grant_temporary_access` + کرون
  روزانه‌ی فعال/منقضی‌سازی خودکار. یک کارمند فقط می‌تواند نقشی را که
  خودش دارد موقتاً تفویض کند؛ فقط Executive/System Admin می‌توانند هر
  نقشی به هرکسی بدهند.
- `05_acceptance_tests.py` با ۳ سناریوی جدید (تفویض غیرمجاز رد می‌شود،
  تفویض توسط Executive قبول می‌شود، حافظه‌ی شخصی برای دیگران دیده
  نمی‌شود) گسترش یافت.

## v10: ۴ مورد بعدی نقشه‌راه (موارد ۲۰، ۱۵، ۳۱، ۵۳-۵۴)
- **Risk Engine (مورد ۲۰)**: مدل `ai.gateway.tool.risk` - رجیستری
  صریح سطح ریسک (۰ تا ۵) برای هر ابزار، seed شده در
  `data/tool_risk_data.xml` برای همه‌ی ابزارهای فعلی.
  ⚠️ صادقانه: این یک اسکن خودکار زنده‌ی متدهای `@llm_tool` نیست (چون
  به کد داخلی ماژول پایه‌ی `llm_tool` دسترسی نداریم) - یک رجیستری
  صریح و دستی است؛ هر ابزار جدیدی که می‌سازی باید یک ردیف اینجا هم
  اضافه کنی.
- **Tool Registry (مورد ۱۵)**: ابزار `list_available_tools` - همان
  رجیستری بالا را برای بازبینی انسانی یا خودِ دستیار نمایش می‌دهد.
- **Rules Engine (مورد ۳۱)**: مدل عمومی `ai.gateway.approval.matrix`
  (فرآیند + بازه‌ی مبلغ + گروه تاییدکننده). `generate_hr_decree` الان
  واقعاً از این جدول گروه تاییدکننده را می‌خواند (نه هاردکد) - نمونه‌ی
  آماده برای فرآیندهای آینده مثل خرید (کامنت‌شده در
  `data/approval_matrix_data.xml`).
- **TLS واقعی (مورد ۵۳)**: `06_setup_tls.sh` - nginx + Let's Encrypt
  به‌جای cloudflared quick tunnel. نیاز به یک دامنه‌ی واقعی که از قبل
  به IP سرور اشاره کند:
  ```bash
  DOMAIN=company.yourbrand.example EMAIL=you@yourbrand.example ./06_setup_tls.sh
  ```
- **بکاپ (مورد ۵۱، پیش‌نیاز چک‌لیست)**: `07_setup_backups.sh` - بکاپ
  روزانه‌ی Postgres + filestore با نگهداری ۱۴ روزه، و مهم‌تر: خودش
  همان لحظه یک تست restore واقعی (روی دیتابیس آزمایشی، نه production)
  انجام می‌دهد و نتیجه را می‌گوید - بکاپی که تست نشده بکاپ نیست.
- **Deployment Checklist اجرایی (مورد ۵۴)**: `08_deployment_checklist.sh`
  - رمز پیش‌فرض، secrets، TLS، بکاپ، و کل مجموعه‌ی تست پذیرش را خودکار
  چک می‌کند و PASS/FAIL می‌دهد؛ مواردی که واقعاً نیاز به چشم انسان
  دارند (مثل تست مانیتورینگ) را به‌عنوان MANUAL علامت می‌زند، هرگز
  ادعای دروغین PASS نمی‌کند. اگر چیزی FAIL شود، با کد خروجی غیرصفر
  تحویل را متوقف می‌کند.

## v11: ۴ مورد بعدی نقشه‌راه (موارد ۵۰، ۱۸/۲۰ تکمیل، ۲۸، ۱۲ تکمیل)
- **Risk Engine enforcement (موارد ۱۸/۲۰ - تکمیل)**: `ai.gateway.tool.risk`
  یک متد `enforce()` واقعی گرفت - قبلاً فقط در docstring خودش وعده داده
  شده بود ولی هیچ‌جا صدا زده نمی‌شد، یعنی سطح ریسک صرفاً اطلاعاتی بود.
  حالا `approve_leave`، `reject_leave`، `create_task`،
  `grant_temporary_access`، `generate_hr_decree`، `save_memory` همه در
  همون خط اول این متد رو صدا می‌زنن: ابزارهای RISK_5 («فقط-انسان») به‌
  صورت قطعی بلاک می‌شن، و risk_level هر فراخوانی در audit log ثبت
  می‌شه. **صادقانه**: این جایگزین گارد دستی هر ابزار (مثل self-approval
  guard) نیست - یک لایه‌ی دفاع-در-عمق اضافه‌ست، نه جایگزین منطق موجود.
- **Context Firewall (مورد ۲۸)**: ماژول جدید `context_firewall.py` - یک
  لیست صریح فیلدهای ممنوعه (password، api_key، token، iban، ...) +
  چند regex برای رشته‌های شبیه‌توکن/کارت‌بانکی. اعمال‌شده روی:
  `recall_memory` (حافظه‌ی ذخیره‌شده ممکنه رمز داشته باشه)،
  `read_attached_file` (سند آپلودی ممکنه رمز داشته باشه)، و مهم‌تر از
  همه **خودِ نویسنده‌ی audit log** - یعنی حتی اگه یک ابزار آینده بی‌دقت
  یک رمز رو در payload خودش بذاره، قبل از ذخیره در دیتابیس هم پاک
  می‌شه. **صادقانه**: این یک classifier هوشمند نیست، یک denylist صریح و
  قابل‌بازبینی‌ست - عمداً محافظه‌کارانه (ممکنه گاهی یک شناسه‌ی بی‌ضرر
  طولانی رو هم پاک کنه)، چون لو رفتن یک رمز واقعی بدتر از یک false-
  positive است.
- **Audit Log - دسترسی سطر-به-سطر + نما (مورد ۱۲ - تکمیل)**: یک شکاف
  واقعی پیدا شد و بسته شد - `ir.model.access.csv` قبلاً به همه‌ی
  `base.group_user` اجازه‌ی خواندن **همه‌ی** ردیف‌های audit log رو
  می‌داد (بدون هیچ `ir.rule`)، یعنی هر کارمندی می‌تونست کارهای بقیه رو
  ببینه. حالا `security/audit_log_rules.xml` این رو محدود می‌کنه: کاربر
  عادی فقط ردیف‌های خودش، نقش‌های Executive/System Admin/Security همه‌
  چیز. `views/audit_log_views.xml` هم یک نمای فیلترپذیر
  (کاربر/تاریخ/موفقیت/منبع) زیر Settings > Administration اضافه کرد.
- **Security Testing (مورد ۵۰)**: ۶ سناریوی جدید در
  `05_acceptance_tests.py` (شماره ۱۱ تا ۱۶) - همگی تلاش عمدی برای دور
  زدن یک مجوز هستن، نه مسیر خوشبینانه: allowlist گیت‌وی روی
  `hr.employee.write` رد می‌کنه، ابزار RISK_5 حتی برای CEO بلاک می‌شه،
  Context Firewall یک مقدار شبیه‌رمز رو در recall واقعاً حذف می‌کنه،
  یک کارمند نمی‌تونه audit log مدیرعامل رو بخونه، یک مدیر خارج از گروه
  تاییدکننده نمی‌تونه حکم HR کس دیگه‌ای رو تایید کنه، و یک کارمند عادی
  نمی‌تونه مستقیم (بدون عبور از ابزار) روی رجیستری ریسک بنویسه.

## v12 (پیشنهادی - نه انجام‌شده): موارد ۵۸، ۵۹ - Soup و Buzz
دو مورد جدید به نقشه‌راه اضافه شد (`roadmap-73-items.md`، فاز ۹) -
هر دو یک پیشنهاد بیرونی بودن، هر دو قبل از اضافه‌شدن search و
راستی‌آزمایی شدن (هر دو واقعی‌اند)، هیچ‌کدوم dependency چیز دیگه‌ای
نیستن، و **هیچ‌کدوم روی داده‌ی مشتری واقعی اجرا نشدن** - فقط
اسکریپت نصب/پیکربندی اولیه اضافه شد:

- **`09_setup_soup_finetune.sh`** (مورد ۵۸): نصب `soup-cli[train]`
  (github.com/MakazhanAlpamys/Soup) + یک config اولیه که به همون مدل
  `/opt/start_vllm.sh` اشاره می‌کنه.
- **`10_setup_buzz.sh`** (مورد ۵۹): clone + build محلی
  `block/buzz` (github.com/block/buzz، منتشرشده توسط Block در
  ۲۱ ژوئیه ۲۰۲۶). وصل‌کردنش به Hermes/گیت‌وی عمداً دستی نگه داشته شده -
  Buzz جایگزین گیت‌وی امنیتی (مورد ۱۳/۸) نیست، فقط باید از همون سه
  اندپوینت (`/api/bootstrap`, `/api/rpc` (permanently disabled; use named capabilities), `/api/chat`) عبور کنه.

جزئیات کامل ریسک/محدودیت هر دو (شماره‌ی ستاره‌ی واقعی Soup که با
ادعای منبع فرق داشت، نسخه‌ی هنوز-اولیه‌ی Buzz، و غیره) در
`roadmap-73-items.md` فاز ۹ نوشته شده، نه اینجا.

## v20: مورد ۵۹ کامل شد - پل واقعی Hermes↔Buzz
`buzz_bridge/hermes_gateway_mcp_server.py` اضافه شد: یک سرور MCP روی
stdio که دقیقاً همون سه ابزار `gateway_bootstrap` / `gateway_rpc` /
`gateway_chat` را (هرکدام یک forward ساده به همون اندپوینت هم‌نام) در
اختیار agent می‌ذاره - نه shell، نه فایل، نه هیچ ابزار دیگه. این یعنی
سقف دسترسی یک agent متصل از طریق Buzz دقیقاً همون سقفیه که فرانت React
هم داره (همون کلید API، همون ACL اودو، همون allowlist گیت‌وی)، نه
بیشتر.

`10_setup_buzz.sh` هم به‌روز شد: حالا باینری‌های `buzz-acp` و
`buzz-agent` رو هم پیدا/گزارش می‌کنه، پل رو نصب می‌کنه (venv + `mcp` +
`requests`)، و دستور دقیق اجرای `buzz-acp` با `--mcp-server` اشاره‌شده
به همین پل و `--agent-bin` اشاره‌شده به `buzz-agent` (نه Claude Code/
Codex/Goose) رو چاپ می‌کنه - هیچ‌کدوم خودکار اجرا نمی‌شن، کلید API
واقعی مشتری همچنان دستی وارد می‌شه.

**نکته‌ی مهمی که موقع پیاده‌سازی واقعی پیدا شد** (در پیام اصلی نبود):
انتخاب خود باینری agent هم به‌اندازه‌ی انتخاب MCP server مهمه - اگه
به‌جای `buzz-agent`، از Claude Code یا Codex یا Goose به‌عنوان
`BUZZ_ACP_AGENT_BIN` استفاده بشه، اون CLIها خودشون ابزار shell/file
داخلی دارن که کاملاً مستقل از هر MCP server ای که بهشون بدی در
دسترسشونه - یعنی فقط دوری از `buzz-dev-mcp` کافی نیست. برای همین در
دستور نهایی از `buzz-agent` خود Block استفاده شده (طبق مستندات خودشون:
«MCP servers (your tools)» - یعنی هیچ ابزاری غیر از چیزی که صراحتاً
بهش می‌دی نداره).

## v28: مورد ۵۸ کامل شد - پایپلاین کامل Soup (چهار اسکریپت جدید)
تا اینجا Soup فقط نصب می‌شد (`09_setup_soup_finetune.sh`)؛ خود
fine-tune/eval/جایگزینی همه دستی و بدون اسکریپت بودن. چهار اسکریپت
جدید دقیقاً همون چهار مرحله‌ای که در پیام مربوطه خواسته شده بود رو
پیاده می‌کنن - **هیچ‌کدوم به‌صورت خودکار روی داده‌ی واقعی مشتری اجرا
نمی‌شن یا مدل production رو عوض نمی‌کنن**؛ فقط ابزار دستیِ هر مرحله رو
می‌سازن:

1. **`21_soup_export_training_data.py`** - اسکریپت `odoo-bin shell`:
   متن هر `company.document` رو (با همون استخراج‌کننده‌ی RAG) می‌خونه،
   از همون `scrub_value()` (مورد ۲۸، Context Firewall - همون تابعی که
   `recall_memory`/`read_attached_file`/audit log استفاده می‌کنن، نه یک
   کپی جدا) رد می‌کنه، و متن پاک‌شده رو در یک JSONL می‌نویسه.
   **صادقانه**: این خروجی متن خام پاک‌شده است، نه جفت instruction/
   response آماده برای soup.yaml - تبدیل به فرمت واقعی آموزش عمداً یک
   قدم انسانی جدا مونده.
2. **`22_soup_train_isolated.sh`** - workspace رو با `incus file push`
   داخل همون کانتینر Incus که برای Hermes (مورد ۱۴) هست کپی می‌کنه،
   `soup train` و `soup ship` رو **آنجا** (نه روی هاست Odoo) اجرا
   می‌کنه، و فقط پوشه‌ی نتیجه (adapter) رو با تایم‌استمپ به هاست برمی‌گردونه
   - هیچ‌جا `/opt/start_vllm.sh` رو لمس نمی‌کنه.
3. **`23_soup_evaluate_candidate.sh <candidate-dir>`** - گیت واقعی
   قبول/رد. **صادقانه (محدودیت سخت‌افزاری واقعی)**: چون مجموع
   `--gpu-memory-utilization` سه سرویس vLLM موجود (۰.۶ متن + ۰.۲۵ ویژن
   + ۰.۱ embedding) از قبل ۰.۹۵ است، جایی برای اجرای هم‌زمان یک مدل
   ~۳۰B دوم روی همین GPU نیست - پس این اسکریپت مدل production رو کنار
   نمی‌ذاره، بلکه یک پنجره‌ی نگه‌داری با حضور اپراتور می‌سازه: خودت
   `start_vllm.sh` واقعی رو (طبق GOLDEN RULE، با Ctrl+C) متوقف می‌کنی،
   اسکریپت یک `start_vllm_candidate.sh` تولید می‌کنه که همون مدل پایه +
   LoRA کاندید رو روی همون پورت ۸۰۰۰ بالا می‌آره، بعد `11_evaluation_
   suite.py` (تنها اسکریپت پروژه که واقعاً از طریق HTTP واقعی به
   `/api/chat` زنگ می‌زنه و مدل کاندید رو واقعاً امتحان می‌کنه) رو به‌عنوان
   گیت سخت اجرا می‌کنه. `05_acceptance_tests.py` هم برای کامل بودن اجرا
   و در گزارش ثبت می‌شه، ولی چون فقط متد ابزارهای Odoo رو مستقیم صدا
   می‌زنه و اصلاً به LLM نمی‌رسه (خودش هم همینو می‌گه)، با تغییر مدل
   نمی‌تونه رگرسیون نشون بده - فقط اطلاعاتیه، نه بخشی از گیت. یک گزارش
   با خط `SOUP_CANDIDATE_EVAL: PASS` یا `FAIL` می‌نویسه.
4. **`24_soup_promote_candidate.sh --candidate ... --report ... --confirm`**
   - تنها اسکریپتی که مجاز به تغییر `/opt/start_vllm.sh` است. بدون
   `--confirm` فقط dry-run است؛ حتی با `--confirm`، اول خود فایل گزارش
   رو برای خط `SOUP_CANDIDATE_EVAL: PASS` پارس می‌کنه (نه صرفاً به فلگ
   اعتماد می‌کنه) و بدون آن رد می‌کنه - هیچ override ای براش نیست - و
   یک تاییدیه‌ی تعاملی دوم (تایپ‌کردن نام پوشه‌ی کاندید) هم می‌خواد. اگر
   قبول شد: نسخه‌ی فعلی `start_vllm.sh` رو timestamp-دار بکاپ می‌گیره،
   نسخه‌ی جدید (همون مدل پایه + `--lora-modules candidate=...`) رو
   می‌نویسه، و **خودش هیچ‌وقت vLLM رو ری‌استارت نمی‌کنه** - دستور دقیق
   توقف/شروع دستی رو چاپ می‌کنه، دقیقاً طبق GOLDEN RULE همون فایل.
   Rollback هم یک `cp` ساده از فایل بکاپ است.

نکته‌ی معماری: promotion با merge کردن وزن‌ها نیست، با اضافه‌کردن
`--enable-lora --lora-modules` به همون مدل پایه‌ی بدون‌تغییر است - یعنی
چک‌پوینت اصلی هیچ‌وقت overwrite نمی‌شه، rollback همیشه یک فایل جایگزینی
ساده است.

جزئیات کامل (شامل نکته‌ی جدید درباره‌ی کلید LLM جدای خود `buzz-agent`،
که یک اعتبار کاملاً جدا از کلید گیت‌وی اودوست) در `roadmap-73-items.md`
مورد ۵۹ و docstring خود `hermes_gateway_mcp_server.py` نوشته شده.

## v13: مورد ۲۷ - RAG واقعی روی اسناد (ماژول جدید `ai_rag`)
جزئیات کامل در `roadmap-73-items.md` مورد ۲۷. خلاصه: `Qwen3-Embedding-0.6B`
روی یک نمونه‌ی سوم vLLM (پورت ۸۰۰۲) + pgvector/HNSW روی همون Postgres
+ یک chunker پاراگراف-آگاه تازه + فیلتر دسترسی قبل از جستجوی برداری.
ابزار جدید: `search_documents_semantic`. نصب: `pip install`های جدید
نیاز نیست (فقط `requests` که از قبل بود)، ولی `01_setup_base.sh`
دو چیز جدید نصب می‌کند: پکیج/سورس pgvector، و اسکریپت
`/opt/start_vllm_embed.sh`.

## v14: موارد ۴۳-۴۴ - Frontend مستقل + لایه‌ی API معنایی
دو چیز جدید:

- **`ai_semantic_api`** (ماژول بک‌اند): endpointهای معنایی
  (`/api/me`, `/api/hr/leaves`, `/api/hr/leaves/<id>/cancel`,
  `/api/documents`, `/api/documents/<id>`, `/api/documents/search`) -
  روی `/api/rpc` (permanently disabled; use named capabilities) موجود اضافه شدن، جایگزینش نکردن. ترجمه‌ی state های
  Odoo (`confirm`→`pending_approval`) فقط در یک تابع
  (`_serialize_leave`) اتفاق می‌افته.
- **`frontend/`** (پوشه‌ی جدا، خارج از `custom_addons/` - این کد Odoo
  نیست): یک اپ React/Vite واقعی با صفحات ورود، مرخصی‌ها، اسناد (+
  جستجوی معنایی)، گفتگو. قانون فایل‌بندی: فقط
  `frontend/src/api/client.js` مجاز است یک URL بشناسد.

نصب/اجرا: `custom_addons/ai_semantic_api` باید مثل بقیه‌ی ماژول‌ها
کپی و در `-i` اضافه بشه (در `02_install_modules.sh` و `README.md`
همین راهنما آپدیت شدن). فرانت جدا اجرا می‌شه: `cd frontend && npm
install && npm run dev` - جزئیات کامل در `frontend/README.md`.

**صادقانه**: این دو (v14) بدون یک نمونه‌ی Odoo واقعی تست شدن (فقط
syntax-check). Admin Console و Document Center واقعی از v21 اضافه شدن
(پایین‌تر) - Tasks/Timesheets/Attendance هنوز endpoint معنایی ندارن؛
جزئیات محدودیت‌های باقی‌مانده در `roadmap-73-items.md` مورد ۴۳-۴۴.

## v15: مورد ۴۹ - Evaluation واقعی روی HTTP (نه فقط ORM)
- **اسکریپت جدید `11_evaluation_suite.py` + `11_evaluation_suite.sh`**:
  یک کلاینت **واقعاً خارجی** - فقط از کتابخانه‌ی `requests` استفاده
  می‌کند، هیچ importی از خود Odoo ندارد - که با کلیدهای API واقعی سه
  کاربر دمو (CEO، حسابدار، انباردار) روی `/api/bootstrap`، `/api/rpc` (permanently disabled; use named capabilities)،
  `/api/chat` واقعی تماس می‌گیرد، دقیقاً همون‌طوری که یک فرانت واقعی
  صدا می‌زنه.
- **چرا این با `05_acceptance_tests.py` فرق داره**: اون اسکریپت متد
  ابزارها رو مستقیم از داخل پردازش Odoo (`odoo-bin shell`) صدا می‌زنه
  - منطق مجوز رو تست می‌کنه ولی هیچ‌وقت لایه‌ی HTTP خودِ کنترلر گیت‌وی
  رو لمس نمی‌کنه (نه CORS، نه rate limit، نه parse شدن header، نه
  کد وضعیت). این اسکریپت جدید دقیقاً همون لایه رو از بیرون تست می‌کنه.
  این دو مکمل هم‌اند، نه جایگزین - `08_deployment_checklist.sh` حالا
  هردو رو اجرا می‌کنه.
- **۹ سناریو**: کلید نامعتبر → ۴۰۱، بدون کلید → رد، CEO با کلید واقعی
  خودش می‌تونه bootstrap کنه، حسابدار نمی‌تونه `hr.employee` رو از
  طریق RPC بنویسه (چون در allowlist نیست)، حسابدار نمی‌تونه
  `ir.model` رو unlink کنه، CORS preflight درست جواب می‌ده، و یک تست
  rate-limit اختیاری (`--run-slow`، چون ۱۴۰+ درخواست HTTP واقعی
  می‌فرسته - پیش‌فرض SKIP می‌شه).
- **صادقانه - چت غیرقطعی**: یک سناریوی چت هم هست (حسابدار یک پیام
  عادی می‌فرسته) ولی صراحتاً `hard=False` (INFORMATIONAL) علامت خورده
  - هیچ‌وقت روی exit code تاثیر نمی‌ذاره، چون خروجی LLM قطعی نیست؛
  همون موضعی که `05_acceptance_tests.py` هم درباره‌ی چت داره.
- **اصلاح صادقانه**: docstring خود `05_acceptance_tests.py` قبلاً
  ادعا می‌کرد مورد ۴۹ رو کامل پوشش می‌ده - این ادعا کامل نبود (مورد
  ۴۹ صراحتاً «کلید API واقعی» و تماس واقعی می‌خواست). این توضیح در
  خود فایل تصحیح شد.

## v16: مورد ۴۸ - Observability
- **`duration_ms`** روی audit log + اندازه‌گیری واقعی در کنترلر گیت‌وی
  برای `/api/rpc` (permanently disabled; use named capabilities) و `/api/chat` (برای `source=tool` عمداً خالی می‌ماند
  - توضیحش در کد هست).
- **`observability_snapshot()`** روی `ai.gateway.audit.log`: یک کوئری
  SQL (نه مدل/pipeline جدید) که درخواست ساعت اخیر/۲۴ساعته، نرخ خطا،
  میانگین تاخیر، و ۵ عملیات پرتکرار رو برمی‌گردونه. هم `/api/metrics`
  هم `12_observability_report.py` از همین یک متد استفاده می‌کنن تا هیچ
  وقت با هم ناسازگار نشن.
- **`GET /api/health`** (بدون کلید API - برای uptime monitor خارجی) و
  **`GET /api/metrics`** (نیاز به کلید یک نقش ممتاز - همون مجموعه‌ای که
  audit log کامل رو می‌بینن: `base.group_system`/Executive/System
  Admin/Security).
- **نمای «AI Observability»** (نمودار خطی + جدول محوری) زیر Settings،
  روی همون جدول audit log - بدون مدل جدید.
- **`12_observability_report.py`**: نسخه‌ی خط‌فرمان همون گزارش.
- ۲ سناریوی جدید به `11_evaluation_suite.py`: health بدون کلید کار
  می‌کنه، حسابدار نمی‌تونه metrics بخونه ولی CEO می‌تونه.

> نکته درباره‌ی شماره‌ی نسخه‌ها از اینجا به بعد: v18 تا v22 در چند
> مکالمه‌ی **موازی و مستقل** ساخته شدند (هرکدوم از همون نقطه‌ی v16/v17
> شروع کرده، بدون اطلاع از بقیه) و بعداً در یک راند جداگانه (v22)
> یکپارچه شدند - برای همینه که v20 (Buzz) از نظر جایگذاری در فایل قبل
> از v18/v19 اومده: هرکدوم فقط ترتیب کاری خودشون رو می‌دونستن، نه
> بقیه رو. شماره‌ها برای ارجاع نگه داشته شدن، نه چون کارها واقعاً به
> همین ترتیب زمانی اتفاق افتادن.

## v18: فاز ۵ - موارد ۲۹، ۳۰، ۳۲، ۳۵ (اتوماسیون - `ai_business_tools`)
- **مورد ۲۹ (Workflow)** نیازی به کد نداشت - فقط تایید شد (سناریوی ۱۹
  در `05_acceptance_tests.py`): تغییر state روی `hr.leave` همین الان
  با tracking خودکار Odoo یک نوتیف چتری می‌سازد.
- **مورد ۳۰ (Events)**: نگاشت `_EVENT_ACTIONS` (`stage_id` و
  `escalation_level`) با override `write()` روی `project.task`
  (`models/task_automation.py`) - تغییرات را روی `bus.bus` پوش می‌کند
  (event `ai_task_event`)، بدون هیچ بروکر مستقلی.
- **مورد ۳۲ (Task System) تکمیل شد**: وابستگی بین تسک‌ها -
  `depends_on_task_ids` روی `project.task`؛ بستن یک تسک با پیش‌نیازِ
  بازِ نبسته با `UserError` رد می‌شود (چه از چت چه از UI). ابزار
  `create_task` پارامتر اختیاری `depends_on_titles` گرفت.
- **مورد ۳۵ (Escalation) تکمیل شد**: فیلد `escalation_level` (۰-۳) +
  کرون روزانه‌ی جدید `cron_escalate_overdue_tasks` که تشدید را طبق
  زنجیره‌ی کارمند→مدیر مستقیم→مدیر بخش→Executive پیش می‌برد. آستانه‌ها
  (پیش‌فرض ۳/۷/۱۴ روز) از `ir.config_parameter` خوانده می‌شوند
  (`data/escalation_config_data.xml`)، قابل تغییر بدون نیاز به کد.
- ۴ سناریوی جدید (وقتی این راند به‌تنهایی نوشته شد، ۱۹ تا ۲۲ بودن؛
  بعد از یکپارچه‌سازی v22 همچنان ۱۹ تا ۲۲ ماندن چون این بلوک اول
  نشست، توضیح کامل در v22 پایین) به `05_acceptance_tests.py` اضافه
  شد.

## v19: فاز ۸ تکمیل شد - موارد ۵۰، ۵۵، ۵۶، ۵۷
- **Security Testing (مورد ۵۰ - تکمیل)**: ۳ سناریوی جدید به
  `05_acceptance_tests.py` اضافه شد (قانون دپارتمانی تسک v17،
  محدودیت انقضای cron-محور `access.grant`، تلاش escalation مستقیم روی
  `res.groups` - این سه بعد از یکپارچه‌سازی v22 به شماره‌های ۲۳-۲۵
  منتقل شدند چون راند v18 بالا هم مستقل، همزمان، از همون پایه شماره‌ی
  ۱۹ رو گرفته بود؛ توضیح کامل در v22) - هیچ‌کدوم قبلاً تست خودکار
  نداشتن. بعلاوه، با خواندن دقیق `gateway.py`، دو شکاف واقعی پیدا و
  بسته شد (نه فقط تست، خودِ کد): ۱) کلیدهای نامعتبر قبلاً هیچ rate
  limit نداشتن (چون `_check_rate_limit` فقط بعد از یک lookup موفق صدا
  زده می‌شد) - یک محدودکننده‌ی جدید IP-محور
  (`AI_GATEWAY_AUTH_FAIL_LIMIT`) اضافه شد. ۲) `/api/chat` هر
  `thread_id` ای که کلاینت می‌فرستاد رو بدون چک مالکیت قبول می‌کرد - یک
  کاربر می‌تونست حدس بزنه/افزایش بده و مکالمه‌ی خصوصی یک کاربر دیگه رو
  بخونه/ادامه بده؛ حالا با `create_uid` چک می‌شه. یک اسکریپت جدید،
  `13_security_testing.py`/`.sh`، این دو رفع را و چند سناریوی
  حمله‌محور دیگه (مدل injection-شکل، عملیات غیرمجاز، payload حجیم/
  بدشکل، متد HTTP اشتباه) رو از بیرون (HTTP واقعی) تست می‌کنه - زاویه‌ی
  سومی که نه `05` (ORM) و نه `11` (HTTP خوشبینانه) پوشش نمی‌دادن.
- **White-label (مورد ۵۵ - تکمیل)**: `14_configure_whitelabel.sh` -
  دیگه نیازی به دستی sed زدن `debrand_data.xml` نیست (که چون
  `noupdate="1"` داره، دوباره‌اجرا کردن `-u ai_debrand` بعد از نصب اول
  این تغییرات رو اعمال نمی‌کرد). این اسکریپت مقادیر رو مستقیم و
  همیشه-قابل‌اجرا از طریق ORM (`odoo-bin shell`) ست می‌کنه - هم برای
  نصب اول هم برای ری‌برند بعدی. یادآوری بازبینی چشمی (لاگین، تب مرورگر،
  یک ایمیل واقعی) که قبلاً در کد بود، همچنان به‌عنوان خروجی این اسکریپت
  چاپ می‌شه - این بخش عمداً هیچ‌وقت خودکار نمی‌شه.
- **Licensing (مورد ۵۶ - یادداشت فنی، نه مشاوره‌ی حقوقی)**:
  `LICENSING_NOTES.md` - جدول لایسنس واقعی هر بخش (۶ ماژول Odoo همه
  LGPL-3، فرانت بدون لایسنس اعلام‌شده - عمداً، چون فرانت جدا از فرآیند
  Odoo اجرا می‌شه)، و نکته‌ی فنی مهم درباره‌ی مرز LGPL بین ماژول‌ها و
  فرانت مستقل. این یک جایگزین وکیل واقعی نیست - خودش هم صریح همین رو
  می‌گه.
- **Customer Onboarding (مورد ۵۷ - تکمیل)**: `15_customer_onboarding.sh`
  - نصب → Excel import → برندینگ → TLS → بکاپ → هر سه مجموعه تست
  (پذیرش/HTTP/امنیتی) → چک‌لیست تحویل، همه با یک دستور، با گیت واقعی
  (`set -e`) روی هر شکست. هر مرحله جدا skip-پذیره (مثلاً
  `SKIP_INSTALL=1`) برای وقتی که بعضی مراحل قبلاً انجام شدن.
- **`08_deployment_checklist.sh` هم به‌روز شد**: بخش «Monitoring» که
  اشتباهاً می‌گفت observability هنوز نیست (درحالی‌که از v16 وجود داره)
  اصلاح شد، بعلاوه چک‌های جدید برای برندینگ (مورد ۵۵) و وجود
  `LICENSING_NOTES.md` (مورد ۵۶) و اجرای `13_security_testing.sh`
  (مورد ۵۰) اضافه شد.

## v21: فاز ۷ - موارد ۴۵-۴۷ (Design System, Admin Console, Document Center)
موارد ۴۳/۴۴ (فرانت مستقل + لایه‌ی API معنایی، v14) قبلاً «شروع‌شده»
بودن؛ این راند سه مورد باقی‌مانده‌ی فاز ۷ رو تکمیل کرد:
- **مورد ۴۵ (Design System)**: یک کتابخانه‌ی کامپوننت واقعی
  (`frontend/src/components/`) - Button، Input، TextArea، Select،
  Badge، Card، Table، Modal، Tabs، Alert، EmptyState، Spinner - به‌همراه
  مستندسازی استفاده (`components/README.md`). هر صفحه‌ی موجود بازنویسی
  شد تا از این کامپوننت‌ها استفاده کند، نه HTML خام.
- **مورد ۴۶ (Admin Console)**: صفحه‌ی جدید `/admin` در فرانت (فقط
  نقش‌های ممتاز) با تب‌های Roles، Access Grants (ساخت/لغو دسترسی
  موقت)، Documents (نمای سراسری سازمان)، Agents (رجیستری ابزار+ریسک)،
  Branding، و Observability. بک‌اند: namespace کاملاً جدید
  `/api/admin/*` در `ai_semantic_api`، پشت یک چک صریح
  (`_require_privileged()`) که مستقل از فرانت روی هر تک‌تک درخواست
  دوباره اجرا می‌شه.
- **مورد ۴۷ (Document Center)**: صفحه‌ی `/documents` بازنویسی شد -
  تب‌بندی بر اساس هر چهار سطح دسترسی (کل‌سازمان/دپارتمان/گروه/شخصی)،
  فرم آپلود (فقط از میان دپارتمان/گروه‌هایی که خودِ کاربر واقعاً عضوشونه)،
  حذف (فقط مالک سند شخصی یا ادمین)، و جستجوی معنایی مورد ۲۷ که از v14
  همینجا بود.

**صادقانه**: این راند بدون یک نمونه‌ی Odoo واقعی نوشته شد - فقط با
`esbuild` سینتکسی/import-resolution چک شد (bundle نهایی بدون خطا ساخته
می‌شه)، نه با اجرای واقعی روی یک Odoo واقعی. `11_evaluation_suite.py`
هنوز سناریوهای `/api/admin/*` یا آپلود/حذف سند رو پوشش نمی‌ده - جزئیات
کامل و شکاف‌های باقی‌مانده در `frontend/README.md`.

## v22: یکپارچه‌سازی نهایی (merge round - همه‌ی راندهای موازی با هم)
v18 تا v21 بالا در **پنج مکالمه‌ی جدا و مستقل** نوشته شدن - هرکدوم از
همون نقطه‌ی v16/v17 شروع کرده بدون اطلاع از بقیه (روش عادی کار روی این
پروژه: هر راند یک zip کامل تحویل می‌داد، نه یک patch روی راند قبلی).
این نسخه (v22) همه‌شون رو در یک درخت واحد و واقعاً قابل‌نصب یکپارچه
می‌کنه. **دو تعارض واقعی پیدا و رفع شد**، نه فقط کپی/پیست فایل‌ها روی
هم:

1. **شماره‌ی سناریوهای تست تصادفی تکرار شده بود**: v18 (اتوماسیون) و
   v19 (Security Testing) هردو مستقل، هر دو از همون نقطه‌ی v17 (تا
   سناریوی ۱۸) شروع کرده بودن و هردو سناریوهای جدیدشون رو از عدد ۱۹
   شروع کرده بودن - یعنی دو فایل `05_acceptance_tests.py` متفاوت،
   هرکدوم با یک «سناریو ۱۹» کاملاً متفاوت. رفع شد با ادغام واقعی هر دو
   بلوک در یک فایل: بلوک v18 (اتوماسیون) سناریوهای ۱۹-۲۲ رو نگه داشت،
   بلوک v19 (Security Testing) به ۲۳-۲۵ منتقل شد - همراه با رفع دو
   تصادم اسم متغیر (`task_b`، `project`) که هردو بلوک مستقل انتخاب
   کرده بودن.
2. **امضای `_authenticate()` عوض شده بود**: v19 (Security Testing) این
   تابع رو در `ai_gateway/controllers/gateway.py` از یک 2-tuple
   `(user, api_key)` به یک 3-tuple `(user, api_key, ip_blocked)` تغییر
   داد (برای محدودکننده‌ی جدید IP-محور). v21 (Admin Console/Document
   Center) که مستقل از v19 نوشته شده بود، در `ai_semantic_api` هنوز
   همون امضای قدیمی 2-tuple رو صدا می‌زد - اگه بدون رفع merge می‌شد،
   دقیقاً همون‌جا (`_require_auth()` در `semantic_api.py`) در اولین
   درخواست واقعی با خطای «too many values to unpack» کرش می‌کرد. رفع
   شد: `_require_auth()` حالا 3-tuple رو می‌خونه و همون رفتار 429 که
   بقیه‌ی route های گیت‌وی برای `ip_blocked` دارن رو تکرار می‌کنه.

**بعد از رفع این دو، کل درخت به‌طور کامل اعتبارسنجی شد**: هر فایل
پایتون (`ast.parse`)، هر فایل XML، هر CSV (طول ردیف‌ها)، و کل درخت
frontend (با `esbuild`، bundle کامل، import-resolution، بدون خطا) -
همه بدون خطا. هیچ فایلی از هیچ‌کدوم از پنج راند گم نشد (با
`diff -rq` هر راند در برابر نتیجه‌ی نهایی چک شد).

**صادقانه، همچنان**: این یکپارچه‌سازی، مثل هرکدوم از پنج راند بالا،
روی یک نمونه‌ی Odoo واقعی اجرا نشده - فقط سینتکس/ساختار/import
اعتبارسنجی شدن، نه رفتار واقعی در زمان اجرا. قبل از تحویل به مشتری،
یک دور کامل دستی (طبق `15_customer_onboarding.sh` یا حداقل
`05_acceptance_tests.py` + `11_evaluation_suite.sh` + `13_security_testing.sh`
+ `08_deployment_checklist.sh`) الزامی‌ست - این تازه اولین باری‌ست که
همه‌ی این ماژول‌ها با هم، در یک نصب واحد، قرار است اجرا بشن.

## v23: دور ممیزی عمیق (نه یکپارچه‌سازی - یک راند جداگانه‌ی بررسی)
درخواست صریح بود: «همه چیز رو دقیق چک کن - مثلاً اگه یک دپارتمان یک
گروه بزنه، ایجنت هم اونو می‌بینه؟» به‌جای فقط جواب‌دادن، کد واقعاً
خط‌به‌خط خونده شد - مسیر دسترسی سند/تسک از `ir.rule` تا هر متد
`@llm_tool`، بعلاوه هر ۲۳ ابزار AI موجود در کل پروژه به‌صورت خودکار
لیست و با `tool_risk_data.xml` مقایسه شدن.

**نتیجه‌ی معماری: درست بود.** `list_documents`، `list_overdue_tasks`،
و `search_documents_semantic` هرسه از `self.env` (نه `sudo()`)
استفاده می‌کنن، پس `ir.rule` روی `company.document`/`project.task`
(شامل چک‌های `group_id`/`department_id` در `document_rules.xml` و
`task_department_rules.xml`) خودکار روی همه‌شون اعمال می‌شه - چه
فراخوانی از فرانت بیاد چه از خودِ چت. حتی مسیر پرریسک‌تر
(`search_similar`'s raw-SQL pgvector query، که `ir.rule` رو دور
می‌زنه) هم قبل از SQL یک `search()` واقعی روی ORM اجرا می‌کنه که
همون rule رو اعمال می‌کنه - تایید شد که درست کار می‌کنه.

**ولی ۴ مشکل واقعی هم پیدا و رفع شد** (جزئیات کامل هرکدوم در
`roadmap-73-items.md`، بخش خلاصه‌ی v23، و کامنت‌های «GAP FOUND» مستقیم
توی کد):
1. باگ در فرم آپلود Document Center (کار خودِ v21): دپارتمان می‌شد به
   هر مقداری ست بشه، نه فقط دپارتمان خودِ کاربر (`ir.rule` جلوش رو
   می‌گرفت، ولی با خطای گیج‌کننده؛ منوی فرانت هم گزینه‌های نامعتبر نشون
   می‌داد).
2. سناریوی تست گروه/دپارتمان روی `company.document` هرگز نوشته نشده
   بود - در هیچ‌کدوم از ۵ راند - اضافه شد (سناریو ۲۶).
3. ۵ از ۲۳ ابزار AI موجود اصلاً در `tool_risk_data.xml` ثبت نشده بودن
   (`get_current_datetime`، `list_available_tools`،
   `read_attached_file`، `search_documents_semantic`،
   `search_internet`) - یعنی تب Agents در کنسول مدیریت این ۵ تا رو
   نشون نمی‌داد. رفع شد.
4. `list_documents`/`get_document` فیلد `description` سند رو بدون
   عبور از Context Firewall (مورد ۲۸) برمی‌گردوندن، برخلاف
   `search_documents_semantic` که این کار رو می‌کرد. رفع شد + سناریو
   ۲۷ اضافه شد.

**صادقانه**: این دور هم، مثل v22، روی یک Odoo واقعی اجرا نشده - فقط با
خوندن دقیق کد + اعتبارسنجی سینتکسی/ساختاری کامل (پایتون، XML، CSV،
شل، و کل frontend با `esbuild`). عمق این ممیزی نشون می‌ده که خوندن
دقیق کد چیزهایی پیدا می‌کنه که چک سینتکسی نمی‌تونه - ولی جایگزین یک
دور واقعی روی یک دیتابیس زنده نیست.

## v24: ورود با یوزر/پسورد + رفع نشت نام Odoo در چت
درخواست مستقیم بود - دو چیز مشخص:
1. **فرانت باید با ایمیل/پسورد وارد بشه، نه با کلید خام.** `/api/login`
   (جدید، `ai_semantic_api`) پسورد واقعی Odoo همون کاربر رو چک می‌کنه
   (`request.session.authenticate`) و در جواب موفق، همون
   `ai.gateway.api.key` موجودش رو برمی‌گردونه - هیچ سیستم احراز هویت
   موازی جدیدی ساخته نشد، فقط یک لایه‌ی «مبادله‌ی پسورد با کلید» روی
   همون معماری stateless قبلی. سشن Odoo بلافاصله بعدش logout می‌شه
   (`keep_db=True`) که یک کوکی بک‌اند اضافه توی مرورگر یک فرانت
   API-only نمونه. همون محدودکننده‌ی IP فاز ۸ (roadmap #50) برای ضد
   حدس‌زدن پسورد هم استفاده مجدد شد. `LoginPage.jsx` و `client.js`
   بازنویسی شدن.
2. **نشتِ نام Odoo در خودِ چت.** ریشه پیدا شد: پرامپت خودِ دستیار
   (`company_ai_demo/data/llm_agent_data.xml`) عیناً می‌گفت *"running
   inside Odoo"*. حذف شد + یک قانون صریح («۱۳») اضافه شد: هرگز نام
   Odoo/پلتفرم فنی/مدل زبانی رو نگو، حتی اگه مستقیم بپرسن - فقط بگو
   «من دستیار داخلی همین شرکتم». چون این فایل `noupdate="1"` داره
   (دقیقاً همون مشکلی که `debrand_data.xml` هم داشت)،
   `14_configure_whitelabel.sh` گسترش داده شد تا این پچ رو مستقیم روی
   دیتابیس زنده هم (نه فقط نصب تازه) از طریق ORM اعمال کنه.

**یک باگ واقعی هم موقع این کار پیدا و رفع شد**: `15_customer_
onboarding.sh` (فاز ۸) هنوز فرض می‌کرد `onboard_from_excel.py` یک
اسکریپت کاملاً غیرتعاملیه - ولی از وقتی موارد #36/#37 (Preview/
Approval) اضافه شدن، اون اسکریپت یک `input()` واقعی داره. چون
ارکستریتور از طریق stdin pipe اجرا می‌شه (نه ترمینال)، این `input()`
بلافاصله با EOFError می‌ترکید. رفع شد با `ONBOARD_YES=1` +
`ONBOARD_FILE` (که خودِ اسکریپت onboarding از قبل پشتیبانی می‌کرد).

## v25: دور تحقیق «چیز جدیدی منتشر شده که بشه باهاش ارتقا داد؟»
درخواست صریح بود: تحقیق کامل و به‌روز، نه حدس. نتیجه با جستجوی واقعی
وب (نه از حافظه‌ی مدل):

**۱. رفع شد در کد (نه فقط پیشنهاد) - یک آسیب‌پذیری واقعی:**
`CVE-2026-3172` (CVSS 8.1) یک buffer overflow در ساخت ایندکس HNSW
موازی pgvector هست، در نسخه‌های ۰.۶.۰ تا ۰.۸.۱ (رفع‌شده در ۰.۸.۲) -
یک کاربر دیتابیس می‌تونه داده از جدول‌های دیگه بخونه یا کل Postgres رو
کرش کنه. `01_setup_base.sh` دقیقاً `v0.8.0` رو pin کرده بود (توی
بازه‌ی آسیب‌پذیر) و `ai_rag` واقعاً همین نوع ایندکس رو می‌سازه
(`CREATE INDEX ... USING hnsw` در `document_chunk.py`) - یعنی این
تئوری نبود، مستقیم روی این پروژه قابل‌اجرا بود. رفع شد: pin به
`v0.8.2` + یک چک نسخه‌ی خودکار بعد از نصب که هر دو مسیر (پکیج
توزیع/build از سورس) رو verify می‌کنه و اگه نسخه‌ی آسیب‌پذیر بود
هشدار می‌ده. **اگه از قبل روی یک دستگاه نصب‌شده هستید**: نسخه رو چک
کنید (`SELECT extversion FROM pg_extension WHERE extname='vector';`)
و اگه بین ۰.۶.۰ تا ۰.۸.۱ بود، pgvector رو آپدیت کنید و روی هر دیتابیس
`ALTER EXTENSION vector UPDATE;` بزنید.

**۲. رفع شد در کد - یک ریسک reproducibility:** کلون `odoo-llm` به هیچ
branch/tag ای pin نبود (فقط شاخه‌ی پیش‌فرض ریپو، که می‌تونه هر وقت
عوض بشه) - حالا صریح به شاخه‌ی `18.0` (که خودِ apexive نگه می‌داره و
هنوز فعاله - مثلاً یک قابلیت جدید MCP Server هم بهش اضافه کرده) pin
شد.

**۳. مستندسازی شد به‌عنوان گزینه (نه سوییچ خودکار):** دو مدل بازتر و
جدیدتر از چیزی که الان استفاده می‌شه پیدا شد:
- **Qwen3.6-27B** (Apache-2.0، آوریل ۲۰۲۶) - دنس (نه MoE)، روی یک GPU
  معمولی جواب می‌ده، طبق ادعای خودِ Qwen در tool-calling حتی از
  فلگ‌شیپ بزرگ‌تر ۳.۵ بهتره - مستقیماً مرتبط با این پروژه که ۲۳ تا
  `@llm_tool` داره. سوییچ خودکار نشد چون پروفایل حافظه‌ش (دنس، نه
  AWQ-quantized) با چیزی که `01_setup_base.sh` برای سخت‌افزار GB10
  اعتبارسنجی کرده فرق داره - باید قبل از اعتماد، هر ۳ suite تست
  (۰۵/۱۱/۱۳) دوباره روش اجرا بشه.
- **Qwen3-VL-30B-A3B** - ارتقای واقعی نسل روی `Qwen2.5-VL-7B` فعلی
  (OCR بهتر، spatial reasoning، tool-use بومی) - نیاز به `vllm>=0.11.0`
  که چون اسکریپت فعلی همیشه `pip install -U vllm` می‌زنه احتمالاً از
  قبل برقراره.

هر دو به‌صورت کامنت مستند در `01_setup_base.sh` کنار دستور `vllm
serve` مربوطه گذاشته شدن، نه به‌عنوان دیفالت جدید - همون فلسفه‌ای که
از اول این پروژه داشت («یک تغییر مشخص و تست‌شده، نه یک آپدیت گسترده‌ی
تایید‌نشده»).

**۴. دیده شد ولی عمداً کاری نشد (بزرگ‌تر از یک راند کدنویسیه):** Odoo
**19.3** الان نسخه‌ی پایدار فعلیه (این پروژه روی Odoo **18** ساخته
شده) و Odoo 20 برای اکتبر ۲۰۲۶ اعلام شده. ارتقای نسخه‌ی اصلی Odoo یک
پروژه‌ی migration واقعی با ریسک واقعیه (همه‌ی ۶ ماژول سفارشی باید
دوباره تست بشن) - نه چیزی که این‌جا خودکار انجام بشه. اگه به فکرشید،
اول یک کپی از دیتابیس رو روی یک نسخه‌ی تست از 18 به 19 upgrade کنید
(Odoo خودش این مسیر رو رسمی پشتیبانی می‌کنه)، هر ۳ suite تست رو
دوباره اجرا کنید، بعد تصمیم بگیرید.

## v26: دور تحقیق دوم - «چیز جداگانه‌ای هست که بشه بهش وصل شد؟»
درخواست صریح بود: نه ارتقای داخلی کد، بلکه سیستم‌های **جدا و بیرونی**
که تازه معرفی شدن و می‌شه به این پروژه وصل کرد تا سرعت/دقت/عملکرد
بالا بره - دقیقاً همون الگوی مورد ۵۸ (Soup) و ۵۹ (Buzz)، نه یک راند
کدنویسی داخلی. نتیجه با سرچ واقعی وب:

**۱. Muse Glimmer (مدل، Meta، ۱۰ اوت ۲۰۲۶) - مستندسازی شد، سوییچ
نشد.** جزئیات کامل (بنچمارک‌های واقعی، جواز Apache-2.0 خالص، و
مهم‌تر از همه دلیل مشخصی که سوییچ نشد: پشتیبانی vLLM هنوز از طریق یک
PR ادغام‌نشده است، نه نسخه‌ی پایدار) در `roadmap-73-items.md` مورد ۲۴
و کامنت `01_setup_base.sh` است. خلاصه‌ی یک خطی: این آیتم (که از قبل،
از قبل از وجود این مدل، اسمش «Qwen/Glimmer Benchmark» بود) حالا یک
کاندید واقعی و مشخص داره، نه یک اسم فرضی.

**۲. DFlash (تکنیک سرعت، z-lab/UCSD، متن‌باز) - بررسی شد، فعلاً
قابل‌اعمال نیست.** یک drafter سبک برای speculative decoding که با یک
پرچم config (نه تغییر کد) روی vLLM/SGLang سوار می‌شه و ادعای ۲ تا ۶
برابر سرعت داره - دقیقاً همون چیزی که خواسته شده بود («یه چیز جداگانه
که وصل بشه و سرعت رو بالا ببره»). ولی: هر چک‌پوینت DFlash فقط برای
یک مدل هدف مشخص train شده؛ تنها چک‌پوینت تاییدشده برای خانواده‌ی
Qwen3-30B-A3B (یعنی `z-lab/Qwen3-Coder-30B-A3B-DFlash`) برای نسخه‌ی
**Coder** ترین شده، نه برای `cpatonn/Qwen3-30B-A3B-Instruct-2507-AWQ`
که این پروژه واقعاً استفاده می‌کنه - یعنی فعلاً یک drafter تاییدشده
و match برای مدل دقیق این پروژه پیدا نشد. ثبت شد به‌عنوان کاندید آینده
(اگه z-lab دستور train خودشون رو منتشر کنه، می‌شه یک drafter اختصاصی
با همون زیرساخت Soup/مورد ۵۸ ساخت)، نه چیزی که الان وصل بشه.

**۳. Buzz (مورد ۵۹) - از قبل ساخته شده، عمداً وصل نیست.** این سوال
مستقیم پرسیده شده بود: «الان چرا وصل نیست؟». جواب دقیق: پل
(`buzz_bridge/hermes_gateway_mcp_server.py`) و اسکریپت نصب
(`10_setup_buzz.sh`) از v20 وجود دارن و کامل کار می‌کنن، ولی **از قبل،
عمداً**، `03_start_all.sh` هیچ‌وقت relay/agent مربوط به Buzz رو
استارت نمی‌کنه و هیچ کلید API واقعی مشتری در هیچ فایلی هاردکد نشده -
این یک تصمیم امنیتی صریحه (همون فلسفه‌ی مورد ۵۸/۵۹ از اول: «فقط نصب
اولیه، وصل‌کردن واقعی همیشه دستی»)، نه یک کار نصفه‌کاره‌ی
فراموش‌شده. **برای وصل‌کردن واقعی** (یک pilot، یک کانال، یک agent)،
دقیقاً ۵ قدم چاپ‌شده در خروجی خودِ `10_setup_buzz.sh` را دنبال کن؛
خلاصه‌شون:
1. `./10_setup_buzz.sh` را اجرا کن (فقط clone/build/نصب پل، چیزی
   استارت نمی‌شه).
2. یک `ai.gateway.api.key` واقعی برای همون کاربر اودویی که این agent
   قراره جای اون کار کنه بساز (Settings > Technical، یا از خروجی
   `onboard_from_excel.py`).
3. یک کلید Nostr مجزا برای همین هویت agent بساز
   (`buzz-admin generate-key`) - هرگز یک کلید مشترک بین چند agent.
4. یک relay محلی رو استارت کن (`cd /opt/buzz && just dev`) و
   `buzz-acp` رو دقیقاً با دستوری که خودِ اسکریپت چاپ می‌کنه اجرا کن
   (`--mcp-server` به پل بالا، `--agent-bin` به `buzz-agent` - نه
   `buzz-dev-mcp`، نه Claude Code/Codex/Goose، طبق دلیل کامل نوشته‌شده
   در مورد ۵۹).
5. قبل از فراتر رفتن از یک کانال pilot، هر سه فراخوانی پل
   (`gateway_bootstrap`/`gateway_rpc`/`gateway_chat`) رو در Audit Log
   گیت‌وی (Settings > Administration) چک کن - باید دقیقاً مثل یک
   فراخوانی از فرانت React ثبت بشن.
هیچ‌کدام از این ۵ قدم خودکار نشدن و نباید بشن - چون قدم ۲ و ۳ به یک
کلید واقعی مشتری نیاز دارن که نباید در هیچ اسکریپتی هاردکد بشه.

**۴. چیزهایی که سرچ شدن ولی رد شدن** (برای شفافیت، نه فقط چیزهایی که
تایید شدن): چند ابزار observability متن‌باز (Langfuse، Arize Phoenix،
OpenObserve) بررسی شدن اما هیچ‌کدام «تازه‌معرفی‌شده» نبودن (همه از قبل
از این پروژه وجود داشتن) و همه به زیرساخت اضافه (ClickHouse/Redis/...)
نیاز دارن - دقیقاً همون نوع پیچیدگی‌ای که این پروژه از اول عمداً ازش
پرهیز کرده (مثل انتخاب pgvector به‌جای Qdrant در مورد ۲۷)؛ observability
فعلی (مورد ۴۸، مبتنی بر audit log خودِ گیت‌وی) برای مقیاس این پروژه
کافی باقی می‌مونه، این‌ها اضافه نشدن.

## v27: مورد ۶۰ کامل شد - پل واقعی Telegram
سوال مستقیم بود: «کارمندها می‌تونن از تلگرام کاراشونو انجام بدن؟».
جواب قبل از این دور: نه، هیچ کد Telegram‌ای وجود نداشت. الان
`custom_addons/ai_telegram_bridge` هست.

قبل از کدنویسی، `OdooPilot` (github.com/arunrajiah/odoopilot، LGPL-3)
پیدا و راستی‌آزمایی شد - یک addon واقعی که همین کار رو می‌کنه، با
موتور LLM و مدل تایید/دسترسی خودش. عمداً نصب نشد: یک مسیر امنیتی موازی
با Risk Engine/Approval Object/Context Firewall/allowlist این پروژه
می‌بود - دقیقاً همون نگرانی که برای `buzz-dev-mcp` هم مطرح شد.

به‌جاش، یک ماژول اودوی واقعی ساخته شد که هر پیام تلگرام رو به همون
`/api/chat` خودِ همین پروژه forward می‌کنه (با کلید API واقعیِ همون
کارمند) - همون Risk Engine، همون Approval Object، همون Audit Log،
بدون استثنا. جزئیات کامل (مدل هویت، جریان اتصال با اثبات هویت با کد
یک‌بارمصرف، امنیت webhook، محدودیت‌ها) در `roadmap-73-items.md` مورد
۶۰. راهنمای کامل نصب/اتصال دستی در `16_setup_telegram.sh`.

**صادقانه، خلاصه**: بدون دکمه‌ی تایید inline (OdooPilot این رو داره)،
بدون پیام صوتی، تست خودکار نشده (نیاز به بات واقعی داره) - دقیقاً همون
سطح صداقتی که برای پل Buzz (v20) هم رعایت شد.

## v28: صفحه‌ی Integrations برای تلگرام - بدون نیاز به بک‌اند اودو
سوال مستقیم بود: تا اینجا تنها راهِ وصل‌کردن تلگرام یک ویزارد داخل
بک‌اند اودو بود ("AI Telegram" > "Generate Link Code") - یعنی کارمندی
که فقط از این پورتال React استفاده می‌کنه، هنوز مجبور بود یک‌بار بره
تو بک‌اند اودو، دقیقاً همون چیزی که مورد ۴۳/۴۴ (Semantic API) قرار بود
جلوش رو بگیره.

سه endpoint جدید به `ai_semantic_api/controllers/semantic_api.py`
اضافه شد (`/api/integrations/telegram`, `/telegram/code`,
`/telegram/unlink`) که همون دو مدل موجود
(`ai.gateway.telegram.link[.code]`) رو صدا می‌زنن - هیچ منطق
لینک‌کردنِ جدیدی نوشته نشد. `ai_telegram_bridge` عمداً soft dependency
موند (همون الگوی `ai.gateway.model.policy` در همین فایل) - یعنی اگه
این ماژول نصب نباشه، این endpoint ها به‌جای کرش کردن، فقط
`{"available": false}` برمی‌گردونن.

صفحه‌ی جدید `frontend/src/pages/IntegrationsPage.jsx` (نویگیشن:
«یکپارچه‌سازی‌ها»، در دسترس همه‌ی کاربران - نه فقط ادمین، مطابق همون
قانونی که خودِ ویزارد اودو داشت) وضعیت اتصال رو نشون می‌ده، دکمه‌ی
گرفتن کد داره، و با poll هر ۳ ثانیه‌ای خودش رو به‌محض اتصال واقعی
(بعد از این‌که کارمند `/link CODE` رو تو تلگرام فرستاد) به‌روز می‌کنه -
بدون رفرش دستی.

**صادقانه**: این فقط تلگرام رو پوشش می‌ده (تنها یکپارچه‌سازی واقعیِ
موجود در پروژه، مورد ۶۰). صفحه به شکلی نوشته شده که یکپارچه‌سازی بعدی
(مثلاً واتساپ) بتونه یک Card دیگه به همین صفحه اضافه کنه، ولی خودِ آن
یکپارچه‌سازی این دور ساخته نشده.

## v29: داده‌ی دمو غنی + دیپلوی واقعی فرانت (رفع سه دغدغه‌ی فروش)
- **`04_seed_demo_data.py`/`.sh`** (⚠️ فقط برای دموی فروش خودت، هرگز
  روی دیتابیس مشتری واقعی): ۶ دپارتمان، ۱۴ کارمند پخش‌شده روی همه‌ی
  Role Templateها، درخواست‌های مرخصی با وضعیت‌های مختلف، تسک‌ها (بعضی
  عمداً عقب‌افتاده)، یک سند در هر ۴ سطح دسترسی، یک تاییدیه‌ی معلق، و
  یک دسترسی موقت فعال - یعنی همین الان با نصب، سیستم پر و کاربردیه،
  نه یک پوسته‌ی خالی. Idempotent (اجرای دوباره چیزی خراب نمی‌کنه).
- **`17_setup_frontend.sh`** - جواب مستقیم «فرانتو چیکار کنم»:
  - `--dev`: همین الان با یک دستور (`npm run dev`) فرانت رو روی
    `localhost:5173` بالا می‌آره، بدون نیاز به دامنه یا nginx - برای
    دیدن سریع محصول.
  - `DOMAIN=... ./17_setup_frontend.sh`: build واقعی + یک فایل کامل
    nginx (نه patch شکننده‌ی فایل قبلی) که فرانت رو روی `/` سرو
    می‌کنه، API روی `/api/`، بک‌اند خام Odoo روی `/odoo/` (برای کارهای
    فنی/ادمین) - همه پشت همون دامنه و همون گواهی TLS.
  - `15_customer_onboarding.sh` حالا این مرحله رو خودش صدا می‌زنه
    (قبلاً اصلاً فرانت رو دیپلوی نمی‌کرد - یعنی مشتری فقط API می‌گرفت،
    نه یک وب‌سایت واقعی؛ این باگ واقعی بود، الان رفع شد).
  - `08_deployment_checklist.sh` حالا چک می‌کنه فرانت واقعاً build و
    سرو شده، وگرنه تحویل رو FAIL می‌کنه.

## v30: تلاش برای یکپارچگی TencentDB Agent Memory (⚠️ نیمه‌تایید‌شده، بخوان قبل از اجرا)

**خلاصه‌ی صادقانه:** TencentDB Agent Memory یک پروژه‌ی واقعی و متن‌باز
Tencent Cloud (MIT) است که حافظه‌ی لایه‌ای خودکار (L0 خام ← L1 فکت ←
L2 صحنه ← L3 پرسونا) می‌سازد. **این نسخه یکپارچگی رو فعال کرده، ولی
من نتونستم خودم اجراش کنم و تستش کنم** چون نیاز به سرور واقعی/GPU
داره که من دسترسی ندارم - قبل از اعتماد کامل بهش، حتماً مراحل زیر رو
خودت تایید کن.

- **`18_setup_tencentdb_memory.sh`**: به‌جای حدس‌زدن، مخزن واقعی رو
  کلون می‌کنه و خودش مستندات فعلیش رو می‌خونه تا بگه مسیر بدون Docker
  وجود داره یا نه (پروژه خیلی جدیده - می‌دونیم پایه‌ی حافظه‌ی L0-L3
  با یک پلاگین npm بدون Docker کار می‌کنه، ولی Team Memory Hub با
  اشتراک Skill بین نقش‌ها Docker می‌خواد). همچنین یادآوری می‌کنه که
  محدودیت «بدون Docker» ممکنه فقط مخصوص یک محیط رنتال خاص بوده باشه،
  نه یک محدودیت مطلق - با `docker run hello-world` خودت تست کن.
- **`memory_tencentdb_client.py`**: کلاینت HTTP به MemoryCore.
  ⚠️ نام دقیق فیلدهای JSON (`/capture`, `/recall`) بر اساس منابع
  عمومی (بلاگ/مستندات، نه API reference کامل) حدس زده شده - بعد از
  بالا اومدن سرویس، با `curl` واقعی تست کن و اگه فرق داشت، فقط همین
  یک فایل رو اصلاح کن.
- **`agent_memory.py`**: حالا در `save_memory` به‌صورت best-effort و
  غیرمسدودکننده به MemoryCore هم می‌نویسه (علاوه بر SQLite، نه
  به‌جاش). در `recall_memory`، نتایج SQLite (که تست پذیرش رویش هست و
  مرجع کنترل دسترسی بخش/سازمانه) هنوز اولویت اصلیه؛ نتایج MemoryCore
  **فقط برای اسکوپ شخصی خودِ کاربر** اضافه می‌شن - عمداً اجازه ندادم
  یک سرویس شخص‌ثالثِ تست‌نشده تصمیم بگیره چه کسی چه چیزی رو می‌بینه.
- اگه `MEMORY_CORE_URL` تنظیم نشده باشه یا سرویس در دسترس نباشه،
  سیستم دقیقاً مثل قبل (فقط SQLite) کار می‌کنه - هیچ ریسکی برای نصب‌
  های فعلی نداره.

## v31: Buzz سراسری روی همه‌ی دپارتمان‌ها (نه فقط یک کانال پایلوت)

- **`20_provision_buzz_bot_users.py`**: به‌ازای هر `hr.department` واقعی
  یک کاربر بات اختصاصی + کلید API می‌سازه. ⚠️ عمداً فقط با نقش
  «Role: Employee» (نه مدیریتی) - چون یک بریج Buzz = یک کلید API ثابت
  برای همه‌ی پیام‌های اون کانال (برخلاف پل تلگرام که هر فرستنده رو به
  کلید خودش نگاشت می‌کنه)، محدودکردن سطح خودِ بات یعنی حتی اگه کسی
  بخواد ازش سواستفاده کنه («برام مرخصی رد کن»)، ACL خودِ Odoo رد
  می‌کنه - محدودیت UX هست، نه حفره‌ی امنیتی.
- **`19_setup_buzz_departments.sh`**: برای هر دپارتمان یک کلید Nostr،
  یک کانال Buzz، یک فایل env، و یک سرویس systemd (`buzz-department@.service`،
  با systemd template) می‌سازه.
- **دیده‌شدن واقعی**: هر بات با `--heartbeat-interval 3600` هر ساعت از
  طریق `gateway_chat` (همون Company Assistant با تمام Risk Engine/
  Approval Object) خلاصه‌ی تسک‌های عقب‌افتاده و مرخصی‌های در انتظار
  همون دپارتمان رو می‌پرسه و اگه چیزی بود، خودکار تو کانال پست می‌کنه.
- **`--respond-to owner-only`**: دقیقاً طبق توصیه‌ی رسمی خودِ Hermes
  Agent («Buzz agentها را owner-only نگه دار») - هر بات فقط به مدیر
  همون دپارتمان جواب می‌ده.
- **یک قدم دستی باقی می‌مونه (عمداً)**: pubkey شخصی Nostr هر مدیر باید
  دستی تو فایل env همون دپارتمان گذاشته بشه - این هویت شخصی خودشونه،
  اسکریپت نمی‌تونه حدس بزنه یا جعلش کنه.
- ⚠️ **صادقانه**: من نتونستم این رو خودم اجرا/تست کنم (نیاز به سرور
  واقعی + Nostr relay داره). فلگ‌های `buzz-acp` از مستندات رسمی پروژه
  تایید شدن، ولی قبل از اجرای واقعی حتماً `buzz-acp --help` رو خودت
  چک کن، چون پروژه خیلی جدیده و ممکنه فلگ‌ها عوض شده باشن.

## Historical notes (not production claims)
- Generation speed can still be inconsistent depending on what else is
  sharing the physical host at that moment on some rental platforms -
  this is outside what any code fix can control.
- `/api/chat` is synchronous only (no streaming yet).
- Rate limiting exists (roadmap #52, per-key sliding window) and, as of
  v19, so does a separate IP-keyed limiter for failed-auth attempts -
  neither is backed by Redis/an external store, so both reset on an
  Odoo restart. Fine for a single-process delivery; revisit if this
  ever runs behind multiple Odoo worker processes sharing no state.
- Full custom Owl.js dashboard is still a separate, not-yet-built
  project. Background/scheduled agents already exist via `ir.cron`
  (escalation, access-grant expiry, RAG reindex, overdue-task notify).
  Persistent vector-DB RAG is no longer unbuilt - see roadmap #27 /
  `ai_rag` (pgvector, not Qdrant/ChromaDB, was the deliberate choice).
- The Excel Onboarding Preview/rollback rewrite (roadmap #36/#37) is
  DONE (v19/f14 round) - `onboarding/onboard_from_excel.py` now does
  Parse → Validate → Normalize → Department → Position → Manager →
  Role Mapping → Preview → Approval → Import with a real
  `env.cr.savepoint()`, not the earlier "still open" version.
- `/api/admin/*` (Admin Console) and document upload/delete
  (Document Center) are NOT yet covered by `11_evaluation_suite.py` or
  `13_security_testing.py` - both suites predate v21. A reasonable next
  step, not a blocker for internal testing, but do this before treating
  those two screens as adversarially-tested.
- This v22 merge itself has not been run against a live Odoo instance
  yet (see v22's own note above) - budget one real end-to-end pass
  before the next customer delivery.
- Buzz (roadmap #59) is fully built (bridge + setup script) but
  deliberately not wired up or started by default - see v26's note
  above for the exact 5 manual steps to pilot it for real.
- Telegram Bridge (roadmap #60) is fully built (`ai_telegram_bridge`
  module + `16_setup_telegram.sh`) but, same reasoning as Buzz, not
  installed or wired by default - see v27's note above for what it
  does and does not do, and the setup script for the exact manual
  steps (bot token, webhook, per-employee linking).

## v32 integration-hardening release

This release adds the `ai_control_plane` module and hardens the AI gateway/tool surface. See `INTEGRATION_HARDENING.md` for the exact changes and validation limits.
