# گزارش جامع ممیزی وضعیت فعلی سامانه

> **الحاقیهٔ وضعیت فعلی — ۲۰۲۶-۰۸-۳۱:** متن اصلی این فایل baseline ممیزی پیش از اجرای این turn بود. وضعیت زیر یافته‌های اصلاح‌شده را supersede می‌کند؛ مواردی که در این الحاقیه نیامده‌اند همچنان نیازمند runtime verification هستند.
>
> - duplicate capability، readiness model، delegation signature، SCIM import/contract، SSO binding پایه، debranding bootstrap، cursor collaboration و Restaurant registry/handler اصلاح شده‌اند.
> - native entrypointهای `00_final_production_install.sh` تا `03_start_all.sh` اکنون در checkout موجودند؛ این‌ها نصب/upgrade واقعی را روی host native اجرا می‌کنند، اما در محیط فعلی اجرا نشده‌اند.
> - upload policy مشترک OWASP-oriented، decode صحیح document download، HTML-safe notification، API debranding و frontend dependency hardening اضافه شده است.
> - evidence فعلی: **۱۳/۱۳ contract tests، ۹۴/۹۴ exhaustive source gates، ۲۱/۲۱ production gates، static/XML/AST/shell و frontend build PASS؛ npm audit: ۰ vulnerability**.
> - verdict فعلی: **SOURCE-HARDENED / RUNTIME-BLOCKED**. Odoo، PostgreSQL، Redis، vLLM، IdP و DGX runtime در این محیط موجود/اجرا نیستند؛ بنابراین production-ready یا ظرفیت ۱۰۰۰ کاربر ادعا نمی‌شود.

**تاریخ گزارش:** ۱۴۰۵/۰۶/۰۹ — ۲۰۲۶-۰۸-۳۱
**شاخه:** `arena/01a054c0-aibox-odoo`
**مبنای بررسی:** درخت فعلی مخزن و commit پایه `853400c8fb898cdd9cb07b6e48f5d158cd3f2d96`
**نوع بررسی:** ممیزی baseline استاتیک سورس، manifest، XML/داده، ACL، API و frontend؛ بدون اجرای stack واقعی

> این بخش، snapshot baseline پیش از اصلاحات الحاقیهٔ بالا است. نصب و اجرای واقعی ERP، PostgreSQL، Redis، vLLM/مدل، IdP، Telegram، Buzz یا DGX انجام نشده؛ بنابراین هیچ PASS عملیاتی یا production certification قابل ادعا نیست.

---

## ۱. نتیجهٔ مدیریتی

### verdict نهایی

**وضعیت تولید: BLOCKED — آمادهٔ نصب/تحویل production نیست.**

سامانه از نظر معماری اجزای ارزشمندی دارد: gateway، session، API key، rate limit، ابزارهای نام‌دار، execution gate، approval، audit، event/outbox، workflow، RAG و frontend white-label. اما این اجزا هنوز یک محصول عملیاتی و قابل گواهی را تشکیل نمی‌دهند، چون چند blocker قطعی در مسیر نصب و چند شکست در مسیرهای حیاتی امنیت/مجوز وجود دارد.

مهم‌ترین نتیجه‌ها:

1. **نصب زنجیره‌ای addonها با دادهٔ capability تکراری متوقف می‌شود.**
2. **Deployment Wizard مدل نادرست را بررسی می‌کند** و readiness واقعی را نشان نمی‌دهد.
3. **Delegation در ایجاد رکورد شکست می‌خورد** چون API مرکزی با امضای اشتباه فراخوانی شده است.
4. **SCIM در یک constraint قطعی `NameError` دارد** و از نظر استاندارد provisioning نیز minimal است.
5. **SSO چندشرکتی/claim/group enforcement کامل نیست** و provider lookup tenant-safe نیست.
6. **ACL بومی customer plane با نقش‌های مرکزی هم‌خوان نیست**؛ در نتیجه یک نقش مجاز مرکزی ممکن است در CRUD عادی رد شود.
7. **برای Restaurant/`pos_restaurant` adapter، capability و operation دامنه‌ای وجود ندارد**؛ فقط POS عمومی دیده می‌شود.
8. **White-label کامل نیست**؛ هم frontend/API شناسه‌های فنی برمی‌گردانند و هم debrand عمدتاً DOM/QWeb best-effort است.
9. **نصب‌کننده‌های root که اسناد به آن‌ها ارجاع می‌دهند در checkout فعلی وجود ندارند.**
10. **هیچ runtime certification انجام نشده است.** حتی مواردی که static PASS هستند باید روی DGX واقعی با stack native تأیید شوند.

---

## ۲. انطباق با نیازهای محصول

