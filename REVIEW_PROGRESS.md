# REVIEW_PROGRESS.md — نقطهمرجع ادامهٔ کار پس از قطعی

این فایل نگهبانِ ادامهٔ کار است. بعد از اتمام هر «مورد X»، یک ورودی
«مورد X تمام شد» بههمراه شرحِ دقیقِ تغییر پایین این فایل اضافه
میشود، تا اگر اتصال قطع شد با `opencode --continue` دقیقاً بدانی از
کدام مورد ادامه بدهی. ترتیب موارد منطبق بر دستور کار است (P0 → P1 → P2 ← پایان).

---

## وضعیت فعلی (آخرین بار اجرا: پایان این فایل)

✅ **همهٔ کارها انجام شده** — موارد ۱ تا ۷ کامل، manifest بازتولید و راستیآزمایی
شده (۳۷۹/۳۷۹)، گیتها اجرا شدهاند (`FINAL_PRODUCTION_GATE`: ۲۱/۲۱)، و
خلاصهٔ نهایی همین پایین ثبت است. ادامه از این نقطه فقط در صورت درخواست جدید.

---

## مورد ۱ تمام شد
**P0: تابع `_client_ip` تعریف شد** در
`custom_addons/ai_gateway/controllers/gateway.py`
(بعد از `_record_auth_failure`، زیرِ تابعهای کمکی همتراز
`_authenticate`/`_is_privileged`). بدنه: `return request.httprequest.remote_addr or ""`
با کامنت دربارهٔ `proxy_mode=True` و رزولوشن X-Forwarded-For توسط Odoo.
این تابع برای `_authenticate` (خط ۸۷) و ایمپورتِ `semantic_api.py` فراهم شد؛
قبلاً `_client_ip()` در هیچجا تعریف نبود (باگ P0).

## مورد ۲ تمام شد
**P0: منطق `/api/chat` به تابع ماژول-سطح `_run_chat(user, message, thread_id=None, attachment_ids=None)`
استخراج شد** در `gateway.py` (کاپ کاملِ مدیریت thread-ownership، tool-allowlist،
مالکیت attachment و audit). route اصلی `/api/chat` حالا فقط auth/rate-limit/
parse ورودی را انجام میدهد و بلافاصله `_run_chat` را صدا میزند (بدون تکرار منطق).
در `custom_addons/ai_telegram_bridge/controllers/telegram.py`:
ایمپورت `from odoo.addons.ai_gateway.controllers.gateway import _run_chat` اضافه شد؛
جستجوی `api_key_rec` و تابع قدیمی `_call_gateway_chat` حذف شدند؛ webhook حالا مستقیم
`_run_chat(link.user_id, ...)` را صدا میزند — بدون HTTP loopback و بدون API key.
docstring ماژول و کامنت کلاس هم با این طراحی هماهنگ شد.
**بررسی syntax:** `ast.parse` روی `gateway.py` و `telegram.py` انجام شد → هیچ خطایی.

## مورد ۳ تمام شد
**P1: روتر تکراری `/api/integrations` هنوز وجود داشت — برطرف شد.**
در `custom_addons/ai_control_plane/controllers/api.py` مسیرها منتقل شدند:
- `/api/integrations` → `/api/control-plane/integrations`
- `/api/integrations/sync` → `/api/control-plane/integrations/sync`
مسیر `/api/integrations` حالا فقط در `semantic_api.py` (admin-gated با `base.group_system`) تعریف است.
سند `INTEGRATION_HARDENING.md` هم بهروز شد. هیچ ارجاع frontend/اسکریپتی به مسیر قبلی
کنترلپلین پیدا نشد (تأیید با grep سراسری).

## مورد ۴ تمام شد
**P1: نشت exception به کاربر نهایی بسته شد.**
- `gateway.py` (execute_tool): بهجای `return {"error": str(exc)}` →
  `"operation failed, check server logs for details"`؛ متن واقعی همچنان فقط در
  `_audit(..., error_message=str(exc))` ثبت میشود.
