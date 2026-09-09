# راهنمای دیدن و کار با محصول — نسخهٔ شهریور ۱۴۰۵

این سند سه سؤال را دقیق جواب می‌دهد:

1. محصول کجا **اجرا** می‌شود و چطور بالا بیاوریمش؟
2. LLM لوکال چطور با **API** جایگزین شد و چطور هر API دیگری بگذاریم؟
3. لینک GitHub Pages چیست، چه کاری می‌کند و چه کاری **نمی‌تواند** بکند؟

---

## ۱. اجرای کامل محصول

### الف) روی همین محیط (بدون Docker، بدون apt، بدون root)

`install_aibox_onefile.sh` برای ماشین‌هایی است که Docker و systemd دارند. برای
ماشین محدود، `sandbox/aibox_local.sh` اضافه شد:

```bash
sandbox/aibox_local.sh install   # یک‌بار: venv، وابستگی‌ها، Postgres، دیتابیس، ماژول‌ها
sandbox/aibox_local.sh demo      # دادهٔ دمو (۶ دپارتمان، ۱۴ کاربر، مرخصی، وظیفه، سند)
sandbox/aibox_local.sh seed      # اعمال پیکربندی LLM API
sandbox/aibox_local.sh start     # postgres + redis + LLM + odoo + frontend
sandbox/aibox_local.sh status    # چه چیزی بالا است و چه جوابی می‌دهد
```

چهار نکتهٔ فنی که این اسکریپت حل می‌کند و در مسیر دستی به آن‌ها می‌خوری:

| مانع | راه‌حل |
|---|---|
| PostgreSQL نصب نیست و apt هم کار نمی‌کند | پکیج `pgserver` روی PyPI باینری واقعی PostgreSQL 16.2 را **داخل wheel** دارد؛ بدون دانلود در زمان نصب |
| Odoo 18 بدون `pg_trgm` بالا نمی‌آید (`extension "pg_trgm" is not available`) و آن wheel فقط `plpgsql` و `vector` دارد | `pg_trgm` و `unaccent` از تگ `REL_16_2` مخزن `postgres/postgres` با **pgxs خود همان wheel** کامپایل می‌شوند |
| Redis نیست، و gateway بدون Redis عمداً **همه‌چیز را بلاک می‌کند** (`allow()` مقدار `False` برمی‌گرداند → HTTP 429 روی اولین تلاش لاگین) | پکیج `redislite` باینری واقعی `redis-server` دارد؛ مستقیم با `--port 16379` اجرا می‌شود |
| `psycopg2` و `python-ldap` از سورس بیلد نمی‌شوند | `psycopg2-binary` جدا نصب می‌شود؛ `python-ldap` فقط برای `auth_ldap` لازم است و حذف می‌شود |

نتیجهٔ واقعی روی همین محیط:

```
extension vector   -> 0.6.2
extension pg_trgm  -> 1.6
extension unaccent -> 1.1
124 ماژول نصب‌شده · 0 خطای CRITICAL/Traceback
```

> ⚠️ `pgvector` موجود در آن wheel نسخهٔ **0.6.2** است. خود README (خطوط ۷۶۰–۷۷۰)
> می‌گوید نسخه‌های 0.6.0 تا 0.8.1 باگ HNSW دارند و باید 0.8.2+ باشد. برای دمو
> قابل قبول است؛ برای پروداکشن pgvector را ارتقا بده.

### ب) روی سرور خودت (مسیر اصلی محصول)

```bash
curl -fsSL https://raw.githubusercontent.com/soheilsss-coder/aibox-odoo/<branch>/install_aibox_onefile.sh \
  | bash -s -- install
./install_aibox_onefile.sh serve-odoo https://assistant.example.com
```

---

## ۲. جایگزینی LLM لوکال با API

### چه چیزی عوض شد

هیچ خطی از gateway عوض نشده. `llm.provider` همان رکورد است؛ فقط به‌جای
`http://127.0.0.1:8000/v1` حالا آدرس و کلید خارجی نگه می‌دارد. سه فایل جدید:

| فایل | کار |
|---|---|
| `runtime_workers/llm_api_config.py` | تشخیص خودکار ارائه‌دهنده + نرمال‌سازی آدرس (کتابخانهٔ خالص، بدون Odoo) |
| `runtime_workers/seed_api_inference.py` | seed هم‌توان (idempotent) که رکوردهای Odoo را از روی environment می‌سازد |
| `runtime_workers/verify_llm_api.py` | تست end-to-end با **چاپ کامل خروجی خام** |
| `runtime_workers/mock_llm_server.py` | سرویس OpenAI-compatible آفلاین برای تست بدون دسترسی شبکه |
| `tests/test_llm_api_config.py` | ۲۷ تست قرارداد روی لایهٔ تشخیص |

### «خودش تشخیص بده و من هر API بگذارم»

کافی است آدرس را بدهی؛ ارائه‌دهنده از روی hostname تشخیص داده می‌شود:

```bash
export AI_LLM_API_BASE=https://api.openai.com/v1
export AI_LLM_API_KEY=sk-...
# مدل اختیاری است؛ اگر ندهی، پیش‌فرض همان ارائه‌دهنده انتخاب می‌شود
export AI_LLM_MODEL=gpt-4.1-mini
```

ترتیب اولویت: `AI_LLM_PROVIDER` صریح ← hostname شناخته‌شده ← الگوی نام مدل ←
loopback ← حالت سازگار با OpenAI.

آدرس‌هایی که تشخیص داده می‌شوند: OpenAI، Gemini، Groq، OpenRouter، Anthropic،
Mistral، DeepSeek، xAI، DeepInfra، Together، و هر endpoint سازگار با OpenAI
(vLLM، Ollama، LM Studio، پروکسی داخلی).

نرمال‌سازی آدرس هم انجام می‌شود، چون در عمل همهٔ این‌ها paste می‌شوند:

```
https://api.openai.com                      → https://api.openai.com/v1
https://api.openai.com/v1/chat/completions  → https://api.openai.com/v1
api.openai.com/v1                           → https://api.openai.com/v1
https://generativelanguage.googleapis.com/v1beta
   → https://generativelanguage.googleapis.com/v1beta/openai   (وگرنه 404)
```

### Embedding جدا است — و این عمدی است

Groq و OpenRouter اصلاً `/v1/embeddings` ندارند. اگر یک آدرس برای هر دو
استفاده شود، RAG **در زمان ایندکس** می‌شکند نه در زمان نصب — بدترین جا برای
فهمیدنش. پس:

```bash
export AI_EMBEDDING_API_BASE=https://api.openai.com/v1
export AI_EMBEDDING_MODEL=text-embedding-3-small
export AI_EMBEDDING_DIM=1536
```

اگر نگذاری، به endpoint لوکال قدیمی (`127.0.0.1:8002/v1`) برمی‌گردد و در
خروجی seed هم هشدار می‌دهد.

### اعمال و تست

```bash
python odoo-bin shell -c odoo.conf -d <db> --no-http < runtime_workers/seed_api_inference.py
python runtime_workers/verify_llm_api.py --verbose
```

`verify_llm_api.py` چهار چیز را چک می‌کند و **خروجی خام** هرکدام را چاپ می‌کند:
`/v1/models`، چت غیرجریانی، چت جریانی (SSE با زمان اولین توکن)، و embedding
(همراه با بررسی بعد بردار در برابر `AI_EMBEDDING_DIM`).

کلید **هرگز** چاپ نمی‌شود — فقط اثر `mock...7890`.

### seed چه کارهایی امن انجام می‌دهد

- provider/model لوکال قدیمی را **غیرفعال** می‌کند، حذف نمی‌کند (قابل rollback)
- کلید ذخیره‌شده در UI را فقط وقتی بازنویسی می‌کند که environment واقعاً کلید داشته باشد
- پروفایل‌های `ai.model.profile` را `production=True` و `health_state=healthy` می‌کند؛ وگرنه روتر پروداکشن آن‌ها را نمی‌بیند

---

## ۳. لینک GitHub Pages

### وضعیت فعلی — دقیق

`https://soheilsss-coder.github.io/aibox-odoo/` الان **404** می‌دهد:
«There isn't a GitHub Pages site here.» یعنی Pages روی این مخزن **هرگز فعال نشده**.

### یک قدم که فقط تو می‌توانی برداری (۳۰ ثانیه)

توکنی که در sandbox هست فقط به این مخزن دسترسی دارد و API تغییر تنظیمات Pages
را `403 Resource not accessible by integration` برمی‌گرداند. پس:

1. مخزن → **Settings** → **Pages**
2. «Build and deployment» → Source → **GitHub Actions**
3. تب **Actions** → «Publish to GitHub Pages» → **Run workflow**

### یک قدم دیگر: فایل workflow باید دستی جابه‌جا شود

push کردن `.github/workflows/pages.yml` از این محیط **رد شد**:

```
! [remote rejected] (refusing to allow a GitHub App to create or update
   workflow `.github/workflows/pages.yml` without `workflows` permission)
```

یعنی GitHub App این محیط اجازهٔ `workflows` ندارد (توکنی که دادی هم به دست
GitHub نمی‌رسد — لایهٔ شبکهٔ sandbox اعتبارنامهٔ خودش را جایگزین می‌کند؛ با یک
توکن عمداً غلط هم همان `200` برمی‌گشت). پس workflow به‌صورت **قالب** در
`docs/pages-workflow.yml` commit شده. برای فعال‌سازی:

```bash
mkdir -p .github/workflows
cp docs/pages-workflow.yml .github/workflows/pages.yml
git add .github/workflows/pages.yml
git commit -m "Enable GitHub Pages deployment"
git push
```

یا در Settings → Actions → General → Workflow permissions به اپ
`Workflows: Read and write` بده تا مستقیم commit شود.

بعد از آن:

| آدرس | محتوا |
|---|---|
| `https://soheilsss-coder.github.io/aibox-odoo/` | صفحهٔ فرود + جعبهٔ «اتصال به بک‌اند» |
| `https://soheilsss-coder.github.io/aibox-odoo/app/` | **خود محصول** (React) |

### چه چیزی روی Pages اجرا می‌شود و چه چیزی نه

GitHub Pages فقط فایل **ثابت** سرو می‌کند. Odoo یک سرویس پایتون با PostgreSQL
است و روی Pages قابل اجرا نیست — با هیچ workflow ای. پس:

- ✅ رابط کاربری کامل محصول روی Pages
- ✅ داده‌ها، LLM، ACL، ممیزی، RAG روی appliance خودت
- ❌ اجرای بک‌اند روی Pages

برای اینکه Pages به appliance روی دامنهٔ دیگر وصل شود، در Odoo:

```bash
export AI_GATEWAY_ALLOWED_ORIGIN=https://soheilsss-coder.github.io
export AI_GATEWAY_COOKIE_SECURE=1
export AI_GATEWAY_COOKIE_SAMESITE=None   # نیازمند HTTPS روی بک‌اند
```

> مخزن **private** است. Pages روی مخزن خصوصی به GitHub Pro/Team/Enterprise نیاز
> دارد. روی اکانت رایگان با مخزن خصوصی، یا فرانت را از یک مخزن عمومی منتشر کن
> یا از reverse proxy خود appliance استفاده کن.

---

## ورود به محصول

`04_seed_demo_data.py` چهارده کاربر با نقش‌های مختلف می‌سازد. رمز همه‌شان در
محیط تست روی `Demo1234!` تنظیم شده:

```
admin                              Administrator
demo.ceo@yourbrand.example         سارا احمدی — مدیرعامل
demo.hr.manager@yourbrand.example  مریم رضایی — مدیر منابع انسانی
demo.finance.manager@...           علی محمدی — مدیر مالی
demo.warehouse.manager@...         رضا قاسمی — مدیر انبار
demo.pm@yourbrand.example          فاطمه صادقی — مدیر پروژه
demo.security@yourbrand.example    بهروز طاهری — مسئول امنیت
```

---

## چیزی که در این سند **ادعا نشده**

- هیچ عدد latency یا ظرفیت پروداکشن اندازه‌گیری نشده.
- تماس واقعی با `api.openai.com` و بقیه از این sandbox ممکن **نیست**: خروجی
  شبکه محدود است و `curl` خطای `SSL_ERROR_SYSCALL` می‌دهد. پس مسیر LLM با یک
  سرویس سازگار با قرارداد OpenAI تست شد — همان shape درخواست و پاسخ، همان
  مسیر کد. تعویض `AI_LLM_API_BASE` به یک ارائه‌دهندهٔ واقعی هیچ خط کدی را
  عوض نمی‌کند، ولی **اولین تماس واقعی باید روی ماشین تو تأیید شود**:
  `python runtime_workers/verify_llm_api.py --verbose`