| نیاز محصول | وضعیت فعلی | نتیجهٔ دقیق |
|---|---|---|
| انجام عملیات شرکت با زبان طبیعی | 🟡 ناقص | مسیر chat و ابزارهای نام‌دار وجود دارد؛ پوشش همهٔ دامنه‌ها و اجرای واقعی همهٔ ماژول‌های نصب‌شده اثبات نشده است. |
| AI سازمانی کامل: ابزار، خروجی، فایل، تاریخچه، حافظه، جستجو، گزارش، approval و automation | 🟡 ناقص | اجزای هرکدام موجودند، ولی history pagination، memory/RAG recovery، خروجی امن و runtime end-to-end کامل اثبات نشده‌اند. |
| هویت، نقش، دسترسی، ریسک، approval، اجرا، audit، اعلان، workflow، فایل و RAG در یک مسیر مرکزی | 🟡 معماری موجود / runtime اثبات‌نشده | gateway و execution gate مسیر مرکزی دارند، اما customer profile به runtime compile نمی‌شود و بعضی endpoint/cronها مسیرهای جداگانه دارند. |
| ACL/Record Rule/FGA قبل از نمایش، تحلیل و vector search | 🟡 کنترل‌های مهم موجود / پوشش یکنواخت اثبات‌نشده | RAG filter و attachment ownership وجود دارد؛ باید روی تمام upload، preview، download، context، search، export و async worker با تست runtime اثبات شود. |
| عدم نمایش نام برند ERP در chat، AI output، UI و customer experience | 🔴 ناقص | QWeb/DOM debrand وجود دارد، اما `/api/bootstrap` مدل/نوع action و فهرست moduleها را برمی‌گرداند؛ خروجی provider/model/error/third-party نیز firewall کامل و سراسری ندارد. |
| نصب bare-metal/native روی DGX GB10، بدون Docker | 📐 اثبات‌نشده و فعلاً blocked | اسناد قرارداد native را تعریف کرده‌اند، ولی installerهای root مفقودند و نصب واقعی روی DGX انجام نشده است. |
| هر ماژول نصب‌شده باید discover/authorize/audit/event/capability و در صورت نیاز adapter عملیاتی داشته باشد | 🔴 برآورده نشده | discovery و registry عمومی وجود دارد، اما readiness همهٔ moduleهای نصب‌شده را الزام نمی‌کند و Restaurant integration ندارد. |
| Restaurant باید از همان مسیر مرکزی قابل انجام باشد | 🔴 غایب | `point_of_sale` عمومی ثبت شده؛ adapter/operation/capability مخصوص Restaurant یا `pos_restaurant` دیده نشد. |

---

## ۳. معماری فعلی و وابستگی‌ها

### مسیر منطقی اجرا

```text
Frontend / Telegram / Discuss
          ↓
Semantic API + AI Gateway
          ↓
Session / API key / rate limit / tenant context
          ↓
Chat queue یا named tool endpoint
          ↓
Central authorization + capability + risk + approval + execution gate
          ↓
Business tools یا reviewed adapter
          ↓
Native ERP model + ACL/record rule
          ↓
Audit + durable event/outbox
          ↓
Notification / workflow / memory / RAG / Telegram / Buzz workers
```

این معماری در سطح کد تا حد زیادی قابل مشاهده است، اما چند مسیر از آن خارج می‌شوند: cron collaboration مستقیماً chat core را صدا می‌زند؛ customer profile فقط JSON ذخیره می‌کند؛ SCIM و SSO مسیرهای `sudo()`-محور جدا دارند؛ و frontend بعضی صفحات را بدون اتصال به API واقعی نمایش می‌دهد.

### تعداد و لایهٔ addonها

در checkout فعلی **۱۶ custom addon** وجود دارد:

- `company_ai_demo`: agent، حافظه و پایهٔ LLM
- `ai_gateway`: authentication، session، chat، queue، rate limit و execution entrypoint
- `ai_business_tools`: ابزارهای HR، task، document، communication، calendar، report، schedule و role-safe actions
- `ai_control_plane`: capability، policy، authorization، classification و durable events
- `ai_integration`: discovery، adapter، unified operation، event subscriber، model router و certification
- `ai_workflow`: workflow durable، retry و idempotency
- `ai_rag`: chunk، embedding، pgvector/search و async indexing
- `ai_semantic_api`: APIهای semantic برای chat، HR، document، admin و integration
- `ai_customer_plane`: role/policy، access review، temporary grant، delegation، SSO، SCIM و deployment profile
- `ai_collaboration`: workspace، Discuss opt-in و Buzz identity
- `ai_document_intelligence`: job تحلیل فایل
- `ai_correspondence`: template و نامهٔ رسمی
- `ai_production`: release checks/certification record
- `ai_experience`: façade/API سطح تجربهٔ کاربر
- `ai_telegram_bridge`: اتصال per-user به Telegram
- `ai_debrand`: حذف branding در view/template/DOM