- `gateway.py` (`_run_chat`): خطای generation →
  `"generation failed, check server logs for details"` (استثنا فقط در audit).
- `telegram.py` (media/voice): پیام خطای خام `f"... {exc}"` →
  پیام فارسی generic «خطایی در دریافت یا تحلیل فایل/صدا رخ داد؛ لطفاً بعداً دوباره تلاش کنید.»
  و `_logger.exception` برای جزئیات واقعی حفظ شد.

## مورد ۵ تمام شد
**P1: README.md هماهنگ شد.**
- عنوان «Current release: v38» → «v57» با ارجاع به `RELEASE_CANDIDATE_VERSION.txt`
  و `FINAL_RELEASE_STATUS.md`.
- دستور `cp` از ۶ ماژول → هر **۱۶ ماژول** `custom_addons/`.
- جملهٔ «installer چاپ میکند API key را» → «M2M secrets هيچوقت چاپ نمیشوند؛
  کلید از طریق session-flow منطور `/api/login`».

## مورد ۶ تمام شد
**P2: وابستگی `mrp` در `ai_business_tools` مستند و هماهنگ شد.**
بررسی نشان داد وابستگی hard واقعی است (نقشهای تمپلیت، گروه
`mrp.group_mrp_manager` را ضمنی اضافه میکنند — `role_templates_data.xml`).
بنابراین optional نکردم (شکستنِ گروه، باگ جدید میساخت)؛ بهجایش:
- `mrp` به لیست `-i` در `02_install_modules.sh` اضافه شد.
- پیشنیازِ mrp در `README.md` و `INSTALL_READY.md` صریح نوشته شد.

## مورد ۷ تمام شد
**P2: سقف حجم دانلود فایل تلگرام اضافه شد.**
در `telegram.py`: ثابت `_MAX_FILE_BYTES = int(AI_TELEGRAM_MAX_FILE_MB, پیشفرض ۲۵MB) * 1024 * 1024`
و در `_download_telegram_file` بعد از دریافت، اگر `len(resp.content) > _MAX_FILE_BYTES`
باشَد `RuntimeError` مناسب میزند (به پیام generic فارسی میرسد).

---

---

## فاز ۱ — merge دو دسته اصلاح (تکمیل شد)

چک‌لیست حضور/عدم حضور روی درخت واحد، و نتیجه:

| مورد | وضعیت قبل | اقدام |
|---|---|---|
| `ODOO_COMMIT_SHA`/`ODOO_LLM_COMMIT_SHA` در `01_setup_base.sh` | **غایب** (clone بدون pin: `git clone --depth 1 --branch 18.0`) | `: "${ODOO_COMMIT_SHA:?...}"` و `: "${ODOO_LLM_COMMIT_SHA:?...}"` + `git checkout FETCH_HEAD` بعد از clone اضافه شد |
| هر سه vLLM instance | `--host 0.0.0.0` (۳ نمونه) | هر سه → `--host 127.0.0.1` (پورت‌های 8000/8001/8002) |
| `odoo.conf` (= هرر`/opt/odoo.conf` که در step 8/9 ساخته می‌شود) | بدون `proxy_mode`/`http_interface` | `http_interface = 127.0.0.1` + `proxy_mode = True` با کامنت توضیحی اضافه شد (با `06_setup_tls.sh:75` و کامنت `_client_ip` هماهنگ شد) |
| `requirements.lock` | ۸ پکیج | بازنویسی کامل: **۱۹ pin** شامل هر ۱۰ پکیجِ step [7/9] (python-docx, unstructured, sentence-transformers, ddgs, requests, numpy, jdatetime, rapidocr-onnxruntime, PyMuPDF, mcp>=1.0,<2.0) + ۹ پکیج core (cryptography, openpyxl, psycopg2-binary, redis, Authlib, python3-saml, faster-whisper, requests, numpy) |
| `25_static_audit.py` | بدون `AUDIT_SCRIPTS`؛ استثنای hardcoded تک‌فایلی | `AUDIT_SCRIPTS = {"25_static_audit.py", "FINAL_EXHAUSTIVE_SOURCE_AUDIT.py"}` (منبع‌واقعی token که grep تأیید کرد) + helper `_sh_path` برای اجرای `bash -n` از چک‌اوت ویندوزی (WSL `/mnt/...`) |
| `FINAL_SOURCE_AUDIT.py` | shell-check با مسیر ویندوزی خراب می‌شد | همان `_sh_path` اضافه شد |

