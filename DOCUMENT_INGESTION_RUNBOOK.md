# Local document ingestion and RAG runbook

این سند قرارداد عملیاتی ingestion محلی برای appliance مستقل Odoo است. مسیر
پردازش فایل، parsing، OCR، embedding و retrieval روی همان appliance اجرا می‌شود؛
هیچ فایل مشتری برای parsing، embedding یا inference به cloud ارسال نمی‌شود.

## مسیر پردازش

```text
upload/chat attachment
        │
        ▼
shared file policy
(extension, signature, MIME, ZIP safety, size, JSON/text)
        │
        ▼
canonical extractor
  1. Docling structured parser
  2. Unstructured local fallback
  3. bounded local DOCX/XLSX/PPTX/PDF adapters
  4. RapidOCR/PyMuPDF for local OCR/PDF text
        │
        ▼
canonical blocks + provenance + SHA-256
        │
        ▼
Persian normalization for lexical search only
        │
        ▼
chunk + local embedding + pgvector
        │
        ▼
ACL-bounded hybrid retrieval
(vector + simple FTS + pg_trgm)
```

`content` اصلی برای citation دست‌نخورده می‌ماند و فقط
`normalized_content` برای lexical search ساخته می‌شود.

## قالب‌های فعال

| قالب | مسیر اصلی | fallback محلی | provenance معمول |
|---|---|---|---|
| TXT/MD/CSV/JSON/HTML | parser داخلی bounded | — | نوع محتوا |
| PDF | Docling | PyMuPDF و سپس RapidOCR صفحه‌ای | page، coordinates تا حد parser |
| DOCX | Docling | python-docx / Unstructured | section، table، page تا حد parser |
| XLSX | Docling | openpyxl | sheet، table |
| PPTX | Docling | python-pptx | slide، coordinates |
| PNG/JPEG/TIFF/WEBP/BMP | RapidOCR | Docling OCR backend | OCR type، page در PDF |

Legacy Office، macro-enabled Office، archive مستقل، audio/video و executable عمداً
در policy فعال نیستند تا parser و quarantine جداگانه روی corpus واقعی تأیید شود.

## حفاظت از local/on-prem بودن

- `document_extractor.py` قبل از import تنبل Unstructured،
  `DO_NOT_TRACK=1` و `SCARF_NO_ANALYTICS=1` را اعمال می‌کند.
- Unstructured در صورت نبود `en_core_web_sm` اجازه self-download از GitHub ندارد؛
  در این حالت fallbackهای local اجرا می‌شوند.
- `unstructured[all-docs]` عمداً نصب نمی‌شود، چون نسخه فعلی آن inference stack
  سنگین torch/transformers را وارد venv می‌کند. PDF/image در مسیر محلی Docling،
  PyMuPDF و RapidOCR پوشش داده می‌شوند.
- مدل‌های embedding و inference باید از قبل روی appliance و با revision ثابت
  نصب شوند؛ هیچ endpoint ابری در extractor وجود ندارد.

## حدود و quotaهای پردازش

| مورد | مقدار پیش‌فرض |
|---|---:|
| Document Center upload | 25 MiB (`AI_MAX_UPLOAD_BYTES`) |
| Chat attachment | 50 MiB (`AI_MAX_CHAT_UPLOAD_BYTES`) |
| مجموع حجم unpack شده ZIP | 100 MiB (`AI_MAX_UNPACKED_BYTES`) |
| متن استخراج‌شده | 2,000,000 کاراکتر |
| تعداد blockها | 100,000 |
| تعداد pageهای OCR PDF | 500 |
| تعداد rowهای CSV/XLSX | 100,000 |
| query retrieval | 8,000 کاراکتر |
| top-k retrieval | حداکثر 50 |
| authorized document scope | پیش‌فرض 50,000 |

این quotaها safety boundary هستند، نه ظرفیت تضمین‌شده production.

## وضعیت durable ingestion

```text
pending → extracting → embedding → indexed
                         ├────────→ empty
                         └────────→ failed
```

- checksum فایل، parser/version، تعداد page، تعداد کاراکتر و خطا ذخیره می‌شوند.
- worker برای هر job savepoint دارد؛ خطای parser/embedding نباید transaction کل
  worker را خراب کند.
- lease منقضی‌شده requeue می‌شود و پس از retry budget برای بررسی operator باقی
  می‌ماند.
- Document Center تا وقتی job فعال است هر سه ثانیه status را refresh می‌کند.
- owner یا administrator می‌تواند job ناموفق را از دکمه «تلاش مجدد» دوباره queue کند.
- API عمداً متن خطای داخلی را عمومی نمی‌کند؛ خطای durable در Odoo باقی می‌ماند.

## Citation و ACL

هر chunk می‌تواند این anchorها را برگرداند:

- page
- section
- parser block type
- coordinates
- table
- spreadsheet sheet
- presentation slide

ترتیب امنیتی retrieval تغییرناپذیر است: ابتدا ORM/FGA/record-rule با company و
scope محدود، بعد query خام vector/FTS/trigram فقط روی `allowed_doc_ids`. بنابراین
vendor parser یا pgvector جایگزین authorization مرکزی نیست.

## نصب native

```bash
INSTALL_OS_DEPS=1 ./01_setup_base.sh
AI_MODULE_MODE=upgrade ODOO_DB=company_ai ./02_install_modules.sh
AI_GATEWAY_ENV=production ./03_start_all.sh
```

بسته‌های native مربوط به این مسیر شامل `libmagic`, `libgl1`, `libglib2.0-0`,
Poppler، Tesseract با زبان‌های `eng/ara/fas`، LibreOffice، Pandoc و Noto fonts
هستند. Docker در این deployment path وجود ندارد.

## validation فعلی

این‌ها روی checkout قابل اجرا و تکرار هستند:

```bash
python3 -m unittest discover -s tests -v
python3 -m pip install --dry-run --ignore-installed \
  --break-system-packages -r requirements.lock
bash 30_build_release.sh
```

در validation این release، suite قرارداد ۳۲ تست، source audit با ۹۴ check،
frontend build و npm audit بدون vulnerability موفق شدند. یک venv موقت نیز
Docling، Unstructured، PyMuPDF و fallbackهای DOCX/XLSX/PPTX را روی فایل مصنوعی
فارسی اجرا کرد.

### مواردی که هنوز certification واقعی می‌خواهند

- Odoo registry/module upgrade و اجرای migration روی PostgreSQL واقعی
- نصب و import RapidOCR پس از نصب native `libgl1` روی target appliance
- pgvector/pg_trgm extension و index creation روی نسخه PostgreSQL هدف
- ACL/FGA retrieval با چند user و چند company واقعی
- corpus benchmark فارسی مشتری و بررسی table/sheet/slide citation
- latency، memory، rollback و ظرفیت concurrent روی DGX GB10

تا اجرای این موارد، عبارت‌های production-ready، کیفیت قطعی فارسی و ظرفیت ۱۰۰
درخواست هم‌زمان نباید استفاده شوند.