### وابستگی لایه‌ای

1. **پایه:** ERP core، HR، accounting، stock، manufacturing، project، calendar، mail و پشتهٔ LLM.
2. **هوش و gateway:** `company_ai_demo` ← `ai_gateway` ← `ai_business_tools`.
3. **control/integration:** `ai_control_plane` و `ai_integration` روی gateway و business tools سوار هستند.
4. **امنیت و دانش:** `ai_workflow`، `ai_rag`، `ai_semantic_api` و `ai_customer_plane` به control/integration/gateway وابسته‌اند.
5. **تجربه و کانال‌ها:** `ai_experience` به تقریباً تمام اجزای بالا وابسته است؛ collaboration، document intelligence، correspondence، production و Telegram مصرف‌کنندهٔ مسیر مرکزی‌اند.
6. **Debrand:** عمداً مستقل و برای نصب آخر تعریف شده، ولی installer ترتیب نصب آن در checkout فعلی موجود نیست.

### ماژول‌های دامنه‌ای مورد انتظار و شکاف

در دادهٔ integration برای HR، leave، project، sales، purchase، stock، accounting، CRM، attendance، expense، manufacturing، calendar، documents، helpdesk و POS operation تعریف شده است. این موارد بیشتر **registry/data declaration** هستند؛ readiness باید وجود واقعی module، handler، capability، risk، ACL، event و runtime test آن‌ها را جداگانه بررسی کند.

برای Restaurant هیچ `pos_restaurant`، مدل دامنه‌ای، handler یا operation اختصاصی در source دیده نشد. POS عمومی (`pos.order.create`) جایگزین Restaurant integration محسوب نمی‌شود.

---

## ۴. یافته‌های قطعی بر اساس severity

### P0 — مانع نصب یا امنیت/مجوز حیاتی

| شناسه | یافته | شاهد | اثر |
|---|---|---|---|
| P0-01 | capabilityهای تکراری با constraint یکتا | `ai_control_plane/data/capability_data.xml:7-13` و `ai_integration/data/capability_data.xml:5` برای `hr.leave.approve` و `project.task.create`؛ همچنین `artifact.generate` در `ai_control_plane/data/capability_data.xml:30` و `ai_experience/data/capability_data.xml:3` | نصب زنجیره‌ای می‌تواند در insert دوم با unique constraint شکست بخورد و transaction را rollback کند. باید یک source of truth برای هر capability وجود داشته باشد. |
| P0-02 | installerهای root مفقود | اسناد به `00_final_production_install.sh`، `01_setup_base.sh`، `02_install_modules.sh` و سایر `0x_*` ارجاع می‌دهند؛ این فایل‌ها در checkout فعلی نیستند. | مسیر ادعایی نصب native قابل اجرا نیست؛ audit نیز `P0-1 generic-tool-deny: 02_install_modules.sh` را fail ثبت کرده است. |
| P0-03 | readiness مدل نادرست را بررسی می‌کند | `custom_addons/ai_customer_plane/models/customer_config.py:43-45` مدل `ai.integration.module` را لازم می‌داند؛ مدل واقعی discovery `ai.control.module` است. | `all_required_models` عملاً false می‌شود و deployment wizard نمی‌تواند readiness معتبر بدهد. |
| P0-04 | delegation با signature اشتباه | `custom_addons/ai_customer_plane/models/delegation.py:40-43` فراخوانی `check_capability(rec.delegator_id, rec.capability, model=..., res_id=...)` است؛ قرارداد واقعی در `ai_control_plane/models/authorization.py:97-98`، `check_capability(capability, user=None, record=None, action="execute")` است. | ایجاد delegation به `TypeError` می‌رسد یا هرگز authority را درست validate نمی‌کند. این مسیر برای temporary/delegated access قابل اعتماد نیست. |
| P0-05 | audit فعلی false-positive دارد | `FINAL_EXHAUSTIVE_SOURCE_AUDIT.json` چند مورد مانند delegation را PASS گزارش می‌کند، در حالی که signature واقعی بالا با آن PASS سازگار نیست. | release gate به‌تنهایی منبع حقیقت نیست؛ باید audit خودکار با contract test و runtime test تقویت شود. |

### P1 — شکاف‌های جدی محصول، tenant یا امنیت