موارد دستهٔ OpenCode (پیش از این در همین درخت اعمال شده بود): `_client_ip` ✅ · `_run_chat` + تلگرام مستقیم ✅ · route تکراری rفع ✅ · exception leak بسته ✅ · README v57/۱۶ ماژول ✅

**نتیجهٔ اجرای ۳ گیت روی درخت merge شده (خروجی کامل در بالا):**
- `25_static_audit.py` → **STATIC AUDIT PASS** (۴/۴؛ قبلاً FAIL)
- `FINAL_SOURCE_AUDIT.py` → **`source_audit_pass: true`, errors: []** (قبلاً به‌خاطر SHELL روی ویندوز fail بود)
- `FINAL_PRODUCTION_GATE.py` → **21/21 PASS**

---

## فاز ۲ — پوشش‌سنجی قابلیت‌ها (تکمیل شد)

وضعیت هر ردیفِ جدول «خواسته ↔ زیرساخت Odoo موجود» در `FEATURE_COVERAGE.md`
ثبت شد (پیاده‌شده/ناقص/غایب + شواهد). خلاصه: ۱۴ ردیف موجود/نیاز‌به-ساخت‌ندار،
۴ ردیف ناقص، ۳ ردیف غایب، ۲ ردیف فقط‌طراحی. `ChatPage.jsx` dead-code تأیید شد
(گپ زنده `ChatWorkspace` نسخهٔ inline در `App.jsx` بود و استفاده می‌شد).

## گامهای نهایی (دور پیش — تکمیل شد)
1. بازتولید کامل `SHA256MANIFEST.json` ✅ → **۳۷۹ ورودی، ۰ گمشده، ۰ ناهماهنگ**
   (شامل ورودی جدید `REVIEW_PROGRESS.md`؛ بازتولید با همان ساختار/ترتیب موجود).
2. اجرای `25_static_audit.py` و `FINAL_PRODUCTION_GATE.py` ✅ (خروجی خام پایین)
3. خلاصهٔ نهایی ✅ (بخش «خلاصهٔ نهایی» پایین)

## خروجی خامِ اجرای گیتها (بعد از تغییرات)

### `python 25_static_audit.py`
```
PASS - generic assistant assignment removed
FAIL - generic ORM tool refs removed
PASS - query-string API key removed
PASS - control plane present

FAILURES:
SHELL D:\Odoo\00_final_production_install.sh: /bin/bash: D:Odoo00_final_production_install.sh: No such file or directory
... (۲۷ شکست SHELL روی ۲۷ فایل .sh؛ همگی همین الگو)
CHECK failed: generic ORM tool refs removed
```
خطاهای این اسکریپت **هر دو از قبل موجودند و به تغییرات این دور ربطی ندارند**:
- شکست `SHELL`: مسیر ویندوزی `D:\Odoo\...` داخل `bash -n` به `D:Odoo...` میرسد (مشکل محیط ویندوز، نه کد).
- شکست `generic ORM tool refs removed`: tokenِ `llm_tool_odoo_record_` در
  `FINAL_EXHAUSTIVE_SOURCE_AUDIT.py:37` است و ۲۵ فقط خودش را استثنا میگیرد
  (self-reference شناختهشده بین خودِ اسکریپتهای audit؛ کد تولیدی سالم است).

