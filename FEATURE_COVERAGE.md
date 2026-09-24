# FEATURE_COVERAGE — پوشش‌سنجی درخواست‌ها روی زیرساخت موجود

تاریخ: ۲۰۲۶-۰۸-۲۸ • درخت: v57 (release candidate) — به‌روزشدهٔ پایان فازهای ۲/۳ (این نسخه))

روش: برای هر ردیف، ابتدا بررسی شد که Odoo بومی یا ماژول‌های custom چه چیزی دارند؛ اگر موجود بود، بازسازی نشد. مواردی که در جلسهٔ جاری «ساخته/کامل/اصلاح» شدند، در هر ردیف با شاهد فایل جدید خورده شده‌اند.

وضعیت‌ها: ✅ پیاده‌شده (native یا custom موجود) • 🟡 ناقص (روی زیرساخت موجود، ولی یک شکاف مشخص) • 🔴 غایب (باید ساخته شود) • 📐 طراحی (فقط معماری، بدون اجرا — جایی که stack زنده در این محیط موجود نیست)

## الف) ردیف‌های جدول «خواسته → زیرساخت موجود»

| # | خواسته | زیرساخت موجود | وضعیت | شاهد (file:line) |
|---|--------|---------------|-------|-----------------|
| 1 | کاربران، کارمندان، نقش‌ها، مدیران، سازمان | `res.users` + `res.groups` + `hr.employee` + `hr.department` + قالب‌های نقش + ویزارد Excel | ✅ | `ai_business_tools/data/role_templates_data.xml:31-105`؛ `ai_customer_plane/wizard/excel_role_import.py`؛ `security/access_grant_role_rules.xml:6` |
| 2 | جابجایی کارمند / انتصاب نقش | ویزارد Excel (preview→approve→import) + `ai.customer.role.assignment` + `ai.customer.role.policy` | 🟡 | استخراج/ساخت فقط **create**؛ `excel_role_import.py:103-106` اگر کاربر موجود باشد import را block می‌کند؛ بدون صفحهٔ frontend (ویزارد Odoo). بدون تغییر در این جلسه. |
| 3 | اعمال Policy، مجوزها، Workflow | `ai.control.capability` + `ai.control.policy` + `ai.control.workflow` + `ai.workflow` + `ai.control.authorization` + `approval_matrix_data.xml` | ✅ | `ai_control_plane`، `ai_workflow`، `ai_integration/data/capability_data.xml` |
| 4 | اسناد، فایل، لینک‌منت، آپلود، مجوزها | `ir.attachment` (ستون `file` از نوع `Binary(attachment=True)`) + `ai_document_intelligence` + `ai_rag` + `/api/documents*` | ✅ | فاز ۲.۱۱: **دانلود/پیش‌نمایش بایت فایل برای اولین بار اضافه شد** — `GET /api/documents/<id>/file` در `ai_semantic_api/controllers/semantic_api.py` (`document_file`، همان record rule خواندن) + فیلد `url` در `_serialize_document`؛ فرانت مستقیماً با session لینک می‌زند |
| 5 | دانش سازمانی (RAG) | `ai_rag`: chunk/embed/vector + `search_documents_semantic` tool + risk row | ✅ | `ai_rag/data/tool_risk_data.xml:6` (منبع تک‌ریشه؛ ردیف تکراری در ai_business_tools در ۳.۳ حذف شد) |
| 6 | مکالمه، پروفایل، اعلان‌ها | `ai_collaboration` + Discuss (`mail.thread`/`mail.message`) + `mail/notification` + `bus.bus` | ✅ | `ai_collaboration`؛ `_run_chat` در `ai_gateway/controllers/gateway.py:183`؛ `task_automation.py` |
| 7 | ایمیل | `mail` بومی + `mail.message` + سرویس SMTP بومی | ✅ | (native؛ بدون کد custom لازم) |
| 8 | تقویم / رویداد / جلسه | `calendar.event` بومی + ابزار native جدید | ✅ | فاز ۲.۸: ابزار `schedule_meeting` (`ai_business_tools/models/calendar_tools.py`) → `calendar.event` واقعی با organizer=شریک کاربر و `partner_ids` شرکت‌کنندگان؛ risk row `risk_schedule_meeting` (R2)؛ هم‌رسانی ددلاین تسک/مرخصی از طریق `event_dispatch._handle_calendar` (فاز ۲.۶، organizer با `res.users→partner_id` درست شد) |
| 9 | تسک، مرخصی، اعلان، تشدید | `project.task` + `mail.activity` + `hr_holidays` + `task_automation.py` + دو cron تشدید | ✅ | فاز ۲.۱: `create_task` با `assignee_email`/`employee_code` و `_resolve_assignee_user` (کد کارمند → ایمیل → نام + ابهام سخت)؛ `fill_document_template` (۲.۴) و `send_personal_message` (۲.۲) روی همان resolver؛ escalate از `parent_id.user_id`/`department_id.manager_id.user_id` واقعی (۲.۹) |
| 10 | گزارش‌ها | QWeb/`ir.actions.report` — **اکنون ساخته شد** | ✅ | فاز ۲.۵: `ai_business_tools/reports/hr_directory_report.xml` (`report_hr_directory`، qweb-pdf روی hr.employee) + ابزار `generate_qweb_report` با allowlist (`_ALLOWED_REPORTS`) در `models/document_tools.py` |
| 11 | زمان‌بندی / اتوماسیون زمانی | `ir.cron` بومی + cron های موجود + **مدیریت rule بومی** | ✅ | فاز ۲.۷: `ai.schedule.rule` (mail.thread) که خودش ir.cron می‌سازد (`_ensure_cron` در create/write)؛ اجرا با `_run_chat_env` در env مالک + اعلان به فالوورها؛ ویو + `/api/schedules` و `/api/schedules/toggle` |
| 12 | تلگرام | `ai_telegram_bridge`: لینک/دریافت/تحلیل فایل و صدا/پیام‌های فارسی generic/سقف حجم | ✅ | فاز ۲.۱۰: **باگ relink-upsert رفع شد** — بوت‌پت وب‌هوک `/link` حالا روی ردیفِ همان user write می‌کند (unique(user_id) بود و بعد از self-unlink create می‌سوخت)؛ کاربر می‌تواند بدون ادمین چت را عوض کند |
| 13 | ACL / record rules / دفاع عمقی | ACL بومی + `ir.rule` سفارشی + `ai.gateway.tool.risk` (allowlist) + `execution gate` + context firewall + audit chain | ✅ | فاز ۳.۳: cross-check خودکار **۳۰ متد `@llm_tool` ↔ ۳۰ ردیف ریسک، ۰ بدون ردیف**؛ ردیف‌های تکراری حذف شدند؛ `tool_risk.py:5`؛ `execution_gate.py:41-43`؛ `context_firewall.py`؛ `audit_log.py:79` |
| 14 | Agent / مدل | `llm.assistant`/`provider`/`model` + `ai.model.router` + `company_ai_demo/data/llm_agent_data.xml` | ✅ | `llm_agent_data.xml:20-35`؛ `experience_api.py:303`؛ gateway.py:200-202 |
| 15 | Risk / تأیید انسانی | `ai.gateway.tool.risk` + `ai.gateway.execution.gate` + `ai.gateway.approval` + `approval_matrix_data.xml` | ✅ | فاز ۲.۲/۲.۸/۲.۴/۲.۵/۲.۷ ردیف‌های `send_personal_message` (R2)، `schedule_meeting` (R2)، `fill_document_template` (R1)، `generate_qweb_report` (R1)، `create_scheduled_command` (R2) اضافه شدند |
| 16 | کمپانی / چند-سازمان | `res.company` + `tenant_id` در audit و event | ✅ | `audit_log.py:46,75` |
| 17 | رویدادها / پیام‌رسان (bus) | `ai.control.event` + `event_dispatch.py` + `event_subscribers.py` + `bus.bus` | ✅ | فاز ۲.۶ در `_handle_calendar`؛ `ai_integration/models/event_dispatch.py` |
| 18 | Voice / صدا | تلگرام: faster-whisper (رفع‌شده، سقف حجم)؛ وب: فقط SpeechRecognition مرورگر | 🟡 | بدون تغییر در این جلسه؛ آپلود صوتی در وب همچنان بدون handler است — RUNTIME_CERTIFICATION_REQUIRED |
| 19 | چت وب (پورتال) | `ChatWorkspace` inline در App.jsx (زنده) — بدون streaming/thinking؛ `ChatPage.jsx` dead code | 🟡 | بدون تغییر در این جلسه؛ `frontend/src/App.jsx:49-52` |
| 20 | یکپارچگی ۱۶ ماژول + adapters | `adapter_data.xml` + `unified_operation_data.xml` (۱۵ آپریشن dot-named) | ✅* | فاز ۳.۳ اندازه‌گیری مجدد: **هر ۱۵ آپریشن یکپارچه ردیف ریسک dot-named ندارند** → `execution_contract` (unified_registry.py:262-265) همیشه رد می‌شود. این یعنی **سطح adapter عمداً deny-by-default است و هیچ surface مضاعفی باز نیست**؛ سطح محصول از ۳۰ ابزار native می‌آید که ۱۰۰٪ ریسک‌رجیستری دارند. (*تنش: این «بسته بودن» عمدی و امن است، بازسازی نشده — فعال‌سازی adapters در برابر ابزارهای native تکراری بود) |

