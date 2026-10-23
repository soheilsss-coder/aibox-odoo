# Master Plan — Customer Setup Center و Admin Control Plane

**تاریخ:** 2026-09-05
**شاخه:** `arena/01a054c0-aibox-odoo`
**وضعیت مبنا:** commit `0f5d011`
**هدف:** تبدیل Admin Console فعلی به پنل کامل و fail-closed برای آماده‌سازی، شخصی‌سازی، فعال‌سازی و تحویل appliance هر مشتری.

---

## 0. اصل مهم این برنامه

هدف این برنامه «تضمین بدون باگ با ادعا» نیست؛ هیچ پیاده‌سازی نرم‌افزاری را نمی‌توان بدون اجرای runtime و evidence واقعی بدون باگ اعلام کرد. هدف این برنامه این است که:

- هر feature قرارداد مشخص داشته باشد.
- هر تغییر backend با migration و rollback همراه باشد.
- هر mutation از endpoint نام‌دار و authorization مرکزی عبور کند.
- هیچ feature صرفاً با mock یا static test production-ready اعلام نشود.
- هر مرحله قبل از ورود به مرحله‌ی بعدی gate قابل اندازه‌گیری داشته باشد.
- خطا در setup به‌صورت fail-closed باقی بماند.
- appliance مشتری بدون عبور از readiness gate تحویل داده نشود.

این سند، ترتیب اجرای کار را مشخص می‌کند. ترتیب مراحل قابل جابه‌جایی نیست مگر با ثبت تصمیم معماری و دلیل آن.

---

# 1. وضعیت فعلی و delta موردنیاز

## 1.1 قابلیت‌های موجود

در repository فعلی این بخش‌ها وجود دارند:

- Admin route با privilege check مرکزی.
- مشاهده‌ی roleها و اعضای role.
- temporary access و delegation.
- فهرست اسناد سازمان.
- Agentها و tool risk registry.
- metrics پایه.
- کشف application moduleهای Odoo.
- نصب application module از مسیر رسمی `ir.module.module`.
- ثبت durable درخواست نصب و نتیجه‌ی آن.
- `ai.customer.configuration.profile` در backend.
- compile و hash کردن runtime configuration profile.
- deployment readiness logic در backend.
- white-label پایه برای brand name و domain.

## 1.2 کمبودهای قطعی

در وضعیت فعلی موارد زیر کامل نیستند:

- Customer Setup Wizard یکپارچه.
- company profile کامل برای آماده‌سازی مشتری.
- logo upload از پنل.
- favicon.
- رنگ‌های قابل تنظیم و dynamic theme.
- اعمال brand در React frontend.
- preview زنده‌ی brand.
- login message و footer قابل تنظیم از پنل.
- support information.
- setup checklist و handoff gate.
- UI کامل برای configuration profile.
- UI برای compile/activate/archive/deploy dry-run.
- policy configuration برای moduleهای نصب‌شده.
- SSO/SCIM setup کامل.
- upgrade/disable guard برای moduleها.
- customer handoff report.
- runtime certification متصل به نتیجه‌ی setup.

## 1.3 تصمیم معماری اصلی

هر مشتری یک appliance و database مستقل دارد. بنابراین:

- tenant جدید در frontend ساخته نمی‌شود.
- هیچ multi-tenant control plane جدیدی اضافه نمی‌شود.
- تنظیمات customer در همان database و با `company_id` ذخیره می‌شوند.
- module activation برای همان appliance/database انجام می‌شود.
- authorization native Odoo، ACL، record rule، capability و FGA باقی می‌مانند.
- vendor یا module installer جای authorization مرکزی را نمی‌گیرد.
- Docker استفاده نمی‌شود.
- سرویس‌ها با systemd اجرا می‌شوند.
- داده‌ی مشتری برای brand، parsing، embedding یا inference به cloud ارسال نمی‌شود.

---

# 2. خروجی نهایی مورد انتظار

در پایان این برنامه، administrator باید بتواند از یک مسیر مشخص:

