# نقشهٔ راه ارتقای واقعی محصول — v58

**تاریخ:** ۲۰۲۶-۰۸-۳۱
**شاخه:** `arena/01a054c0-aibox-odoo`
**هدف:** تبدیل hardening قبلی به یک برنامهٔ محصولی/عملیاتی برای سرعت، workflow، پوشش ERP، RAG، UX و ظرفیت؛ بدون ادعای runtime certification پیش از اجرای stack واقعی.

## ۱. تشخیص فعلی بر اساس source

### مسیر فعلی درخواست

```text
Browser / Telegram / Discuss
  -> semantic API یا AI Gateway
  -> Odoo ORM + Authorization/Risk/Approval
  -> llm.thread.generate()
  -> local OpenAI-compatible endpoint
  -> audit/output firewall
```

یافته‌های مهم source:

| حوزه | وضعیت فعلی | اثر عملی |
|---|---|---|
| Chat | `thread.generate()` بلاک‌کننده است؛ SSE فقط پاسخ نهایی را word-chunk می‌کند | token streaming واقعی و cancellation وجود ندارد؛ یک turn طولانی connection را نگه می‌دارد |
| Queue | pool محدودکننده در هر process است | چند worker پشت یک GPU می‌توانند over-commit کنند؛ صف durable و cross-process نداریم |
| Routing | model registry عمدتاً برای embedding/vision استفاده می‌شود و chat assistant به مدل ثابت وصل است | latency budget، fallback، canary و routing بر اساس workload عملاً استفاده نمی‌شوند |
| vLLM | در source چند endpoint محلی ثبت شده، اما unit/wrapper کامل برای serving، prefix cache، chunked prefill و health gate وجود ندارد | tuning سرعت و lifecycle سرویس قابل بازتولید نیست |
| Workflow | DSL، retry و approval دارد، ولی workflow ددلاین task وضعیت task را دوباره نمی‌خواند | reminder ممکن است برای task تکمیل‌شده هم صادر شود |
| RAG | pre-filter ACL و pgvector وجود دارد و indexing job وجود دارد | hybrid search، snapshot/rollback، freshness و metrics کامل نیست |
| ERP coverage | registry/adapter data برای domainهای متعدد هست | باید هر module نصب‌شده با model/handler/ACL/event/certification واقعی کشف و گزارش شود |
| Frontend | صفحات متعددی به API وصل‌اند، ولی Calendar و برخی صفحات هنوز demo/static یا با خطای خاموش هستند | تجربه محصولی و observability واقعی ناقص است |
| Usage metrics | token count در audit تخمینی است | هزینه/ظرفیت دقیق تا زمان provider usage واقعی قابل اندازه‌گیری نیست |

## ۲. اصول طراحی که باید حفظ شوند

1. **سرعت بدون دورزدن امنیت:** هیچ cache، batch، retry یا fallback نباید tenant/user/policy scope را حذف کند.
2. **vLLM فقط native:** systemd + process wrapper؛ Docker/compose ممنوع.
3. **مسیر کوتاه برای chat:** مدل کوچک‌تر/سریع‌تر برای intent و پاسخ ساده، مدل reasoning فقط با classifier/risk مناسب؛ tool call همیشه از execution gate عبور می‌کند.
4. **هزینهٔ متناسب با کار:** پاسخ‌های ساده نباید وارد مسیر reasoning طولانی، OCR یا RAG کامل شوند.
5. **durability به‌جای cron-only:** Event Bus منبع trigger است؛ cron فقط recovery/deadline maintenance است.
6. **fail closed و قابل مشاهده:** اگر model/Redis/pgvector در دسترس نیست، نتیجهٔ مبهم تولید نشود؛ health، queue، latency و error باید قابل مشاهده باشند.
7. **ادعای ظرفیت فقط با benchmark:** عدد ۱۰۰۰ کاربر تا پیش از benchmark DGX اعلام نمی‌شود.

## ۳. backlog اجرایی و معیار پذیرش

