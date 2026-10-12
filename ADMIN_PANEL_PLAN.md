# Admin Panel — Design Plan (v1)

> Status: IMPLEMENTED (see "Shipped in v1" at the bottom)
> Owner: platform. The Admin Panel is the CUSTOMER'S control room — a
> separate world from the employee workspace.

## 1. Mission

یک صفحهٔ مدیریتی مستقل برای «صاحب محصول»: اتصال موتور AI، مدیریت
ماژول‌های Odoo، کاربران و نقش‌ها، وضعیت سرویس‌ها و لاگ سیستم. کامل ایزوله
از پنل کارکنان (Nova workspace).

## 2. Isolation rules (hard requirements)

1. **دو دنیای جدا:** `/admin` یک اپ مجزاست — منوی خودش، layout خودش، هیچ
   nav مشترکی با پنل کارکنان ندارد.
2. **ورود فقط با username/password** (`admin`). هیچ SSO، کوکیِ پنل
   کارکنان، یا کلید پنل کارکنان به آن راه ندارد.
3. **کوکی ایزوله:** سشن ادمین با کوکی `aibox_admin_session` جدا
   (`HttpOnly`, `SameSite=Lax`, مسیر `/`) — هرگز با کوکی کارکنان
   (`ai_session`) تبادل نمی‌شود.
4. **هر API ادمین** فقط با سشن ادمین باز می‌شود (`_require_admin()`);
   بقیهٔ احرازها (کلید پنل کارکنان) در این روت‌ها **رد** می‌شوند.
5. Failure mode: بلاک شدن سشن → صفحهٔ لاگین ادمین، نه پنل کارکنان.

## 3. Information architecture (single page, 5 tabs)

| Tab | محتوا | Backend |
|---|---|---|
| **AI Engine** | انتخاب سرویس‌دهنده (OpenAI-compatible / DeepSeek / OpenAI / محلی)، Base URL، مدل Chat و Embedding، کلید API، دکمهٔ Test connection با نمایش نتیجهٔ واقعی، ذخیرهٔ امن (کلید فقط-write؛ نمایش ماسک‌شده) | GET/POST `/api/admin/panel/engine` + POST `/api/admin/panel/engine/test` |
| **Modules** | جدول ماژول‌های Odoo (نام، وضعیت، نسخه) + نصب/حذف/آپگرید با تأیید دومرحله‌ای و نشانگر پیشرفت | GET `/api/admin/panel/modules`، POST `/api/admin/panel/modules/act` |
| **Users & Roles** | فهرست کاربران داخلی (نام/لاگین/وضعیت)، تعویض رمز هر کاربر | GET `/api/admin/panel/users`، POST `/api/admin/panel/users/password` |
| **System health** | وضعیت سرویس‌ها: DB، Redis، موتور AI (ping واقعی به endpoint)، تعداد رکوردها، uptime | GET `/api/admin/panel/health` |
| **Logs** | آخرین رویدادهای audit (زمان، کاربر، عملیات، موفق/خطا) | GET `/api/admin/panel/logs` |

## 4. Visual language

- همان family طرح Nova (فونت/گوشه‌ها/انیمیشن‌های سبک) ولی **پنل متمایز**:
  هدر تیرهٔ باریک با برچسب «ADMIN PANEL» و نشان وضعیت سرویس‌ها، تب‌های
  افقی، کارت‌های استات-محور. کاربر معمولی هرگز این صفحه را نمی‌بیند
  (ورودی مستقل `/admin`، بدون لینک از پنل کارکنان).

## 5. Security model

- `POST /api/admin/panel/login {username, password}` → `admin/admin`
  credentials را با `res.users` چک می‌کند و **فقط** اگر `base.group_system`
  داشته باشد سشن ۸ ساعته صادر می‌کند.
- `POST /api/admin/panel/logout` → ابطال سشن.
- Rate-limit روی login (همان لیمیتر مشترک درگاه).
- هر فراخوانی tab → `_require_admin()` (کوکی مخصوص ادمین).
- کلیدهای موتور AI در `ir.config_parameter` با `sudo()` ذخیره می‌شوند و در
  پاسخ‌ها هرگز برنمی‌گردند (فقط ۴ کاراکتر آخر).

## 6. Shipped in v1

- سرویس Odoo جدید `ai.gateway.admin.panel` (مدل دیتایی سشن ادمین +
  متدهای engine/modules/users/health/logs).
- کنترلر `ai_gateway` با ۱۰ روت `/api/admin/panel/*` (همه `_require_admin`).
- اپ تک‌صفحه‌ای `/admin` — یک فایل `admin.html` مستقل با JS خودش
  (`admin.js`)، بدون وابستگی به باندل Nova؛ `docs/` هم همان را سرو می‌کند
  تا روی Pages هم `/aibox-odoo/admin.html` کار کند (دمو-مود وقتی بک‌اند
  نیست؛ بک‌اند وقتی `?api=` ست شده یا هم‌مبدأ است).
- ماژول‌ها: نصب/حذف با button box و پیام نتیجهٔ واقعی از Odoo.
- AI Engine: ذخیرهٔ provider/model/key و تست اتصال واقعی (chat + embedding
  endpoint) با نمایش پاسخ.
- تست خودکار: `tests/test_admin_panel.py` (login/logout/isolation/
  engine-save/test-connection/modules/health/logs/users).

## 7. Out of scope (v1.1+)

- ویرایش نقش‌ها (فعلاً فقط نمایش) · آپلود فایل ماژول · backup/restore ·
  2FA برای ادمین.