1. اطلاعات مشتری را وارد کند.
2. brand را کامل تنظیم کند.
3. logo و favicon را آپلود کند.
4. preview واقعی frontend را ببیند.
5. moduleهای Odoo قابل ارائه را انتخاب و نصب کند.
6. وضعیت dependency و integration هر module را ببیند.
7. capability و risk هر module را review کند.
8. roleها و permissionهای مشتری را تنظیم کند.
9. document policy را مشخص کند.
10. agent و tool policy را تنظیم کند.
11. approval matrix و workflow policy را تنظیم کند.
12. configuration profile را compile و activate کند.
13. SSO/SCIM را در صورت انتخاب configure و test کند.
14. readiness checklist را اجرا کند.
15. deployment dry-run بگیرد.
16. backup و rollback artifact ثبت کند.
17. customer handoff report تولید کند.
18. تنها در صورت PASS شدن gate، سیستم را برای customer pilot فعال کند.

وضعیت نهایی باید یکی از این مقادیر باشد:

```text
NOT_READY
READY_FOR_INTERNAL_TEST
READY_FOR_CANARY
READY_FOR_CUSTOMER_HANDOFF
```

---

# 3. مدل داده‌ی نهایی

## 3.1 منبع حقیقت برند

یک منبع حقیقت صریح و company-scoped اضافه می‌شود. پیشنهاد اجرایی:

```text
ai.customer.branding
```

با constraint یکتایی روی:

```text
company_id
```

مدل باید حداقل این فیلدها را داشته باشد:

### هویت برند

- `company_id`
- `brand_name`
- `legal_name`
- `tagline`
- `brand_domain`
- `support_email`
- `support_url`
- `footer_text`
- `login_message`
- `product_title`
- `active`
- `version`
- `updated_by_id`
- `updated_at`

### دارایی‌های برند

- `logo`
- `logo_filename`
- `logo_mimetype`
- `favicon`
- `favicon_filename`
- `favicon_mimetype`

دارایی‌ها باید با `attachment=True` ذخیره شوند و محدودیت size/type داشته باشند.

### theme

- `primary_color`
- `secondary_color`
- `accent_color`
- `background_color`
- `surface_color`
- `surface_alt_color`
- `text_color`
- `text_muted_color`
- `danger_color`
- `warning_color`
- `font_family`
- `border_radius`

رنگ‌ها فقط باید با فرمت hex معتبر پذیرفته شوند. مقدار CSS خام، `url()`, expression و custom CSS در این مرحله ممنوع است.

### تنظیمات تجربه

- `default_language`
- `default_timezone`
- `default_date_format`
- `default_number_format`
- `default_currency_id`
- `show_ai_brand`
- `show_powered_by`
- `show_module_navigation`
- `support_contact_visible`

## 3.2 company profile

برای اطلاعات قانونی و عملیاتی، از فیلدهای استاندارد `res.company` استفاده می‌شود و از duplicate کردن آن‌ها جلوگیری می‌شود:

- name
- email
- phone
- website
- street
- street2
- city
- zip
- country_id
- currency_id
- logo در صورت استفاده‌ی مشترک با Odoo

فیلدهای white-label خاص در `ai.customer.branding` می‌مانند، نه در `ir.config_parameter` عمومی.

`ir.config_parameter` فقط برای compatibility fallback نسخه‌های قدیمی استفاده می‌شود و منبع اصلی آینده نخواهد بود.

## 3.3 configuration profile

مدل موجود `ai.customer.configuration.profile` حفظ می‌شود و کامل‌تر می‌گردد:

- role policy
- capability policy
- approval matrix
- document policy
- agent config
- tool config
- workflow config
- compiled runtime snapshot
- compiled hash
- version
- state
- compile timestamp
- activated by
- activation timestamp
- previous profile
- deployment result

JSON خام در backend باقی می‌ماند چون runtime به snapshot نیاز دارد؛ اما UI باید editor ساختاریافته داشته باشد.

## 3.4 setup run و handoff evidence

یک مدل durable برای اجرای setup اضافه می‌شود:

```text
ai.customer.setup.run
```

فیلدهای حداقلی:

- `company_id`
- `run_key`
- `requested_by_id`
- `started_at`
- `completed_at`
- `state`
- `current_stage`
- `result_json`
- `error_summary`
- `release_commit`
- `configuration_profile_id`
- `branding_version`
- `module_snapshot_hash`
- `runtime_certification_state`
- `backup_reference`
- `rollback_reference`

مقادیر state:

```text
queued
running
passed
failed
cancelled
```

هیچ نتیجه‌ای فقط از state frontend برداشت نمی‌شود؛ نتیجه باید در database و audit ذخیره شود.