### V58-A — Inference Runtime و سرعت LLM

- [x] ثبت current architecture و bottleneckها.
- [x] افزودن native vLLM wrapper و unitهای chat/embedding/vision با تنظیمات environment-based.
- [x] فعال‌سازی prefix caching، chunked prefill، bounded sequences/tokens و GPU headroom؛ مقدارها configurable و benchmark-gated باشند.
- [x] اتصال chat به model router با purpose/latency budget و fallback فقط به مدل certified.
- [x] افزودن Redis global lease برای جلوگیری از over-commit چند Odoo worker روی یک GPU.
- [ ] افزودن health/circuit-breaker و metricهای TTFT/TPOT/queue wait/timeout/error؛ profile health/circuit source اضافه شده، اما evidence runtime هنوز اجرا نشده است.
- [x] حفظ SSE فعلی به‌عنوان compatibility path و ثبت صریح محدودیت آن؛ token streaming واقعی تا زمان پشتیبانی framework runtime باقی است.

**قبولی:** source tests برای config bounds، fallback، lease release و عدم expose کردن model/provider identifier؛ benchmark واقعی در فاز runtime جداگانه.

### V58-B — Workflow و Agent Loop

- [x] افزودن read-only task status tool و استفاده از آن در deadline workflow.
- [x] ثبت `last_tool_result` و trace/correlation در context workflow.
- [x] validation قوی‌تر DSL: schema نسخه‌دار، محدودیت jump/loop، timeout و idempotency.
- [ ] retry با backoff/jitter، dead-letter، compensation و recovery چند worker را قابل مشاهده‌تر کن.
- [x] approval UX/API برای pending/approve/reject/timeout با re-authorization در زمان تصمیم.
- [x] برای prompt injection در tool result، context firewall و tool allowlist حفظ/تقویت شده است.

**قبولی:** contract tests برای workflow completed-task، duplicate event، retry/dead-letter و approval replay.

### V58-C — RAG و حافظهٔ سازمانی

- [x] indexing فقط از Event Bus و worker durable؛ enqueue idempotent و stale job قابل recovery.
- [x] hybrid retrieval: ACL-filtered lexical candidate + vector ranking، بدون broaden کردن scope.
- [x] chunk/index version برای re-embed safety و citations اضافه شد؛ snapshot/rollback metadata هنوز runtime gate است.
- [ ] freshness/ACL/cache leakage metrics و negative tests.
- [x] citations شامل document/chunk version و نه identifier فنی backend.

**قبولی:** cross-tenant/revocation/cache leakage tests و اندازه‌گیری retrieval latency روی dataset واقعی.

### V58-D — ERP Module Capability Matrix

- [x] inventory نصب‌شده از `ir.module.module` و model registry گرفته شود.
- [x] برای هر module: discovery، capability، risk، handler، native ACL، record rule، event subscriber و certification status؛ گزارش runtime در `62_v58_module_certification.py` fail-closed است.
- [x] adapters واقعی برای Sales/CRM/Purchase/Inventory/MRP/Accounting/POS/Restaurant/HR/Attendance/Expenses/Project/Helpdesk/Documents/Calendar/Marketing/Events/Subscriptions/Rental/Quality/Maintenance اضافه شده‌اند؛ برای ماژول‌های بدون adapter، certification به‌صورت fail-closed block می‌شود.
- [x] optional module نصب‌نشده فقط در inventory به‌عنوان غیرنصب‌شده دیده می‌شود و عملیات بدون handler در registry ثبت/advertise نمی‌شود.

**قبولی:** matrix runtime با evidence رکورد/handler/ACL و تست positive/negative برای هر operation.

### V58-E — Product UX و عملیات روزمره

