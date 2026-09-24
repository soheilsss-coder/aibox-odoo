# برنامهٔ ارتقای جامع و لاگ اجرای مرحله‌ای

**تاریخ آغاز:** ۲۰۲۶-۰۸-۳۱
**شاخهٔ ثابت:** `arena/01a054c0-aibox-odoo`
**سیاست workspace:** از مدل‌های حجیم، dataset، نصب package داخل مخزن و build artifact غیرضروری استفاده نشود؛ حجم فعلی repository حدود ۲٫۷ MB است.

## ۰. تصمیم‌های اجرایی

- اجرای ارتقا بدون توقف و بدون نیاز به تأیید مرحله‌ای انجام می‌شود.
- هیچ ادعای «بدون باگ مطلق» یا «۱۰۰۰ کاربر همزمان قطعی» بدون اجرای stack واقعی، benchmark و failure test ثبت نمی‌شود.
- Docker استفاده نمی‌شود؛ target نهایی bare-metal/native روی DGX GB10 است.
- منبع حقیقت برای mutation فقط مسیر مرکزی است: `identity → company/department scope → capability → native ACL/record rule/FGA → risk → approval → execution gate → handler → audit/event/outbox`.
- نام فنی backend/مدل/ماژول نباید در تجربهٔ کاربر نهایی یا پاسخ AI نمایش داده شود؛ APIهای داخلی برای frontend نیز باید label امن و capability-based داشته باشند.
- فایل و RAG همیشه باید authorization را قبل از load، parse، chunk، embed، vector search، context assembly، preview، download و export اعمال کنند.
- همهٔ moduleهای نصب‌شده باید به‌صورت dynamic discover و certify شوند؛ hard-code محدود readiness قابل قبول نیست.

## ۱. نتایج research و benchmark معماری

### ۱٫۱ دامنهٔ واقعی ERP که باید discover شود

بر اساس مستندات رسمی نسخهٔ ۱۸، دامنه‌ها فقط Restaurant نیستند و باید registry برای این خانواده‌ها وجود داشته باشد:

1. Finance: accounting، invoicing، expenses، payments، budgets، analytic accounting، tax/EDI.
2. Sales: CRM، leads/opportunities، quotations، orders، pricing، subscriptions، rental.
3. POS/Commerce: Point of Sale، retail، restaurant، bars، floors/tables، kitchen/bar routing، split bills، tips، delivery، self-ordering، loyalty و payment.
4. Supply Chain: inventory، warehouses، replenishment، barcode، shipping، purchase، vendor bills، lots/serials.
5. Manufacturing: MRP، BoM، work centers، work orders، quality، maintenance، PLM/ECO، subcontracting.
6. People: employees، departments، attendances، time off، recruitment، onboarding، appraisals، planning، payroll، fleet، frontdesk، lunch.
7. Work/Service: project، tasks، timesheets، planning، field service، helpdesk، SLA، repairs.
8. Productivity/Knowledge: documents، sign، spreadsheet، knowledge، calendar، appointments، discuss، email، VoIP.
9. Growth: marketing، events، surveys، website، eCommerce و live chat.
10. Integrations/IoT: payment providers، barcode، printers، IoT و external channels.

**اصل طراحی:** وجود یک ERP module به‌تنهایی مجوز استفادهٔ AI نیست. برای هر module باید `discovery + capability + policy + risk + handler/adapter + event + audit + certification` ثبت شود. اگر handler reviewed وجود ندارد، mutation باید deny-by-default بماند و صرفاً module را «قابل استفاده» اعلام نکند.

منابع رسمی research:

- [ERP 18 application index](https://www.odoo.com/documentation/18.0/applications.html)
- [ERP 18 Point of Sale](https://www.odoo.com/documentation/18.0/applications/sales/point_of_sale.html)
- [ERP 18 Restaurant features](https://www.odoo.com/documentation/18.0/applications/sales/point_of_sale/restaurant.html)
- [ERP 18 Apps and modules](https://www.odoo.com/documentation/18.0/applications/general/apps_modules.html)

### ۱٫۲ الگوهای محصول مشابه که باید جذب شوند

- الگوی **Topics/Actions/Guardrails** در Agentforce: دامنهٔ agent باید explicit باشد، actionها فهرست‌شده و قابل audit باشند و action authorization قبل از اجرا انجام شود.
- الگوی **Governed lifecycle** در Copilot Studio: inventory، readiness، approval publish، DLP/connector policy، محیط dev/test/prod، audit و capacity monitoring باید جزو محصول باشند.
- الگوی **AI Control Tower/Guardian** در ServiceNow: auto-discovery، guardrail ورودی/خروجی، escalation انسانی، usage/performance dashboard و evidence قابل پیگیری لازم است.
- الگوی **vLLM production serving**: continuous batching، structured outputs، tool calling، real streaming، prefix caching، metrics، readiness/liveness، TTFT/TPOT و queue observability باید اندازه‌گیری شوند.
- الگوی **SCIM استاندارد**: `startIndex`/`count`، filter، `PATCH` عملیاتی، `PUT` جایگزینی، conflict/uniqueness، error type و ETag/version باید پشتیبانی شوند.
- الگوی **OWASP ASVS 5 / File Upload**: allow-list extension و MIME، magic bytes، اندازهٔ compressed/uncompressed، storage خارج از webroot، malware quarantine، filename داخلی، authorization سروری، XSS/CSP و SSRF protection.

منابع اصلی:

- [SCIM RFC 7644](https://datatracker.ietf.org/doc/html/rfc7644)
- [SCIM cursor pagination RFC 9865](https://www.rfc-editor.org/info/rfc9865)
- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [vLLM official documentation](https://docs.vllm.ai/)
- [Microsoft agent resources](https://microsoft.github.io/agent-resources/copilot-studio/)
- [Salesforce AI guardrails](https://www.salesforce.com/welcome-to-the-agentic-enterprise/ai-guardrails/)
- [ServiceNow AI Control Tower](https://www.servicenow.com/products/ai-control-tower.html)

## ۲. ترتیب اجرای پروژه

### فاز A — سلامت سورس و installability

**هدف:** نصب و upgrade قابل تکرار، حذف false-positive و ایجاد contractهای canonical.

کارها:

- حذف duplicate capability data و نگه‌داشتن یک source of truth.
- اصلاح import و signatureهای قطعی.
- اصلاح readiness و dynamic module inventory.
- ایجاد testهای pure-Python برای XML/data contracts، duplicate identifier، missing handler و manifest.
- اصلاح/تکمیل deployment scripts native بدون اضافه کردن Docker.

**Gate:** static checks، XML parse، AST، duplicate scan، manifest check و dry-run installer بدون blocker.

### فاز B — authorization/tenant/customer plane

**هدف:** هر تصمیم دسترسی یکسان و قابل بازبینی باشد.

کارها:

- canonical delegation API و re-check هنگام replay.
- ACL alignment برای Executive/roleهای محصول.
- compile/version/rollback configuration profile.
- SSO provider binding به company، audience، issuer، claims و group-to-role.
- SCIM استاندارد، conflict-safe و tenant-safe.
- dynamic readiness بر مبنای moduleهای واقعی نصب‌شده.

**Gate:** ماتریس cross-company، department، team، user، grant، delegation، expiry، revoke و replay.

### فاز C — registry و پوشش همهٔ moduleها

**هدف:** هیچ module نصب‌شده‌ای از مسیر مرکزی خارج نباشد.

کارها:

- registry dynamic از `ir.module.module` و metadata reviewed.
- capability/action taxonomy عمومی برای read/create/update/delete/approve/execute.
- handler certification برای هر operation.
- event/audit mapping برای create/update/approve/delete.
- عملیات domainهای فعلی و moduleهای رسمی موجود.
- adapter واقعی برای POS/Restaurant، شامل floor/table/order/kitchen/printer/bill/payment/booking/tip/stock/account events.

**Gate:** module بدون reviewed adapter/capability صرفاً `discovered/unavailable` باشد، نه `ready`.

### فاز D — فایل، RAG، memory و output safety

**هدف:** جلوگیری از نشت داده و prompt injection در کل چرخه.

کارها:

- common authorization service برای attachment/document/chunk/embedding/context/export.
- file allow-list، size quota، magic-byte validation، safe filename، quarantine/scan hook.
- context firewall برای PII، secret، technical identifiers و prompt injection.
- citation/grounding metadata بدون افشای path/ID داخلی.
- deletion/re-index/revocation propagation.
- frontend HTML sanitization و CSP.

**Gate:** denied-user cannot observe data در هیچ مسیر sync/async/vector/cache/notification/export.

### فاز E — تجربهٔ محصول و white-label

**هدف:** محصولی قابل فروش و consistent، نه مجموعهٔ endpoint.

کارها:

- capability-aware navigation/action rendering.
- chat history، search، citations، attachments، voice، approval cards، action result، retry و offline/error states.
- اتصال واقعی صفحات calendar، departments، knowledge، approvals، agents و tasks.
- وضعیت AI بر اساس health واقعی، نه hard-coded.
- label registry برای حذف نام‌های فنی در bootstrap/API/error/AI/Telegram/Buzz.
- accessibility، RTL، responsive design، keyboard navigation، skeleton/loading، empty/error states.

**Gate:** UI smoke/e2e و snapshot white-label روی roleهای مختلف.

### فاز F — capacity و native DGX certification

**هدف:** تعیین ظرفیت واقعی و production gate.

کارها:

- systemd units و native services برای database، cache، gateway، vLLM، event worker و RAG worker.
- load profile برای ۱۰۰، ۲۵۰، ۵۰۰ و ۱۰۰۰ کاربر concurrent.
- p50/p95/p99 برای chat، tool، RAG، upload، approval و SCIM.
- failure injection: Redis/database/model/worker restart، queue overflow، dead letter، network timeout و duplicate replay.
- Prometheus/OpenTelemetry metrics، alerting، backup/restore و disaster recovery.

**Gate:** نتیجهٔ ۱۰۰۰ concurrent فقط با evidence واقعی صادر می‌شود؛ static code یا selftest جای benchmark را نمی‌گیرد.

## ۳. لاگ اجرای مرحله‌ای

### مرحلهٔ A-1 — انجام شد

- research رسمی ERP domainها و Restaurant انجام شد.
- research استاندارد SCIM، OWASP file security، agent governance و vLLM production انجام شد.
- این plan و research log در همین فایل ذخیره شد.
- حجم workspace بررسی شد: حدود ۲٫۷ MB؛ سقف ۱۲۸ MB با حاشیهٔ زیاد رعایت می‌شود.

### مرحلهٔ A-2 — انجام شد

- duplicate capability data از `ai_integration/data/capability_data.xml`، `ai_integration/data/unified_registry_data.xml` و `ai_experience/data/capability_data.xml` حذف شد؛ source of truth در control plane باقی ماند.
- readiness به `ai.control.module` اصلاح شد و inventory dynamic از installed moduleها و operation moduleها اضافه شد.
- delegation به signature canonical (`capability`, `user`, `record`, `action`) متصل شد و target record قبل از authorization resolve می‌شود.
- import `ValidationError` در SCIM اصلاح شد.
- SCIM ServiceProviderConfig، pagination، filter محدود و استاندارد، PUT، PATCH، conflict handling، group membership replacement و group DELETE اضافه شد.
- SSO provider ambiguity/tenant binding، audience و explicit claim-group-to-product-role synchronization اضافه شد؛ assignmentهای SSO از assignmentهای admin/SCIM جدا هستند.
- test سبک `tests/test_upgrade_contracts.py` اضافه شد.
- نتیجه: **۷/۷ pure-Python contract tests PASS**؛ این نتیجه جایگزین runtime test نیست.

### مرحلهٔ A-3 — انجام شد

- readiness اکنون operationهای active را با `ir.module.module(state=installed)` تقاطع می‌دهد؛ operationهای optional برای domainهای نصب‌نشده فقط در `uninstalled_operation_modules` گزارش می‌شوند و tenant را unready نمی‌کنند.
- policy مشترک upload در `ai_gateway/controllers/file_policy.py` اضافه شد: allow-list، سقف پیش‌فرض ۲۵MB، UTF-8/text validation، magic bytes برای PDF/image/legacy XLS، ZIP path/symlink/unpacked-size checks برای Office، و نام فایل داخلی امن.
- `/api/files/analyze`، `/api/documents` و job هوش فایل از همان policy استفاده می‌کنند؛ PDF حداکثر ۱۰۰ صفحه و خروجی/پرسش customer-facing scrub می‌شود. دانلود document نیز Base64 ORM را درست decode می‌کند و MIME/content را دوباره اعتبارسنجی می‌کند.
- notification HTML دیگر با `dangerouslySetInnerHTML` رندر نمی‌شود؛ محتوای اعلان به متن امن تبدیل می‌شود.
- APIهای customer/admin دیگر provider، model identifier یا vision endpoint را برنمی‌گردانند؛ فقط capability/health را expose می‌کنند.
- Vite و React Router به نسخه‌های دارای audit پاک ارتقا یافتند؛ `npm audit` اکنون **۰ آسیب‌پذیری** و `npm run build` موفق است. preview با bind روی `0.0.0.0` و allowlist مناسب تنظیم شد.
- پس از hardening فایل، output firewall، SSO و SCIM، suite قرارداد به **۱۳/۱۳ PASS** رسید؛ `compileall`، `bash -n` و `git diff --check` نیز موفق بودند.

### نتایج و محدودیت‌های ثبت‌شده

- **PASS واقعی محیطِ verification نهایی:** ۱۳ تست pure-Python، compile سورس Python، parse/contractهای XML موجود، frontend production build، `npm audit` با **۰ آسیب‌پذیری**، static audit، ۹۴/۹۴ production-source gate و ۲۱/۲۱ exhaustive source gates.
- auditهای 25/28/59 و `30_build_release.sh` با entrypointهای native فعلی یکپارچه شدند؛ installerهای `00` تا `03` اکنون واقعاً در checkout هستند و syntax/source gate دارند، ولی اجرای آن‌ها همچنان به host واقعی و dependencyهای native نیاز دارد.
- **RUNTIME_REQUIRED:** Odoo binary و PostgreSQL/Redis/vLLM در checkout یا محیط فعلی موجود نیستند؛ بنابراین install/upgrade واقعی، ORM/XML registry، ACL/record-rule، SSO/SCIM wire test، RAG leakage، queue failure test و DGX benchmark هنوز قابل صدور نیستند.
- **ظرفیت ۱۰۰۰ کاربر:** هنوز ادعایی صادر نشده است؛ فقط بعد از اجرای native load/failure benchmark روی DGX GB10 مجاز خواهد بود.

### Verification نهایی فاز A — انجام شد

آخرین اجرای کامل `bash 30_build_release.sh` موفق شد: suite قرارداد **۱۳/۱۳ PASS**، `compileall` و `bash -n` موفق، `git diff --check` موفق، static audit و release audit موفق، structural E2E موفق، hardening audit موفق، production-source gate **۲۱/۲۱ PASS**، exhaustive source audit **۹۴/۹۴ PASS**، Vite production build موفق و `npm audit` با **۰ آسیب‌پذیری**. `SHA256MANIFEST.json` نیز پس از تغییرات نهایی بازتولید و با ۳۹۲/۳۹۲ ورودی بدون mismatch بررسی شد.

در hardening نهایی، مصرف واقعی `PGVECTOR_PACKAGE` در apt install، health gate برای Redis native، مسیر واقعی `odoo-bin` در installer/systemd، rate limit مشترک برای OIDC callback و SAML ACS، fail-closed شدن خطای Redis limiter، الزام public HTTPS base در production، validation امن URLهای SSO، parsing/role allow-list/atomic validation در SCIM و تست output firewall ثبت و بررسی شدند.

### معیار توقف واقعی

این پروژه از نظر کدنویسی و تست‌های قابل اجرای محیط ادامه پیدا می‌کند؛ فقط مواردی که به سرویس‌های خارج از checkout نیاز دارند، با status دقیق `RUNTIME_REQUIRED` ثبت می‌شوند. صدور گواهی «بدون مشکل» یا «۱۰۰۰ کاربر» پیش از اجرای آن تست‌ها مجاز نیست.