---

# 4. قرارداد API نهایی

همه‌ی endpointهای جدید باید در semantic API و با auth موجود پیاده شوند. generic RPC مجاز نیست.

## 4.1 brand برای کاربران عادی

```text
GET /api/branding
GET /api/branding/logo
GET /api/branding/favicon
```

این endpointها فقط اطلاعات safe برند را برمی‌گردانند:

- brand name
- title
- tagline
- رنگ‌ها
- فونت مجاز
- URL assetها
- support information در صورت فعال بودن

هرگز این موارد را برنگردانند:

- secret
- token
- raw configuration JSON
- internal module name
- filesystem path
- database id غیرضروری

## 4.2 مدیریت company و branding

```text
GET  /api/admin/setup
POST /api/admin/setup/company
GET  /api/admin/branding
POST /api/admin/branding
POST /api/admin/branding/validate
POST /api/admin/branding/preview
POST /api/admin/branding/reset
```

`POST /api/admin/branding` باید از این عملیات پشتیبانی کند:

- update text fields
- update colors
- upload logo
- upload favicon
- clear logo
- clear favicon
- update experience flags
- version increment
- audit event

درخواست باید atomic باشد؛ اگر logo معتبر نیست، تغییر رنگ‌ها نباید نصفه ذخیره شود مگر اینکه API به‌صراحت patch semantics داشته باشد.

## 4.3 module catalog

endpointهای فعلی حفظ و تکمیل می‌شوند:

```text
GET  /api/admin/modules
POST /api/admin/modules/install
POST /api/admin/modules/upgrade
POST /api/admin/modules/disable
GET  /api/admin/modules/<id>/readiness
GET  /api/admin/modules/<id>/capabilities
GET  /api/admin/modules/<id>/menus
POST /api/admin/modules/sync
```

قواعد:

- install هر بار یک module.
- install idempotent.
- upgrade فقط با confirmation و backup reference.
- uninstall مستقیم از UI عمومی ممنوع تا rollback/compatibility گیت داشته باشد.
- disable فقط capability/navigation را محدود کند، نه اینکه رکوردهای Odoo را بدون migration حذف کند.
- technical module name به customer UI نمایش داده نشود مگر در حالت technical admin.

## 4.4 configuration profile

```text
GET  /api/admin/configuration-profiles
POST /api/admin/configuration-profiles
GET  /api/admin/configuration-profiles/<id>
PATCH /api/admin/configuration-profiles/<id>
POST /api/admin/configuration-profiles/<id>/validate
POST /api/admin/configuration-profiles/<id>/compile
POST /api/admin/configuration-profiles/<id>/activate
POST /api/admin/configuration-profiles/<id>/archive
POST /api/admin/configuration-profiles/<id>/dry-run
GET  /api/admin/configuration-profiles/<id>/history
```

هر mutation باید:

- company scope را چک کند.
- privilege را چک کند.
- JSON sectionها را validate کند.
- toolها را با unified registry تطبیق دهد.
- risk/approval contract را validate کند.
- audit شود.
- version را افزایش دهد.
- compiled snapshot را invalidate کند.

## 4.5 setup checklist و certification

```text
GET  /api/admin/setup/checklist
POST /api/admin/setup/checklist/run
GET  /api/admin/setup/runs
GET  /api/admin/setup/runs/<run_key>
POST /api/admin/setup/runs/<run_key>/cancel
POST /api/admin/setup/handoff-report
```

checklist باید حداقل این checkها را داشته باشد:

- company profile
- branding
- logo
- favicon
- valid theme
- selected modules
- module dependencies
- agent connections
- capability registry
- operation contracts
- subscriber matrix
- configuration profile
- compiled profile
- active profile
- SSO/SCIM اگر enabled
- database readiness
- RAG readiness
- runtime certification
- backup evidence
- rollback evidence

هر check باید این ساختار را برگرداند:

```json
{
  "key": "branding.logo",
  "label": "لوگو",
  "state": "pass",
  "severity": "blocking",
  "message": "لوگوی مشتری ثبت شده است",
  "remediation": null,
  "checked_at": "..."
}
```

severity:

```text
blocking
warning
informational
```

وجود warning به‌تنهایی handoff را fail نمی‌کند؛ وجود blocking fail می‌کند.