| شناسه | یافته | شاهد | اثر |
|---|---|---|---|
| P1-01 | SCIM exception import نشده | `ai_customer_plane/models/scim.py:1-3`، اما `ValidationError` در خط 60 استفاده شده است. | ایجاد/ویرایش group mapping می‌تواند به `NameError` ختم شود. |
| P1-02 | SCIM استاندارد و lifecycle کامل نیست | `ai_customer_plane/controllers/scim_api.py:40-92` و `103-164` | pagination و filter استاندارد محدود/غایب، PATCH فقط subset ساده، PUT semantics ناقص، user login conflict در update کنترل نشده، DELETE فقط `active=False` است، و membership مدیریت‌شده فقط assignment سفارشی است. |
| P1-03 | SCIM group POST در برابر ambiguity امن نیست | `scim_api.py:124-134` group را فقط با `name` global پیدا می‌کند. | در وجود groupهای هم‌نام یا global metadata، mapping tenant می‌تواند اشتباه یا مبهم شود. |
| P1-04 | SSO tenant/enforcement ناقص است | provider lookup در `ai_customer_plane/controllers/sso_api.py:10` فقط با name و active انجام می‌شود؛ فیلدهای `audience`، `claim_groups` و `enforce_for_company` در `models/sso.py:17-23` تعریف شده‌اند، اما در auth path مؤثر نیستند. | provider یک شرکت می‌تواند برای شرکت دیگر resolve شود؛ group-to-role provisioning و enforce-for-company قابل اتکا نیست. |
| P1-05 | ACL customer plane با capability مرکزی mismatch دارد | `ai_customer_plane/security/ir.model.access.csv:2-14` تقریباً همهٔ modelها را فقط برای `base.group_system` باز می‌کند، در حالی‌که API در `customer_designer_api.py:9` capability `customer.config.manage` را می‌پذیرد. | نقش Executive ممکن است از central check عبور کند ولی در `create/search/write` native ACL شکست بخورد. |
| P1-06 | configuration profile به runtime compile نمی‌شود | `customer_config.py:8-20` policyها را به JSON ذخیره می‌کند و `activate()` فقط profile قبلی را archive می‌کند. | activation به capability، authorization، tool، approval matrix، document policy یا workflow runtime تبدیل نمی‌شود؛ profile عملاً configuration record است، نه policy engine. |
| P1-07 | readiness همهٔ moduleهای نصب‌شده را پوشش نمی‌دهد | `customer_config.py:51-52` فقط ده adapter محدود و subscriber set ثابت را بررسی می‌کند. | `helpdesk`، `point_of_sale`، `hr_attendance`، `hr_expense` و Restaurant/ماژول‌های بعدی الزام readiness نمی‌شوند. |
| P1-08 | Restaurant integration غایب است | `ai_integration/data/adapter_data.xml:54` فقط `point_of_sale` و `unified_operation_data.xml:18` فقط `pos.order.create` را تعریف می‌کند؛ در کل source `pos_restaurant` یا operation/handler restaurant وجود ندارد. | الزام صریح محصول برای discover/authorize/audit/event/capability و عملیات واقعی Restaurant برآورده نشده است. |
| P1-09 | white-label کامل نیست | `ai_gateway/controllers/gateway.py:384-424` در `/api/bootstrap` action type/model و installed module list را برمی‌گرداند؛ `ai_debrand` عمدتاً QWeb/DOM replacement است. | شناسه‌های فنی ممکن است در API، خطا، provider/model context، third-party UI یا پاسخ AI نشت کنند. |
| P1-10 | مسیر collaboration خارج از اجرای استاندارد و پرریسک است | `ai_collaboration/models/channel_link.py:77` import از `custom_addons.ai_gateway...` دارد، در حالی‌که الگوی بقیهٔ کد `odoo.addons...` است؛ cron نیز در خطوط 52-64 با `sudo()` پیام‌ها را scan می‌کند و cursor را برای پیام بدون trigger جلو نمی‌برد. | cron ممکن است در deployment fail شود؛ scan تکراری باعث فشار DB/cron می‌شود؛ این مسیر باید همان execution/audit/output policy مرکزی را به‌صورت صریح enforce کند. |
| P1-11 | frontend سطح محصول را کامل پیاده نکرده است | `frontend/src/App.jsx:50-56` تقویم hard-coded است، دکمه‌های Department/Task بعضاً handler ندارند، Approval عمدتاً read-only است، و فقط route مدیریت capability gate دارد. | UI ممکن است ظاهر یک سیستم کامل را نشان دهد، اما بسیاری از عملیات واقعی/tenant-aware از صفحه در دسترس نیستند یا صرفاً placeholder هستند. |
| P1-12 | notification با HTML خام render می‌شود | `frontend/src/App.jsx:56` از `dangerouslySetInnerHTML={{__html:n.body||""}}` استفاده می‌کند. | اگر upstream sanitization در همهٔ مسیرها تضمین نشود، ریسک XSS در customer UI وجود دارد؛ باید sanitize و CSP با تست امنیتی اثبات شود. |