### `python FINAL_PRODUCTION_GATE.py`
```
PASS  no blanket assistant tool assignment
PASS  generic rpc permanently disabled
PASS  production CORS fail closed
PASS  telegram code atomic consume
PASS  temporary grants do not mutate group membership
PASS  Excel has no secret output
PASS  unknown Excel role blocks import
PASS  vision is registry routed
PASS  frontend admin is capability driven
PASS  model router benchmark gated
PASS  self contained deployment exists
PASS  workflow cron is recovery only
PASS  event bus triggers workflow processing
PASS  core subscriber matrix exists
PASS  enterprise audit context/hash fields
PASS  customer designer plane exists
PASS  memory retention/deletion controls
PASS  FGA project/folder dimensions
PASS  forbidden pattern grant\.group_id\.write\(\{[\'\"]users
PASS  forbidden pattern localStorage\.setItem\([^\n]*api
PASS  forbidden pattern "model"\s*:\s*"vision-model"

21/21 static gates passed
```

## خلاصهٔ نهایی

**چند مورد واقعاً عوض شد: ۷ مورد (همه)**
۱) `_client_ip` تعریف شد (P0) · ۲) `_run_chat` استخراج + تلگرام مستقیم و بدون API key (P0) ·
۳) روتر تکراری رفع شد (P1، به `/api/control-plane/integrations`) ·
۴) نشت exception بسته شد (P1) · ۵) README هماهنگ شد (P1) ·
۶) mrp مستند + در `-i` (P2) · ۷) سقف حجم فایل تلگرام (P2).

**چند مورد از قبل حل شده بود: صفر.** مورد ۳ را قبل از اقدام چک کردم —
تداخل واقعاً هنوز وجود داشت و رفع شد (نه «قبلاً حلشده»).

**پس از این دور:**
- `FINAL_PRODUCTION_GATE`: **21/21 PASS**.
- `SHA256MANIFEST.json`: **379/379 تناظر، 0 mismatch** (بازتولید کامل + راستیآزمایی محاسباتی).
- همهٔ فایلهای پایتون تغییرکرده با `ast.parse` سالماند؛ مسیرِ `/api/integrations` فقط یک تعریف دارد.

**هنوز verify نشده / مشکوک:**
- **runtime certification**: Odoo/Postgres/Redis/vLLM/pgvector/Telegram/Buzz —
  در این محیط قابل تست نیست؛ همان «RUNTIME_CERTIFICATION_REQUIRED» که داکها هم صادقانه میگویند.
  رفتار واقعی `_client_ip` (با proxy) و `_run_chat` (با کاربر واقعی) در همان runtime باید سنجیده شود.
- **25_static_audit و 44** همچنان FAIL میدهند؛ هر دو شکستِ از پیشموجودِ audit (self-reference و چکِ staleِ
  `cron_process`→`process`) هستند و این دور در دستور کار نبودند.
- **README** سطرهای ۱۲–۱۴/۷۹/۹۶ («exactly 3 endpoints»، «prints the exact 3 commands»)
  هنوز قدیمی است — عمداً و طبق scope این دور دستنخورده.
- **49/53/56/58/27/48** نیاز به root نسخهٔ قبلی/Odoo shell/آرگومان دارند — در این محیط قابل اجرا نبودند.

---

## فاز ۳ — پیاده‌سازی موارد ناقص/غایب (تکمیل شد)