## ب) موارد «ساخت فقط اگر خالی» (جدول ۶ گانهٔ دستور)

| # | مورد | ارزیابی | وضعیت | تصمیم |
|---|------|---------|-------|-------|
| N1 | صفحهٔ چت streaming + thinking indicator + آپلود هر فایل + voice | چت فعلی non-stream 1-shot است | 🟡 | بدون تغییر در این جلسه (فاز ۲ stream نبود)؛ RUNTIME_CERTIFICATION_REQUIRED |
| N2 | گزارش مصرف توکن | فیلد/ثبت توکن بررسی نشده | 📐 | بدون تغییر در این جلسه |
| N3 | کارایی تاریخچهٔ چت (pagination/index) | پاسخ‌ها در `mail.message`؛ بدون pagination در API | 📐 | بدون تغییر در این جلسه |
| N4 | همزمانی / صف `/api/chat` + vLLM | `chat_queue` (فاز ۱.۲) با selftest 10/10؛ اجرای واقعی نیاز به stack زنده | 📐 | RUNTIME_CERTIFICATION_REQUIRED |
| N5 | auto-discovery ماژول‌های تازه‌نصب | فقط `/api/bootstrap` ماژول‌ها را می‌خواند | 🟡 | بدون تغییر در این جلسه |
| N6 | web_search / ddgs واقعاً در دسترس | `search_internet` + risk `risk_search_internet` (R0) + `ddgs==8.1.0` پین‌شده | ✅ | `company_ai_demo/models/web_search.py:13`؛ `ai_business_tools/data/tool_risk_data.xml`؛ `requirements.lock` |