### P2 — کیفیت، کارایی و بلوغ عملیاتی

| شناسه | یافته | شاهد/اثر |
|---|---|---|
| P2-01 | صف داخلی chat در هر process جداست | `ai_gateway/models/chat_queue.py` صف process-local دارد و برای هماهنگی cross-process از Redis lease استفاده می‌کند؛ پیش‌فرض application concurrency برابر ۸، waiter برابر ۱۲۸ و timeout برابر ۲۴۰ ثانیه است. | burst صدتایی در صف application پذیرفته می‌شود، اما ظرفیت واقعی، tail latency و sizing روی GPU باید با load test native تأیید شود. |
| P2-02 | SSE، token streaming واقعی نیست | `ai_gateway/controllers/gateway.py:556-614` ابتدا generation blocking انجام می‌شود و سپس متن نهایی word-sized chunk می‌شود. | تجربهٔ progressive وجود دارد، ولی latency واقعی قبل از اولین token پنهان نمی‌شود و backpressure/provider streaming حل نشده است. |
| P2-03 | bootstrap احتمال N+1 دارد | `gateway.py:384-407` برای هر menu فرزندها را جداگانه search می‌کند. | در database بزرگ startup latency و query count بالا می‌رود؛ باید endpoint contract و cache/pagination داشته باشد. |
| P2-04 | SCIM list مقیاس‌پذیر نیست | `scim_api.py:47-51` `search_count` و سپس search با limit ثابت ۱۰۰ دارد، بدون startIndex/count و filter واقعی. | sync سازمان‌های بزرگ ناقص یا پرهزینه می‌شود. |
| P2-05 | report مصرف token دقیق نیست | خود gateway آن را `ESTIMATE (chars/4)` می‌نامد. | برای billing/quota قابل اتکا نیست؛ usage provider باید ثبت شود. |
| P2-06 | history API pagination ندارد | پیام‌ها در mail.message نگهداری می‌شوند، ولی API history در مسیرهای تجربه محدودسازی/صفحه‌بندی کامل ندارد. | رشد thread باعث latency و memory pressure می‌شود. |

---

## ۵. وضعیت قابلیت‌ها

| حوزه | آنچه در source هست | شکاف/وضعیت |
|---|---|---|
| Identity و نقش | `res.users`، `res.groups`، employee/department، role assignment، Excel import | role transition/update، ACL هماهنگ و runtime provisioning نیازمند تست و hardening است. |
| Temporary access و approval | access grant، review، approval، immutable fields و re-check مرکزی | delegation contract فعلاً شکسته است؛ activation/revocation و replay باید runtime تست شود. |
| Chat | `/api/chat` و `/api/chat/stream`، thread ownership، attachment ownership، bounded pool | generation blocking، history pagination، full output firewall و runtime GPU behavior اثبات‌نشده. |
| ابزارهای کسب‌وکار | leave، task، communication، document، calendar، report، schedule و ابزارهای دیگر | registry declaration با «همهٔ عملیات شرکت» یکی نیست؛ update/delete/read/approve همهٔ دامنه‌ها کامل نیستند. |
| فایل | `ir.attachment`، document API، upload/download/preview و file intelligence | ACL قبل از هر مسیر async/search/export باید با matrix تست شود؛ frontend HTML و error output نیز باید کنترل شوند. |
| RAG | chunk/index job، embedding، vector search و pre-filter مبتنی بر access | اجرا، retry/recovery، حذف سند و stale index روی stack واقعی تأیید نشده. |
| Memory | canonical memory و policy/classification | encryption policy و lifecycle در static دیده می‌شود، اما retention، deletion، reindex و leakage runtime اثبات نشده. |
| Workflow و event | durable event، subscription matrix، outbox، retry/idempotency و workflow cron | event delivery، dead-letter recovery، duplicate prevention و subscriber فعال باید با PostgreSQL/Redis واقعی تست شود. |
| SSO | OIDC state/nonce/JWK و SAML endpoint | company binding، audience field، claim groups، enforced provider و role synchronization ناقص است. |
| SCIM | hashed token، company-scoped user/group endpoint و managed assignment | RFC semantics minimal، exception bug، pagination/filter و lifecycle ناقص است. |
| Telegram | per-user identity/link code و اتصال به gateway | اتصال واقعی، webhook، فایل/صوت، retry و unlink هنوز runtime certified نیست. |
| Buzz/Discuss | channel opt-in، trigger و cron | import path، scan cursor/performance، output policy و execution/audit یکپارچه نیازمند اصلاح/تست است. |
| Correspondence | template و validation | generation/approval/issue lifecycle و attachment access کامل به API عملیاتی متصل نشده است. |
| Production certification | مدل release/check و endpoint certify | `certify()` فقط checkهای ثبت‌شده را می‌بیند؛ اگر check runtime واقعاً تولید نشده باشد، نتیجهٔ معنادار نیست. |
| Frontend | login، dashboard، chat، documents، admin، integrations، leaves و صفحات پایه | بعضی صفحات static/read-only/placeholder هستند؛ capability gating باید برای همهٔ route و actionها اعمال شود. |
| Restaurant | POS عمومی | **غایب**؛ `pos_restaurant` و عملیات واقعی Restaurant وجود ندارد. |