### مورد ۳–الف تمام شد — ریسک-رول‌های گمشدهٔ آپریشن‌های یکپارچه
از ۱۶ آپریشن `ai.integration.operation`، ۸ مورد `ai.gateway.tool.risk` نداشتند و
`execution_contract()` (unified_registry.py:262-265) آن‌ها را ممنوع می‌کرد:
`crm.lead.create`, `hr.attendance.check_in`, `hr.expense.create`,
`mrp.production.create`, `calendar.event.create`, `documents.document.create`,
`helpdesk.ticket.create`, `pos.order.create`.
→ به `unified_registry_data.xml` با `noupdate="1"` اضافه شدند با
risk_level/‌capability_name دقیقاً برابر رکورد op، و `approver_group_id`
برای `mrp.production.create` = `role_manufacturing_manager`. اکنون هر ۱۶ آپریشن
قرارداد کامل Capability→Tool→Risk دارند. (برای دیتابیس‌های نصب‌شدهٔ قبل: سینک
`ai.control.tool.binding.sync_from_risk_registry`/`/api/control-plane/integrations/sync`
کاربردی خواهد بود، چون noupdate=1 رکورد جدید را در دیتابیس موجود بارگذاری نمی‌کند.)

### مورد ۳–ج تمام شد — نشت جزئیات در experience_api
`/api/files/analyze` و `/api/artifacts/generate` مقدار `str(exc)` را به کلاینت
برمی‌گرداندند → هر دو generic شدند (جزئیات فقط در `_logger.exception`/audit).
تأیید با `ast.parse`.

### مورد ۳–پ تمام شد — گزارش مصرف توکن
- `token_count` (Integer, indexed) به `ai.gateway.audit.log` اضافه شد؛ در `log()`
  ذخیره و در hash-chain audit گنجانده شد.
- `_run_chat` یک تخمینِ **صادقانه** ثبت می‌کند (`_estimate_tokens`: chars/4) — چون
  odoo-llm از `thread.generate()` هیچ usage واقعی برنمی‌گرداند؛ لیبل «estimate»
  صریح در خروجی گزارش.
- `tokens_24h` به `observability_snapshot()` اضافه شد و متد جدید
  `token_usage_report(days=30)` (گروه‌بندی day/user/company) + اندپوینت اختصاصی و
  privileged به نام `/api/reports/tokens` در gateway.py.

### مورد ۳–ت تمام شد — چت وب زنده: streaming + thinking + فایل/صدا + رفع dead-code
- **Dead code حذف شد**: `ChatWorkspace` (نسخهٔ inline غول‌پیکر در App.jsx) حذف و
  `ChatPage.jsx` زنده شد (`<Route path="/chat" element={<ChatPage/>}>`).
- **اندپوینت SSE**: `/api/chat/stream` (POST) — رویدادهای `thinking` →
  چند `delta` → `done`/`error`؛ احراز/rate-limit همانند `/api/chat`؛ هدرهای
  `X-Accel-Buffering: no` برای کنار زدن بافرینگ پراکسی.
- **محدودهٔ صادقانه**: `thread.generate()` بلوک است و streaming اسمی ندارد؛
  «streaming» یعنی تحویل تدریجیِ پاسخِ نهایی (چیک‌های word‌ای) + رویداد thinking،
  نه جعل token‌های وسط زنجیره. streaming واقعیِ سطح-provider به runtime و
  جایگزینی `thread.generate()` نیاز دارد.
- `streamChat()` در client.js (خوانندهٔ SSE با fetch + ReadableStream)؛
  خواندن پاسخ به‌صورت تدریجی، حباب «در حال پردازش...»، پیوست فایل
  (از طریق `/api/files/analyze`)، و Voice (SpeechRecognition مرورگر).
- build فرانت (`npm run build`) موفق: **۵۵ ماجول، dist ساخته شد**.

### مورد ۳–چ تمام شد — طرح discovery خودکار (طراحی + یک قدم پیاده)
گزینه‌ها:
1. **cron دوره‌ای** برای اسکن `ir.module.module` + ثبت op/capability جدید — رد شد:
   مناسب مقیاس فعلی نیست؛ ثبت‌نام deriative قبلاً دستی/گامه‌گام است؛ و «بدون
   chron جدید تا اندازهٔ نیاز» با فلسفهٔ پروژه هم‌خوان است.