---

# 5. برنامه‌ی مرحله‌ای اجرا

## فاز 0 — Freeze، contract و baseline

### هدف

قبل از تغییر کد، مرز دقیق feature مشخص شود.

### کارها

1. branch و commit مبنا freeze شود.
2. current AdminPage و endpoint inventory ثبت شود.
3. field contract و API contract این سند به ticketهای کوچک تقسیم شود.
4. threat model نوشته شود.
5. تصمیم source-of-truth برند ثبت شود.
6. تصمیم اینکه `ai.customer.branding` در `ai_customer_plane` قرار می‌گیرد ثبت شود.
7. هیچ field جدیدی در `ir.config_parameter` بدون justification اضافه نشود.

### خروجی

- architecture decision record
- field dictionary
- API schema
- permission matrix
- migration plan
- rollback plan

### Gate خروج

- همه‌ی fieldها owner و source مشخص دارند.
- هیچ endpoint بدون auth/ACL design وجود ندارد.
- تیم روی معنی `install`, `upgrade`, `disable`, `archive`, `activate` توافق دارد.

---

## فاز 1 — مدل داده و migration پایه

### هدف

ساخت مدل‌های پایدار قبل از frontend.

### کارها

1. افزودن `ai.customer.branding`.
2. افزودن `ai.customer.setup.run`.
3. تکمیل audit fieldها.
4. افزودن company-scoped record rule.
5. افزودن ACL فقط برای roleهای مجاز.
6. ایجاد migration از brand name/domain قدیمی.
7. انتقال logo موجود از `res.company.logo` در صورت تصمیم معماری.
8. حفظ compatibility fallback برای نسخه‌ی قبلی.
9. اضافه‌کردن index روی `company_id`, `state`, `version`.
10. جلوگیری از دو branding فعال برای یک company.

### تست‌های اجباری

- create/update هر دو مدل.
- company isolation.
- non-admin read/write denial.
- invalid color rejection.
- oversized asset rejection.
- invalid image signature rejection.
- migration idempotency.
- duplicate active branding rejection.

### Gate خروج

- migration روی database clone موفق.
- upgrade دوم بدون تغییر مخرب موفق.
- rollback clone موفق.
- security tests سبز.

---

## فاز 2 — API برند و asset security

### هدف

ایجاد backend امن و کامل برای branding.

### کارها

1. پیاده‌سازی serializer مشترک branding.
2. اضافه‌کردن `GET /api/branding`.
3. اضافه‌کردن asset streaming امن.
4. اضافه‌کردن admin GET/POST.
5. validate MIME، extension، signature و size.
6. sanitize filename.
7. جلوگیری از SVG ناامن یا SVG را فعلاً ممنوع‌کردن.
8. محدودسازی logo و favicon به imageهای مشخص.
9. جلوگیری از خروج raw binary در log.
10. audit تمام تغییرات.
11. پیاده‌سازی reset با confirmation و audit.
12. جلوگیری از تغییر brand شرکت دیگر با company scope.

### Gate خروج

- unit tests کامل API.
- تست unauthorized و non-privileged.
- تست upload جعلی با extension معتبر.
- تست path traversal filename.
- تست asset بعد از logout.
- تست cache invalidation.
- هیچ secret در response یا audit دیده نشود.

---

## فاز 3 — اعمال branding در Odoo و React

### هدف

تنظیمات ذخیره‌شده واقعاً در محیط دیده شوند.

### کارها

1. حذف hard-code برند از shell تا حد ممکن.
2. اضافه‌کردن brand bootstrap پس از login.
3. اعمال CSS variables از پاسخ safe branding.
4. اعمال document title.
5. اعمال brand name در sidebar.
6. اعمال logo در sidebar و login surface.
7. اعمال favicon.
8. اعمال tagline و support link.
9. fallback امن در صورت نبود brand.
10. محدودسازی font family به whitelist.
11. اضافه‌کردن version برای invalidation cache.
12. تکمیل QWeb debrand برای Odoo login/backend.
13. جلوگیری از تغییر رنگ alertهای امنیتی به رنگ‌های غیرقابل تشخیص.

### قواعد UX

- رنگ‌های danger/warning نباید توسط مشتری به رنگ نامشخص تبدیل شوند.
- contrast حداقلی باید بررسی شود.
- preview باید desktop و mobile داشته باشد.
- تغییر brand باید بدون restart frontend قابل مشاهده باشد.
- تغییر branding نباید authorization یا policy را تغییر دهد.