---

## ۶. بررسی امنیت و حریم داده

### نقاط مثبت موجود

- generic `/api/rpc` به‌صورت hard 410 بسته شده است (`gateway.py:498-509`).
- chat از attachment ownership و thread ownership دفاع می‌کند.
- execution gate، risk registry، approval و ACL/record rule به‌عنوان defense in depth طراحی شده‌اند.
- API key hashing/expiry/rotation و session rotation در source وجود دارد.
- RAG طراحی شده تا access filter قبل از vector search اعمال شود.
- temporary access قرار نیست با mutation گروه native authority بسازد.

### مواردی که هنوز نمی‌توان امن اعلام کرد

- `sudo()` در SCIM، event، collaboration و بعضی admin مسیرها باید با tenant/company boundary و input contract آزمون شود.
- central authorization و native ACL همیشه یک تصمیم واحد نمی‌دهند؛ mismatch customer plane ثابت است.
- debrand فقط ظاهر را تغییر می‌دهد و جایگزین output/context firewall نیست.
- پاسخ bootstrap، metadata و خطاها ممکن است شناسهٔ فنی یا نام module/provider را آشکار کنند.
- notification HTML و هر third-party rendered content باید sanitization مستقل داشته باشد.
- هیچ آزمون واقعی cross-company، cross-department، delegated access، revoked access، stale session و concurrent replay اجرا نشده است.

---

## ۷. کارایی و ظرفیت مورد انتظار

این اعداد **تنظیمات source هستند، نه benchmark**:

- chat pool پیش‌فرض: ۲ turn هم‌زمان در هر process؛ ۱۰ waiter؛ timeout برابر ۱۸۰ ثانیه.
- queue process-local است؛ چند process روی یک GPU هماهنگی global ندارند.
- `/api/chat/stream` قبل از ارسال delta، generation کامل را منتظر می‌ماند.
- attachment/file analysis ابتدا داده را base64 می‌کند و تحلیل را داخل prompt chat تزریق می‌کند؛ برای فایل‌های بزرگ memory/latency باید اندازه‌گیری شود.
- collaboration cron برای هر link تا ۲۰۰ پیام می‌خواند و در حالت فعلی پیام‌های بدون trigger را در cursor جلو نمی‌برد؛ با تعداد link/پیام بالا scan تکراری ایجاد می‌شود.
- SCIM list count+search دارد و pagination استاندارد ندارد.
- bootstrap برای menu tree احتمال queryهای متعدد دارد.
- token usage فعلی تخمینی است و برای quota/billing دقیق نیست.
- workerهای event و RAG در `runtime_workers/` و service fileها تعریف شده‌اند، اما اجرا و recovery واقعی آن‌ها مشاهده نشده است.

### الزام ظرفیت برای DGX native

قبل از production باید این موارد روی یک worker stack واقعی اندازه‌گیری شوند:

1. latency p50/p95/p99 برای chat ساده، chat با tool، فایل، RAG و approval.
2. تعداد workerهای ERP در برابر یک GPU و یک vLLM process.
3. queue wait، timeout، cancellation و رفتار restart.
4. throughput embedding/indexing و اثر آن بر chat.
5. PostgreSQL query count/lock duration برای bootstrap، history، SCIM و event outbox.
6. Redis availability، rate limit، distributed lock و recovery.
7. رفتار حافظه و disk برای attachment، chunk و audit log.

---

## ۸. تناقض اسناد release و وضعیت واقعی checkout

اسناد موجود نباید بدون بازبینی به‌عنوان release certificate استفاده شوند:

- `FINAL_RELEASE_STATUS.md` از source PASS و `94/94` صحبت می‌کند، اما `FINAL_EXHAUSTIVE_SOURCE_AUDIT.json` فعلی صراحتاً `P0-1 generic-tool-deny` را fail کرده است و یافته‌های قطعی بالا در آن منعکس نشده‌اند.
- `FINAL_COMPLETION_REPORT.md` ادعای manifest بدون missing/mismatch دارد. مقایسهٔ فعلی نشان می‌دهد:
  - manifest: **۳۹۲ entry**؛
  - فایل‌های موجود بر اساس enumeration فعلی: **۳۸۷**؛
  - path مفقود در tree: **۹**؛
  - فایل unlisted: **۴**.