## پ) قوانین سخت — وضعیت گقتار user-facing

| قانون | وضعیت | شاهد |
|-------|-------|------|
| هیچ نام «Odoo»/مدل/جدول/اندپوینت/دیتابیس در پاسخ AI | ✅ | `llm_agent_data.xml:28` قانون ۱۳ (فارسی، «قانون سکوت، نه دروغ») + `:29` footer انگلیسی — تأیید در ۳.۱ |
| خطای user-facing بدون جزئیات داخلی | ✅ | فاز ۳.۲: ۱۰ نقطهٔ نشت exception متن‌خام به سطح LLM/کاربر بسته شد (rag_tool، web_search، vision_analysis، leave_request، file_reader، agent_memory، artifact_tools، hr_leave_tools/task_tools/company_document (access_denied)، workflow.dead_letter)؛ جزئیات فقط در `_audit(error_message=str(exc))` و log؛ HTTP/telegram ها از قبل تمیز بودند و `experience_api.py:310-312` هم قبلاً generic شده بود |
| WRITE فقط از طریق adapters / ابزارهای نام‌دار | ✅ | `model_policy.py` (explicit allowlist) + `execution_gate.py` deny-by-default؛ `/api/rpc` tombstone 410؛ سطح adapter نیز deny-by-default (ردیف ۲۰) |
| دسترسی داده با ACL/record rules | ✅ | رکورد رول‌ها + ir.rule در `ai_business_tools/security/` |

## خلاصه

- ✅ پیاده/کامل‌شده: ردیف‌های ۱، ۳–۱۷، ۲۰ (سطح native) + N6 — از جمله رفع شکاف‌های حساب‌دار این درخت: تقویم (۸)، گزارش QWeb بومی (۱۰)، دانلود فایل (۴)، پیام/مکالمه/جلسه/قالب‌ساز/زمان‌بند (۲.۲–۲.۸)، تلگرام relink (۲.۱۰)، ۳۰/۳۰ ریسک ابزار (۳.۳) و نشت‌های exception (۳.۲).
- 🟡 ناقص (بدون تغییر این جلسه): ردیف‌های ۲، ۱۸، ۱۹ + N1، N5.
- 📐 طراحی فقط: N2، N3، N4.

ترتیبِ کیفیتِ این جلسه: فاز ۲ (۱۱ قابلیت، همه روی زیرساخت native) → فاز ۳ (debrand / نشت exception / سخت‌گیری دسترسی) → فاز ۴ (یکپارچگی: 201 فایل Python AST-OK، 58 فایل XML-OK، بازتولید `SHA256MANIFEST.json` با ۳۹۲ ورودی) → فاز ۵ (گزارش تکمیل).

## موارد نیازمند RUNTIME_CERTIFICATION (قابل اجرا فقط با stack زنده)

اجرای واقعی ir.cron های `cron_ai_channel_mentions` (۲.۳) و `ai.schedule.rule` (۲.۷)، رندر QWeb-PDF (۲.۵)، رندر python-docx داخل Odoo (۲.۴)، برقراری اتصال تلگرام upsert (۲.۱۰)، download بایت از record rule (۲.۱۱)، و چرخهٔ buzz opt-in واقعی در Discuss — همه کد کامل و تست pure-python شده‌اند ولی این محیط استک زنده ندارد.