### Gate خروج

- snapshot test برای CSS variables.
- تست login page.
- تست title/favicon.
- تست frontend build.
- تست contrast برای text/background.
- تست browser با brand جدید و fallback.
- تست company A و B روی clone جداگانه.

---

## فاز 4 — Customer Setup UI: هویت و برند

### هدف

ساخت اولین بخش عملیاتی Setup Center.

### UI پیشنهادی

تب یا route اصلی:

```text
/admin/setup
```

بخش‌ها:

1. خلاصه‌ی readiness.
2. مشخصات سازمان.
3. برند و ظاهر.
4. asset manager.
5. preview.
6. ذخیره‌ی draft.
7. apply.
8. reset.

### قابلیت‌ها

- فرم company profile.
- color picker همراه input hex.
- upload logo با preview.
- upload favicon با preview.
- حذف asset.
- نمایش version و last updated by.
- نمایش unsaved changes.
- confirm برای تغییرات حساس.
- نمایش نتیجه‌ی validation.
- دکمه‌ی `ذخیره پیش‌نویس`.
- دکمه‌ی `اعمال در appliance`.

### Gate خروج

- کاربر ادمین می‌تواند از صفر brand را تنظیم کند.
- refresh صفحه داده را درست برمی‌گرداند.
- logout/login تغییرات را حفظ می‌کند.
- تغییر company دیگر ممکن نیست.
- frontend build و accessibility smoke test سبز است.

---

## فاز 5 — Module Activation Center

### هدف

تبدیل Modules tab فعلی به setup-grade module center.

### کارها

1. حفظ catalog فعلی.
2. افزودن filter بر اساس category/state/readiness.
3. نمایش dependency با label انسانی.
4. نمایش install request و timestamp.
5. نمایش integration level.
6. نمایش agent connection.
7. نمایش capability count.
8. نمایش reviewed operation count.
9. افزودن detail drawer برای هر module.
10. افزودن readiness check پیش از install.
11. افزودن backup confirmation قبل از upgrade.
12. disable امن navigation/capability.
13. جلوگیری از uninstall مستقیم مگر بعد از طراحی migration/rollback.
14. نمایش warning برای moduleهای blocked.
15. refresh خودکار برای requestهای installing.

### رفتار خطا

- timeout مرورگر نباید به معنی failure قطعی فرض شود.
- retry باید idempotent باشد.
- partial batch باید واضح نمایش داده شود.
- نصب dependency fail باید durable ثبت شود.
- module نصب‌شده دوباره نصب نشود.

### Gate خروج

- install یک module روی clone واقعی.
- dependency failure.
- repeated click.
- browser close during install.
- refresh بعد از timeout.
- module state sync.
- audit trail.

---

## فاز 6 — Configuration Profile Designer

### هدف

قابل‌تنظیم‌کردن policyهای مشتری بدون ورود مستقیم به Odoo backend و بدون JSON خام برای کاربر عادی.

### صفحات

1. Profile list.
2. New profile.
3. Role policy.
4. Capability policy.
5. Approval matrix.
6. Document policy.
7. Agent policy.
8. Tool policy.
9. Workflow policy.
10. Validation results.
11. Version history.
12. Compile/activate.
13. Deployment dry-run.

### قواعد editor

- operationها از registry خوانده شوند، نه از browser input آزاد.
- toolها searchable و risk-labeled باشند.
- هر mutation توضیح و approval requirement داشته باشد.
- ابزار ناشناخته قابل انتخاب نباشد.
- capability ناسازگار با role reject شود.
- document scope با ACL native conflict نداشته باشد.
- policy compile قبل از activation اجباری باشد.

### lifecycle

```text
draft
→ validated
→ compiled
→ active
→ archived
```

اگر compile شکست خورد:

- active profile قبلی حفظ شود.
- profile جدید active نشود.
- خطا safe نمایش داده شود.
- جزئیات فنی در audit/admin log بماند.

### Gate خروج

- profile معتبر ساخته شود.
- profile ناسازگار reject شود.
- tool contract ناقص reject شود.
- active profile قبلی در failure حفظ شود.
- activation hash ثبت شود.
- rollback به نسخه‌ی قبلی موفق باشد.