- pathهای مفقود شامل این installerها و deployment scripts هستند: `00_final_production_install.sh`، `01_setup_base.sh`، `02_install_modules.sh`، `03_start_all.sh`، `04_seed_demo_data.sh`، `06_setup_tls.sh`، `07_setup_backups.sh`، `08_deployment_checklist.sh` و `09_setup_soup_finetune.sh`.
- `FEATURE_COVERAGE.md` بعضی حوزه‌ها را ✅ نشان می‌دهد، اما current source برای Restaurant integration، readiness جامع، SSO enforcement، delegation و frontend کامل با آن سطح از ادعا سازگار نیست.
- در نتیجه، اسناد باید به سه دستهٔ «static evidence»، «runtime verified» و «production certified» تفکیک شوند؛ فعلاً دستهٔ دوم و سوم خالی است.

---

## ۹. برنامهٔ ارتقا — فقط پیشنهاد، بدون اعمال خودکار

هیچ‌یک از موارد این بخش در این turn روی source اعمال نشده است. اجرای آن‌ها نیازمند تأیید صریح مالک محصول است.

### فاز ۰ — unblock نصب و integrity

1. تعیین source of truth برای capability و حذف/تغییر شناسه‌های تکراری با migration امن.
2. بازسازی installerهای native root یا اصلاح اسناد تا فقط فایل‌های واقعاً موجود را ارجاع دهند.
3. بازتولید SHA manifest پس از تعیین دقیق scope، بدون ادعای zero-missing نادرست.
4. اجرای install/upgrade idempotency روی database خالی و database upgrade.
5. تبدیل audit به fail-closed واقعی: هیچ check مهمی نباید صرفاً با وجود نام فایل یا `grep` PASS شود.

### فاز ۱ — اصلاح authorization و tenant boundary

1. اصلاح delegation برای استفاده از قرارداد canonical: capability، user، record و action؛ سپس تست create/revoke/expiry/replay.
2. اصلاح readiness به model واقعی `ai.control.module` و ساخت registry واحد از model/adapter/operation/subscriber/module نصب‌شده.
3. هماهنگ‌سازی ACL native با role/capabilityهای customer plane؛ central allow بدون native CRUD allow مجاز نباشد و برعکس.
4. compile کردن configuration profile به immutable versioned runtime snapshot شامل role، capability، tool، risk، approval، document، workflow و agent.
5. اعمال company binding در SSO provider lookup، enforce-for-company، audience و claim validation؛ تعریف صریح mapping claim گروه به product role.
6. تکمیل SCIM با `startIndex`/`count`/`filter`، ETag/version semantics، PATCH pathهای استاندارد، PUT، conflict update، deprovisioning و tenant-safe group identifier؛ افزودن import صحیح exception.

### فاز ۲ — پوشش کامل integration و Restaurant

1. ساخت adapter دامنه‌ای `pos_restaurant` با capabilityهای مشخص و operationهای واقعی، نه alias به POS عمومی.
2. تعیین برای هر module نصب‌شده: discover، capability، risk، authorization policy، adapter/handler، event، audit، notification و certification test.
3. readiness dynamic بر اساس installed modules، نه فهرست hard-coded محدود.
4. ثبت operationهای read/create/update/delete/approve مورد نیاز هر domain و حذف declarationهایی که handler واقعی ندارند.
5. یکسان‌سازی مسیر tool و adapter تا هر mutation از همان execution gate، approval و audit عبور کند.

### فاز ۳ — فایل، RAG و white-label

1. ایجاد authorization matrix مشترک برای attachment، document، chunk، embedding، preview، download، search، context، export و async worker.
2. تست عدم نشت با company/department/team/user/delegation/revocation و سند classified.
3. ایجاد output/context firewall مرکزی برای حذف technical platform/provider/model/exception identifiers پیش از chat، API، notification و third-party channel.
4. حذف یا عمومی‌سازی metadata فنی از bootstrap و API response؛ frontend فقط capability/label کاربرپسند دریافت کند.
5. حذف `dangerouslySetInnerHTML` یا sanitize معتبر، CSP و XSS test.

### فاز ۴ — frontend محصولی

1. اتصال calendar، departments، knowledge، approvals، tasks و agents به API واقعی با loading/error/empty state و permission gate.
2. افزودن history pagination، search، memory controls، citations، approval action، automation builder و file upload policy.
3. نمایش وضعیت واقعی سلامت AI به‌جای «AI Online» hard-coded.
4. پشتیبانی کامل از فارسی/RTL، notification read state و white-label snapshot test.