- [x] حذف static/demo data از Calendar و جایگزینی با endpoint واقعی.
- [x] fetchهای محصولی اصلی loading/error/empty دارند؛ مسیرهای باقی‌ماندهٔ فرعی باید پیش از runtime sign-off با failure injection بازبینی شوند.
- [ ] chat history، cancellation، attachment status و citation به‌صورت واقعی تکمیل شود؛ approval action اکنون API-backed است.
- [ ] capability gating فقط در UI نباشد؛ API و backend همچنان authority نهایی باشند.
- [ ] RTL/accessibility/responsive و white-label regression در build تست شود.

### V58-F — Verification و Capacity

- [x] unit/contract/security tests در build اجباری.
- [ ] runtime install/upgrade روی Odoo/PostgreSQL/Redis/pgvector/vLLM native.
- [x] harness benchmark سناریوهای chat ساده، chat با tool، RAG، file و approval با p50/p95/p99 و TTFT در `60_v58_llm_benchmark.py`؛ TPOT/queue/GPU/DB/Redis باید توسط collector واقعی تکمیل شوند.
- [ ] load/failure test با worker restart، Redis قطع، vLLM restart، dead-letter و recovery.
- [ ] نتیجهٔ ظرفیت با workload و configuration دقیق ثبت شود؛ در غیر این صورت `RUNTIME_REQUIRED` باقی بماند.

## ۴. تصمیم‌های سرعت بر اساس پژوهش

- vLLM در مستندات فعلی continuous batching، PagedAttention، prefix caching، chunked prefill، structured outputs، tool calling، speculative decoding و metrics را به‌عنوان قابلیت‌های serving ارائه می‌کند.
- طبق مستندات tuning، `max_num_batched_tokens` trade-off بین TTFT/prefill throughput و decode latency/activation memory است؛ بنابراین مقدار ثابت و بدون benchmark برای DGX انتخاب نمی‌شود.
- V1 vLLM در صورت امکان chunked prefill را فعال می‌کند؛ تنظیم explicit در wrapper برای reproducibility نگه داشته می‌شود و نسخهٔ vLLM باید با runtime target validate شود.
- cache application باید کلید scope‌شده بر اساس tenant، user، permission fingerprint، model revision و prompt version داشته باشد؛ پاسخ tool یا business data بدون این scope cache نمی‌شود.
- structured output برای automation و tool arguments اجباری است؛ free-form model text مستقیماً executable نیست.

## ۵. منابع تحقیق

1. vLLM current documentation — serving features, continuous batching, prefix caching, structured outputs, tool calling and observability: <https://docs.vllm.ai/>
2. vLLM Optimization and Tuning — preemption, KV cache, chunked prefill and `max_num_batched_tokens`: <https://docs.vllm.ai/en/stable/configuration/optimization/>
3. vLLM production metrics: <https://docs.vllm.ai/en/stable/serving/metrics.html>
4. Odoo 18 Applications/Modules catalog — Finance, Sales, Supply Chain/MRP, HR, Services, Productivity, Marketing and Integrations: <https://www.odoo.com/documentation/18.0/applications.html>
5. Odoo 18 Apps and Modules: <https://www.odoo.com/documentation/18.0/applications/general/apps_modules.html>
6. OWASP RAG Security — retrieval boundaries, query monitoring, output validation, tool authorization, snapshots and leakage tests: <https://cheatsheetseries.owasp.org/cheatsheets/RAG_Security_Cheat_Sheet.html>
7. OWASP LLM01:2025 Prompt Injection — least privilege, indirect injection and tool boundary: <https://genai.owasp.org/llmrisk/llm01-prompt-injection/>
8. OWASP MCP Security — treat tool returns as untrusted, validate tool calls independently, avoid arbitrary chaining: <https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html>

## ۶. مرز صداقت

این roadmap source work را تا جایی که checkout اجازه می‌دهد اجرا می‌کند. اما انتخاب عدد نهایی `max_num_seqs`، `max_num_batched_tokens`، تعداد worker، مدل مناسب و ظرفیت هم‌زمانی فقط با benchmark روی DGX GB10، نسخهٔ واقعی vLLM، مدل‌های واقعی، PostgreSQL/Redis و workload نماینده معتبر است.