---

## فاز 7 — Role، Access و Policy Setup

### هدف

یکپارچه‌کردن role و permission setup با profile و moduleها.

### کارها

1. role template picker.
2. user assignment.
3. department scope.
4. company scope.
5. temporary grant.
6. delegation.
7. expiry.
8. access review.
9. capability preview به‌ازای user.
10. diff قبل و بعد تغییر policy.
11. audit actor و reason.
12. export امن permission matrix.

### Gate خروج

- user مجاز capability درست دارد.
- user غیرمجاز هیچ document/chunk نتیجه نمی‌گیرد.
- delegation بعد از expiry بی‌اثر می‌شود.
- cross-company assignment رد می‌شود.
- تغییر role بدون audit ممکن نیست.

---

## فاز 8 — SSO، SCIM و operational integrations

### هدف

تکمیل setup سازمانی بدون ذخیره یا نمایش secret ناامن.

### کارها

1. provider list.
2. create/update provider.
3. protocol selection.
4. group mapping.
5. enforce SSO.
6. test connection.
7. SCIM token generation.
8. token revoke.
9. token expiry.
10. sync status.
11. last error.
12. user/group provisioning summary.
13. Telegram و integrationهای اختیاری در setup summary.

### قواعد

- secret بعد از save فقط masked باشد.
- endpoint عمومی secret را برنگرداند.
- test connection با timeout محدود باشد.
- SSO اشتباه نباید ادمین را lock out کند؛ break-glass path باید مستند و local باشد.
- SCIM sync failure نباید roleهای فعال فعلی را کورکورانه حذف کند.

### Gate خروج

- provider ساختگی و provider واقعی روی target test شود.
- bad credentials.
- timeout.
- group mapping conflict.
- SCIM duplicate.
- token revoke.
- emergency local login.

---

## فاز 9 — Setup Checklist و Deployment Wizard

### هدف

یک جریان واحد برای آماده‌سازی appliance مشتری.

### ترتیب wizard

```text
1. Appliance identity
2. Company profile
3. Branding
4. Module selection
5. Module installation
6. Module integration sync
7. Roles and permissions
8. Configuration profile
9. SSO/SCIM optional
10. RAG readiness
11. Runtime certification
12. Backup
13. Dry-run
14. Handoff report
15. Canary enablement
```

### قواعد wizard

- هر مرحله state durable دارد.
- خروج و ورود دوباره progress را حفظ می‌کند.
- skip فقط برای stageهای optional ممکن است.
- blocker باید remediation link داشته باشد.
- wizard نباید مستقیماً production activation را بدون gate انجام دهد.
- عملیات طولانی async و قابل پیگیری است.

### خروجی checklist

سه نمای مختلف:

1. operator view با جزئیات فنی.
2. customer admin view با پیام safe.
3. handoff report با خلاصه‌ی نسخه و وضعیت.

### Gate خروج

- wizard پس از refresh ادامه پیدا می‌کند.
- browser timeout باعث duplicate action نمی‌شود.
- failure در هر مرحله قابل retry است.
- active configuration قبلی خراب نمی‌شود.
- گزارش handoff قابل ذخیره و hashable است.

---

## فاز 10 — Observability، audit و support

### هدف

هر تغییر setup قابل پاسخ‌گویی و عیب‌یابی باشد.

### eventهای اجباری

- branding.created
- branding.updated
- branding.reset
- asset.uploaded
- asset.deleted
- company.profile.updated
- module.install.requested
- module.install.completed
- module.install.failed
- module.upgrade.requested
- module.disabled
- profile.created
- profile.validated
- profile.compiled
- profile.activated
- profile.archived
- setup.run.started
- setup.run.failed
- setup.run.passed
- handoff.report.generated

### هر audit event حداقل

- actor
- company
- timestamp
- action
- object type
- object opaque id
- result
- error class safe
- correlation id
- release commit

raw password، token، logo bytes و customer document content نباید وارد log شوند.

---

## فاز 11 — تست کامل

## 11.1 تست source/static

در هر milestone:

```bash
python3 -m unittest discover -s tests -q
python3 -m compileall -q custom_addons
bash 30_build_release.sh
```

همچنین:

- `git diff --check`
- release manifest verification
- frontend build
- npm audit
- pip dependency dry-run
- exhaustive source audit