### فاز ۵ — native DGX certification

1. نصب bare-metal با systemd برای ERP، PostgreSQL/pgvector، Redis، vLLM، event worker و RAG worker؛ بدون Docker.
2. اجرای install/upgrade، seed، SSO، SCIM، chat، tool، approval، delegation، file/RAG، event، workflow، Telegram، Buzz و Restaurant.
3. اجرای security matrix و load test روی دادهٔ چندشرکتی.
4. ثبت evidence شامل command، version، log، latency، query/lock، GPU utilization و artifact digest.
5. فقط در صورت عبور همهٔ P0/P1 و runtime testها، صدور certification؛ در غیر این صورت release باید BLOCKED بماند.

---

## ۱۰. acceptance gate پیشنهادی برای اعلام آمادگی

هیچ release production نباید صرفاً با static audit سبز اعلام شود. حداقل gates:

- نصب تمام moduleهای target روی DB خالی بدون unique/ACL/import error.
- upgrade idempotent روی DB دارای داده.
- readiness wizard با model registry واقعی، adapterهای نصب‌شده و subscriberهای فعال.
- delegation create/revoke/expiry و approval replay با re-authorization.
- SSO چندشرکتی با provider اشتباه، audience اشتباه، nonce/state replay و claim group نامعتبر.
- SCIM RFC test برای pagination/filter/PATCH/PUT/DELETE/conflict/deprovision.
- دو شرکت، دو department و classificationهای متفاوت؛ هیچ نشت در UI، API، RAG، chunk، memory، attachment یا notification.
- اجرای موفق همهٔ operationهای ثبت‌شده با handler واقعی و native ACL واقعی.
- Restaurant: ایجاد/اصلاح/تأیید عملیات business واقعی از chat و API با audit/event/approval.
- queue/load test با چند process و یک GPU، Redis failure، worker restart و dead-letter recovery.
- white-label test روی rendered UI، API، AI output، errors، logs قابل‌نمایش، metadata و کانال‌های Telegram/Buzz.
- ثبت نسخهٔ immutable برای runtime، frontend، مدل‌ها، dependencyها و migration.

---

## ۱۱. وضعیت تغییرات این turn

- source hardening، readiness scoping، upload security، debranding و frontend dependency fixes اعمال و ذخیره شدند.
- native install/upgrade/start scripts و migration hook اضافه شدند، اما به‌علت نبود Odoo/PostgreSQL/Redis/vLLM در این محیط اجرا نشدند.
- `FINAL_EXHAUSTIVE_SOURCE_AUDIT.json` نتیجهٔ current source را نگه می‌دارد: ۹۴/۹۴ و `runtime_certification: REQUIRED_ON_REAL_STACK`.
- production certification: **SOURCE-HARDENED / RUNTIME-BLOCKED**.
- بخش‌های قدیمی این گزارش baseline تاریخی هستند؛ تست‌های باقی‌مانده در الحاقیه و `UPGRADE_PLAN_AND_EXECUTION_LOG_FA.md` منبع اجرای بعدی‌اند.

**نتیجهٔ نهایی:** مسیر سورس و native installer اکنون قابل ادامه و قابل audit است، اما checkout هنوز production-certified نیست. ابتدا باید install/upgrade واقعی، migration، security matrix، RAG leakage، IdP integration، queue/Redis test و DGX benchmark اجرا و evidence آن‌ها ثبت شود.

---

## الحاقیه — hardening RAG، memory و ظرفیت (2026-09-04)

در این مرحله مسیر retrieval از sort ترکیبی مستقیم به دو candidate scan مستقل تغییر کرد: candidateهای semantic با ترتیب HNSW و candidateهای lexical با GIN/full-text؛ پس از آن merge، threshold و hybrid rank در لایهٔ application انجام می‌شود. ACL/FGA و snapshot gate قبل از هر دو scan باقی مانده‌اند.

embedding cache در مسیر اصلی query فعال است و فقط digest endpoint/model/revision را با vector فشردهٔ float32 نگه می‌دارد. memory encrypted نیز HMAC token digest و migration backfill دارد تا search عادی مجبور به decrypt کردن کل جدول نباشد. file reader محدودیت اندازه و failure صریح دارد و RAG بدون excerpt کافی پاسخ را `insufficient_context` اعلام می‌کند.

اعتبارسنجی قابل تکرار این turn: 28 تست source-contract، compileall، XML parse و queue self-test با `PASS=14 FAIL=0` موفق شدند. این‌ها static/pure-runtime evidence هستند و جای install/upgrade واقعی Odoo یا benchmark روی PostgreSQL/Redis/vLLM/DGX را نمی‌گیرند؛ release همچنان `RUNTIME_CERTIFICATION_REQUIRED` است.