2. **post_init در هر ماژول**: هر ماژول جدید که adapter دارد، در `post_init` رکورد
   op/capability/risk خودش را اضافه کند. ✓ انتخاب شد — منبع حقیقت همان ماژول است
   نه اسکن مرکزی؛ سازگار با مدل پایگاهِ `noupdate="1"`.
3. **manual sync**: `ai.control.tool.binding.sync_from_risk_registry()`
   (موجود) + `/api/control-plane/integrations/sync` (موجود) — برای دیتابیس‌های
   موجود کافی است.
نتیجه: پیاده‌سازیِ داده‌محورِ فعلی + post_init برای ماژول‌های آینده؛ اسکن خودکار
مرکزی (گزینهٔ ۱) در صورت بروز خطای ثبت‌نام تازه معرفی می‌شود، نه قبل‌تر.

### مورد ۳–ح تمام شد — طرح صف هم‌زمانی /api/chat + vLLM
وضعیت فعلی: `_run_chat` یک‌جا و synchronous-blocking است؛ `llm.thread.generate()`
در همان worker ژیکورن اجرا می‌شود. گزینه‌ها:
1. **Redis + queue پایتون** (redis==5.0.8 در requirements برای همین) — صف بلند
   برای درخواست‌های سنگین، پاسخ async. رد شد برای نسخهٔ اول نصب: odoo-llm
   generate همان thread را درWorker دیگری اجرا نمی‌کند بدون بازنویسی عمیق.
2. **محدودیت هم‌زمانی موجود** (rate-limit + `duration_ms`/metrics): + یکی صف
   سبک درون‌فرایندی (deque + worker-thread) — ✓ انتخاب برای گام بعدی بنش.
3. **دو نمونهٔ vLLM** (8000/8001 در راه‌انداز) مدل‌های متنی و vision را جدا
   کرده‌اند؛ هر نمونه به‌صورت بومی خودش batch می‌کند.
تصمیم: برای v57 این طراحی ثبت می‌شود و اجرای واقعی صف (گزینهٔ Balanced #2) فقط
پس از RUNTIME_CERTIFICATION اندازه‌گیری می‌شود — صف بدون عددِ QPS واقعی در این
محیط بهینه‌سازیِ حدسی است و اضافه می‌شود.

---

## فاز ۴ — بازتولید مانیفست + گیت‌های نهایی (تکمیل شد)

بعد از تمام تغییرات فاز ۳، روی درخت واحد:
- `25_static_audit.py` → **STATIC AUDIT PASS** (۴/۴)
- `FINAL_SOURCE_AUDIT.py` → **`source_audit_pass: true`, errors: []**
- `FINAL_PRODUCTION_GATE.py` → **21/21 PASS**
- `SHA256MANIFEST.json` → بازتولید کامل (جزئیات زیر).

## خلاصهٔ نهایی (فاز ۲/۳)

**واقعاً عوض شد (پیاده‌سازی):**
۱) ۸ ریسک-رول برای آپریشن‌های یکپارچه (از جمله calendar.event.create) ·
۲) generic شدن error در `/api/files/analyze` و artifact.generate ·
۳) `token_count` + گزارش + `/api/reports/tokens` ·
۴) چت زنده: SSE streaming + thinking + فایل/صدا + حذف dead-code ChatWorkspace ·
۵) طراحی discovery و صف (اختیار نوشته‌شده و انتخاب منطقی).
**از قبل حل‌شده/نیازی به ساخت نبود:** ۱۴ ردیف جدول پوشش + web_search/ddgs + قوانین
سختِ گفتار (قانون ۱۳ system prompt از قبل فعال بود).

**RV/verify نشده (مثل قبل):** RUNTIME_CERTIFICATION_REQUIRED — streaming واقعی
سطح-provider، QPS صف، رفتار `_client_ip` با proxy، و مقداردهی token واقعی همه
نیاز به Odoo زنده دارند و در این محیط تست نمی‌شوند.