## 11.2 تست backend unit

برای branding:

- valid/invalid hex
- empty values
- long values
- Unicode Persian
- invalid URL
- invalid email
- logo signature
- favicon signature
- max size
- company isolation
- permission denial
- version increment

برای profile:

- invalid JSON
- non-object JSON
- unknown tool
- inactive tool
- missing contract
- compile failure
- activate success
- previous active archive
- rollback

## 11.3 تست API integration

- admin GET/POST
- regular user branding GET
- unauthorized
- 403 non-admin
- CSRF contract
- repeated request
- timeout simulation
- stale browser response
- request replay
- idempotent install

## 11.4 تست frontend

- setup loads empty state
- setup loads existing company
- upload preview
- invalid file error
- dirty form guard
- save success
- save failure
- reset confirmation
- module install progress
- profile validation errors
- checklist blocker
- RTL layout
- mobile layout
- color contrast
- keyboard navigation

## 11.5 تست Odoo runtime

روی Odoo shell واقعی:

```bash
/opt/odoo/src/odoo/odoo-bin shell \
  -c /etc/odoo/odoo.conf \
  -d company_ai < 62_v58_module_certification.py
```

و:

```bash
/opt/odoo/src/odoo/odoo-bin shell \
  -c /etc/odoo/odoo.conf \
  -d company_ai < 48_auto_integration_certification.py
```

## 11.6 تست database migration

روی clone:

1. backup.
2. restore.
3. module upgrade.
4. count snapshot.
5. registry load.
6. profile migration.
7. branding migration.
8. asset read.
9. rollback restore.
10. second upgrade برای idempotency.

## 11.7 تست ACL/FGA

با userهای زیر:

- system admin
- executive
- security
- department manager
- regular user
- user بدون grant
- user company دیگر

هیچ user غیرمجاز نباید:

- branding company دیگر را بخواند.
- asset company دیگر را دانلود کند.
- profile company دیگر را ببیند.
- module request شرکت دیگر را مشاهده کند.
- document/chunk غیرمجاز را در retrieval ببیند.

## 11.8 failure injection

- worker kill
- PostgreSQL disconnect
- module install timeout
- profile compile exception
- asset upload interruption
- browser close
- duplicate click
- expired session
- redis failure در صورت استفاده
- embedding timeout

هدف مطلق:

```text
no data loss
no ACL leakage
no invalid active profile
no false PASS
```

---

# 6. ترتیب دقیق migration و release

## قبل از deploy

```bash
git status --short
git log -1 --oneline
sha256sum requirements.lock
```

سپس:

1. release artifact freeze.
2. DB backup.
3. restore test.
4. native dependency verification.
5. PostgreSQL extension verification.
6. stop workers.
7. deploy source.

## upgrade

```bash
export ODOO_DB=company_ai
export AI_MODULE_MODE=upgrade
./02_install_modules.sh
```

در runtime واقعی باید moduleهای جدید و dependencyها در update list باشند.

## post-upgrade

1. Odoo registry check.
2. branding migration check.
3. profile migration check.
4. module sync.
5. asset read check.
6. setup checklist.
7. integration certification.
8. RAG smoke test.
9. ACL smoke test.
10. backup reference ثبت.

## promotion

ترتیب promotion:

```text
source verified
→ database clone verified
→ runtime certification
→ setup checklist
→ internal test
→ customer-approved canary
→ handoff
```

هیچ مرحله‌ای با `--force` یا bypass gate رد نمی‌شود.

---

# 7. rollback plan

## Branding rollback

- بازگشت به version قبلی branding.
- حفظ asset قبلی تا پایان rollback window.
- invalidate frontend cache.
- restore title/colors/logo.

## Profile rollback

- active profile قبلی archive نشود تا profile جدید PASS شود.
- activate نسخه‌ی قبلی با hash قبلی.
- ثبت actor و reason.
- اجرای smoke test.

## Module rollback

- نصب موفق module به‌معنی uninstall فوری نیست.
- قبل از upgrade backup لازم است.
- disable navigation/capability از uninstall جداست.
- uninstall فقط با migration و compatibility test مجاز است.
- registry و agent binding بعد از rollback باید sync شوند.

## Database rollback

- توقف Odoo و worker.
- restore backup.
- verify registry.
- verify counts.
- run certification.
- start services.

---

# 8. Definition of Done نهایی

Customer Setup Center فقط وقتی complete تلقی می‌شود که همه‌ی موارد زیر برقرار باشند:

## Product

- admin از یک route واحد setup را انجام می‌دهد.
- brand preview دقیق است.
- logo/favicon در frontend و Odoo دیده می‌شوند.
- company profile ذخیره می‌شود.
- module activation و status واضح است.
- configuration profile بدون JSON خام برای کاربر عادی قابل تنظیم است.
- readiness checklist وجود دارد.
- handoff report تولید می‌شود.

## Security

- همه‌ی routeها privilege و company scope دارند.
- arbitrary RPC وجود ندارد.
- arbitrary ORM operation از frontend ممکن نیست.
- secret در UI/log برنمی‌گردد.
- asset upload محدود و validate شده است.
- ACL قبل از retrieval باقی است.
- cross-company access صفر است.

## Reliability

- mutationها durable هستند.
- retry idempotent است.
- partial failure قابل مشاهده است.
- active profile در failure حفظ می‌شود.
- module request audit دارد.
- rollback تمرین شده است.

## Runtime

- Odoo shell certification PASS.
- database clone migration PASS.
- native dependency check PASS.
- PostgreSQL extension check PASS.
- corpus smoke test PASS.
- ACL/citation certification PASS.
- benchmark target واقعی ثبت شده است.

تا قبل از این موارد، وضعیت محصول فقط یکی از این دو است:

```text
SOURCE_VERIFIED
RUNTIME_CERTIFICATION_REQUIRED
```

و نه `production-ready`.

---

# 9. ترتیب پیاده‌سازی در repository

برای کم‌کردن ریسک، تغییرات باید در commitهای کوچک انجام شوند:

## Commit 1 — data contract

- مدل branding
- مدل setup run
- security
- migration skeleton
- tests

## Commit 2 — branding API

- serializer
- admin endpoints
- public branding endpoint
- asset validation
- API tests

## Commit 3 — runtime application

- React branding bootstrap
- CSS variable application
- Odoo debrand integration
- frontend tests/build

## Commit 4 — setup identity UI

- company profile form
- branding editor
- asset preview
- save/reset/validation

## Commit 5 — module center

- readiness detail
- sync/upgrade/disable guard
- durable progress UI

## Commit 6 — profile API/UI

- profile CRUD
- structured policy editor
- compile/activate/dry-run

## Commit 7 — role/policy setup

- role assignment
- capability preview
- access review integration

## Commit 8 — SSO/SCIM setup

- provider UI
- mapping
- token lifecycle
- test connection

## Commit 9 — checklist/handoff

- setup checklist
- setup run persistence
- handoff report
- final readiness gate

## Commit 10 — runtime certification evidence

- migration evidence
- Odoo shell output
- ACL evidence
- corpus smoke evidence
- benchmark evidence

هر commit باید قبل از merge تست‌های همان مرحله را داشته باشد و نباید همه‌ی featureها در یک commit بزرگ پیاده شوند.

---

# 10. اولویت اجرایی نهایی

ترتیب کار از همین وضعیت:

```text
P0 — data model و source-of-truth
P0 — branding API و upload security
P0 — company-scoped permissions
P0 — React/Odoo branding application
P0 — setup identity UI
P0 — readiness checklist اولیه
P1 — module detail/upgrade/disable controls
P1 — configuration profile editor
P1 — compile/activate/dry-run UI
P1 — role/capability setup
P1 — handoff report
P2 — SSO/SCIM complete UI
P2 — richer previews and support tooling
P2 — advanced analytics
```

تا زمانی که P0 کامل نشده باشد، appliance نباید به‌عنوان customer-ready تحویل شود.

---

# 11. گام بعدی بلافاصله

اولین implementation step باید این باشد:

1. ایجاد مدل `ai.customer.branding` با migration و record rule.
2. ایجاد `ai.customer.setup.run`.
3. نوشتن تست company isolation و asset validation.
4. اجرای unittest و static audit.
5. سپس اضافه‌کردن API branding.

هیچ UI جدیدی قبل از تثبیت model و API contract ساخته نمی‌شود؛ این ترتیب جلوی ایجاد frontend ظاهراً زیبا اما بدون persistence، security و migration واقعی را می‌گیرد.
