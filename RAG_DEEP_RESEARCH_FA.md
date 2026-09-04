# بررسی عمیق RAG، سرعت و پذیرش فایل

**تاریخ:** 2026-09-04  
**وضعیت:** research و audit سورس؛ هیچ parser، package یا service جدیدی در این مرحله نصب نشده است.

## 1. پاسخ مستقیم دربارهٔ سرعت

**نه؛ فعلاً نمی‌شود صادقانه گفت inference خیلی سریع است و هر درخواست را بدون مشکل انجام می‌دهد.** چیزی که تا امروز تأیید شده، بیشتر hardening مسیر queue و کنترل ظرفیت است، نه سرعت واقعی مدل روی appliance مشتری.

آنچه واقعاً evidence دارد:

- queue self-test برای burst صد درخواست: همهٔ درخواست‌های قابل‌قبول admit و drain شده‌اند؛
- pool و Redis lease برای جلوگیری از job تکراری و stuck شدن وجود دارد؛
- embedding batch و cache محدود شده‌اند؛
- RAG indexing از transaction چت جدا و asynchronous شده است.

آنچه هنوز **تأیید نشده**:

- p50/p95/p99 زمان پاسخ chat روی vLLM واقعی؛
- TTFT، TPOT و end-to-end latency با مدل و context واقعی؛
- سرعت extraction/OCR فارسی؛
- latency و memory reranker؛
- ظرفیت واقعی 100 inference هم‌زمان روی DGX GB10؛
- رفتار هم‌زمان chat، embedding، vision و RAG worker؛
- restore/index rebuild در corpus واقعی.

بنابراین «۱۰۰ درخواست در queue پذیرفته می‌شود» با «۱۰۰ پاسخ سریع و هم‌زمان تولید می‌شود» یکی نیست. تا benchmark روی DGX و سرویس‌های واقعی اجرا نشود، ادعای سرعت بالا یا بدون مشکل بودن مجاز نیست.

---

## 2. وضعیت فعلی RAG در سورس

مسیر فعلی به‌صورت خلاصه چنین است:

```text
company.document
  -> event bus
  -> ai.document.index.job
  -> Unstructured partition.auto
  -> RapidOCR fallback برای image/scanned PDF
  -> chunker مشترک
  -> local vLLM embedding
  -> PostgreSQL/pgvector

query
  -> Odoo record rule + FGA/grant pre-filter
  -> vector candidate scan
  -> PostgreSQL FTS candidate scan
  -> hybrid score
  -> result با excerpt
```

نقاط قوت فعلی:

- ACL/FGA پیش از candidate generation انجام می‌شود؛
- raw SQL vector search روی documentهای قابل‌مشاهده محدود می‌شود؛
- embeddingها batch می‌شوند؛
- index job durable است و از `FOR UPDATE SKIP LOCKED` استفاده می‌کند؛
- snapshot باعث می‌شود revision ناقص به کاربر سرو نشود؛
- embedding dimension، مدل و revision اعتبارسنجی می‌شوند؛
- context firewall پیش از embedding و پیش از خروجی اعمال می‌شود؛
- hybrid retrieval فقط semantic نیست و lexical fallback دارد.

---

## 3. آیا هر فایلی را می‌پذیرد؟ جواب کوتاه: خیر

در این سیستم سه مسیر مختلف وجود دارد و allowlist آن‌ها یکسان نیست. این خودش یکی از مهم‌ترین findings این audit است.

### 3.1 آپلود از Document Center و `/api/documents`

این مسیر از `validate_upload` استفاده می‌کند و به‌صورت پیش‌فرض حداکثر **25 MiB** را قبول می‌کند (`AI_MAX_UPLOAD_BYTES`). فرمت‌های مجاز فعلی:

```text
.txt  .md  .csv  .json
.pdf  .docx  .xlsx  .xls  .pptx
.png  .jpg  .jpeg  .webp
```

کنترل‌های فعلی:

- PDF باید با `%PDF-` شروع شود؛
- PNG/JPEG/WEBP magic bytes بررسی می‌شود؛
- DOCX/XLSX/PPTX باید ZIP معتبر Office Open XML با فایل‌های اصلی مورد انتظار باشند؛
- مسیرهای خطرناک، symlink و unpacked size بالاتر از **100 MiB** در Office ZIP رد می‌شود؛
- XLS باید OLE signature داشته باشد؛
- TXT/MD/CSV/JSON باید UTF-8 و فاقد null byte ابتدایی باشند.

اما این کنترل‌ها هنوز ثابت نمی‌کنند که **محتوا برای RAG قابل استخراج است**. به‌طور مشخص:

- JSON فقط از نظر UTF-8 بررسی می‌شود و JSON syntax validate نمی‌شود؛
- CSV از نظر delimiter، encoding، تعداد ستون و row limit validate نمی‌شود؛
- PDF رمزدار یا خراب status تخصصی ندارد؛
- DOCX/XLSX/PPTX با رمز یا فایل داخلی آسیب‌دیده ممکن است بعداً در parser fail شوند؛
- HTML، DOC، PPT، BMP، TIFF، ODT، EML، EPUB، RTF و XML در این API رد می‌شوند؛
- `.docm`، `.xlsm` و `.pptm` عمداً در allowlist نیستند که تصمیم خوبی برای macro safety است؛
- archive، executable، CAD، audio و video پذیرفته نمی‌شوند.

### 3.2 attachment در چت

`llm.thread` allowlist جداگانه و وسیع‌تری دارد:

```text
.pdf .docx .doc .xlsx .xls .pptx .ppt
.csv .txt .html .htm
.jpg .jpeg .png .webp .bmp .tiff .tif
```

این مسیر حداکثر **50 MiB** را در `file_reader.py` کنترل می‌کند و از Unstructured استفاده می‌کند؛ در PDF کم‌متن به OCR صفحه‌به‌صفحه fallback می‌کند.

تفاوت‌های مشکل‌ساز با Document Center:

- `.html` در چت مجاز است ولی در persistent Document Center مجاز نیست؛
- `.md` و `.json` در Document Center مجازند ولی در chat attachment allowlist نیستند؛
- `.doc`، `.ppt`، BMP و TIFF در chat ظاهراً مجازند ولی مسیر persistent API آن‌ها را رد می‌کند؛
- content signature و archive safety به‌اندازهٔ `validate_upload` در این مسیر یکسان enforce نمی‌شود؛
- `read_attached_file` فقط جدیدترین/اولین attachment انتخاب‌شده را می‌خواند و multi-file reasoning واقعی ندارد.

پس جملهٔ دقیق این است: **chat و RAG فعلی مجموعه‌ای از فایل‌های رایج را می‌پذیرند، نه هر فایل را؛ و allowlist دو مسیر باید بعداً یکی شود.**

### 3.3 ایجاد مستقیم `company.document` از ORM/import

در `_rag_extract_text`، فایل از نظر extension به‌صورت مرکزی allowlist نمی‌شود. کد تلاش می‌کند هر فایل غیرتصویری را با `unstructured.partition.auto` باز کند و در خطا job را fail می‌کند.

این یعنی اگر سند از import، `sudo()` یا مسیر دیگری مستقیماً ساخته شود، ممکن است فایلِ خارج از allowlist در DB ذخیره شود و تازه هنگام indexing شکست بخورد. برای محصول production بهتر است همان policy قبل از ذخیرهٔ فایل enforce شود، نه بعد از آن.

---

## 4. ماتریس عملی پذیرش و کیفیت

| نوع فایل | مسیر فعلی | نتیجهٔ واقعی فعلی | وضعیت پیشنهادی |
|---|---|---|---|
| TXT/MD | API و چت با تفاوت allowlist | معمولاً سریع و کم‌ریسک؛ UTF-8 لازم | Go |
| CSV | API و چت | قابل پذیرش، ولی structure/encoding/row limit کافی validate نمی‌شود | Go با extractor جدولی |
| JSON | API | upload قبول می‌شود، اما backend extraction برای JSON در dependency فعلی قطعی نیست | فقط پس از parser صریح JSON |
| PDF دیجیتال | API/چت | به dependencyهای Unstructured و کیفیت PDF وابسته؛ metadata/page از دست می‌رود | Docling pilot، سپس Go |
| PDF اسکن‌شده | API/چت | RapidOCR صفحه‌به‌صفحه fallback؛ آهسته‌تر و بدون provenance دقیق | Docling + PaddleOCR benchmark |
| DOCX | API/چت | به parser و extras نصب‌شده وابسته؛ جدول/heading فعلی flatten می‌شود | Docling canonical output |
| XLSX | API/چت | قابل upload؛ رابطهٔ sheet/row/cell در text flatten می‌شود | extractor sheet-aware |
| XLS قدیمی | API/چت | signature قبول می‌شود، extraction به dependency/LibreOffice وابسته | worker با LibreOffice یا رد شفاف |
| PPTX | API/چت | text قابل استخراج است، ترتیب layout و متن داخل image تضمین نیست | Docling + slide/page metadata |
| DOC/PPT قدیمی | فقط چت | Document Center رد می‌کند؛ مسیر parser نیازمند LibreOffice است | Tier B pilot |
| HTML | فقط چت | Unstructured می‌تواند parse کند، اما persistent API رد می‌کند | اگر نیاز محصول هست، با sanitization اضافه شود |
| PNG/JPEG/WEBP | API/چت | OCR عمومی؛ کیفیت به متن و زبان تصویر وابسته | Go با OCR زبان‌محور |
| BMP/TIFF | فقط چت | در chat allowlist است؛ persistent API رد می‌کند | یکسان‌سازی بعد از benchmark |
| ODT/ODS/ODP | هیچ مسیر رسمی API | Unstructured/Docling پشتیبانی دارند، ولی policy فعلی رد می‌کند | Tier B |
| EML/MSG/EPUB/RTF/XML | هیچ مسیر persistent فعلی | Unstructured پشتیبانی اعلام می‌کند، ولی dependency و policy کامل نیست | فقط با requirement واقعی |
| ZIP/RAR/7z | خیر | به‌درستی پیش‌فرض رد شده؛ خطر archive bomb و ACL inheritance | No-Go فعلی |
| EXE/SO/DLL/SCRIPT | خیر | باید همیشه رد شود | No-Go |
| PDF/Office رمزدار | upload ممکن است، extraction ممکن است fail شود | پیام/وضعیت تخصصی ندارد | reject با `encrypted_unsupported` |
| Audio/Video | خیر | transcription مسیر production ندارد | بعداً با worker جدا |

---

## 5. dependency واقعی فعلی یک gap مهم دارد

`requirements.lock` فقط `unstructured==0.16.3` را pin کرده و در comment نوشته که extras مربوط به `all-docs` باید همراه آن نصب شوند؛ اما installer فعلی این دستور را اجرا می‌کند:

```text
pip install -r requirements.lock
```

و به‌صورت صریح `unstructured[all-docs]` یا system dependencyهای کامل را نصب نمی‌کند. مستندات رسمی Unstructured برای بیشترین compatibility به این موارد اشاره می‌کند:

- `libmagic-dev` برای type detection؛
- `poppler-utils` و `tesseract-ocr`/language packs برای PDF و image؛
- `libreoffice` برای Microsoft Office؛
- `pandoc` برای EPUB/ODT/RTF.

منبع رسمی: [Unstructured supported file types](https://docs.unstructured.io/open-source/introduction/supported-file-types) و [Unstructured full installation](https://docs.unstructured.io/open-source/installation/full-installation).

پس در deployment واقعی باید یکی از این دو تصمیم صریح گرفته شود:

1. `unstructured[all-docs]` به‌صورت immutable و با همهٔ OS dependencyهای موردنیاز نصب و certification شود؛ یا
2. Unstructured فقط fallback محدود باشد و Docling worker با dependencyهای مشخص parser اصلی شود.

تا این کار انجام نشود، عبارت «DOCX/XLSX/PPTX/PDF پشتیبانی می‌شود» فقط intent معماری است، نه runtime guarantee.

---

## 6. گزینه‌های بهتر برای ingestion

### 6.1 Docling — انتخاب اول برای parser canonical

مستندات رسمی Docling فرمت‌های PDF، DOCX/XLSX/PPTX، legacy DOC/XLS/PPT با نیاز به LibreOffice، ODT/ODS/ODP، EPUB، Markdown، AsciiDoc، LaTeX، HTML، CSV، image، email و چند فرمت دیگر را فهرست می‌کند: [Docling supported formats](https://docling-project.github.io/docling/usage/supported_formats/).

مزیت اصلی برای RAG فعلی، فقط تعداد extension نیست؛ بلکه خروجی Docling Document می‌تواند heading، reading order، table، page provenance، layout و JSON/Markdown ساختاریافته را حفظ کند. مستندات همچنین JSONL chunk output را برای RAG دارد.

**Go مشروط:**

- worker native جدا با systemd؛
- output canonical قبل از chunking؛
- نگهداری page/section/table/bounding-box؛
- parser version و OCR engine version در metadata؛
- محدودیت page/time/memory؛
- fallback به Unstructured فقط برای formatهای certified نشده.

Docling فایل‌های legacy Office را با LibreOffice نیاز دارد؛ بنابراین برای `.doc/.xls/.ppt` یک LibreOffice headless worker لازم است، نه اینکه این فرمت‌ها بدون dependency ادعا شوند.

### 6.2 PaddleOCR — برای فارسی/عربی scanned

برای اسناد فارسی و عربی scanned، PaddleOCR/PP-OCRv5 نسبت به RapidOCR فعلی گزینهٔ benchmark جدی‌تری است. اما نباید آن را به‌تنهایی parser سند فرض کرد: OCR متن می‌دهد، در حالی که layout/table/provenance باید از Docling یا parser ساختاری بیاید.

### 6.3 Unstructured — fallback گسترده، نه contract مبهم

Unstructured طبق مستندات رسمی فرمت‌های زیادی از جمله DOC/DOCX، XLS/XLSX، PPT/PPTX، PDF، ODT، EPUB، EML، MSG، RTF، XML، image و text را فهرست می‌کند و برای PDF/image بین `fast`، `hi_res` و `ocr_only` trade-off دارد: [partitioning strategies](https://docs.unstructured.io/open-source/concepts/partitioning-strategies).

`fast` برای سرعت خوب است، اما برای image-based file مناسب نیست؛ `hi_res` کیفیت layout/table بهتری می‌دهد ولی مدل‌محور و کندتر است. کد فعلی صریحاً strategy، زبان OCR یا table extraction را تنظیم نمی‌کند؛ بنابراین رفتار فعلی برای فارسی و جدول‌ها قابل certification نیست.

### 6.4 MarkItDown — No-Go به‌عنوان parser دوم اصلی

MarkItDown فرمت‌های PDF، PowerPoint، Word، Excel، image، HTML، CSV، JSON و ZIP را به Markdown تبدیل می‌کند: [Microsoft MarkItDown](https://github.com/microsoft/markitdown).

برای prototype و text-first conversion مفید است، اما در این appliance:

- با Docling/Unstructured هم‌پوشانی دارد؛
- canonical provenance و table fidelity آن برای contract فعلی کافی نیست؛
- ZIP support به معنی امن‌بودن archive ingestion نیست؛
- اضافه‌کردنش parser سوم و مسیر failure سوم ایجاد می‌کند.

**No-Go در core؛ فقط evaluation adapter.**

### 6.5 LibreOffice headless — فقط compatibility worker

برای legacy Office و OpenDocument می‌توان LibreOffice را native با `--headless` به‌کار برد؛ Docling و Unstructured نیز برای برخی فرمت‌ها به آن تکیه می‌کنند. این worker باید:

- با user غیر root؛
- profile/temp directory اختصاصی؛
- timeout و process kill امن؛
- بدون macro execution؛
- بدون network access؛
- با محدودیت CPU/RAM/disk؛
- و با cleanup کامل اجرا شود.

LibreOffice را نباید parser اصلی همهٔ فایل‌ها کرد؛ layout conversion ممکن است تغییر کند و برای citation صفحه/سلول باید خروجی بررسی شود.

### 6.6 OCRmyPDF/Tesseract — ابزار PDF/A، نه انتخاب اصلی Persian RAG

OCRmyPDF برای اضافه‌کردن text layer به scanned PDF، skip/redo/force OCR و timeout per page مناسب است: [OCRmyPDF advanced documentation](https://ocrmypdf.readthedocs.io/en/latest/advanced.html).

ولی برای RAG فارسی، OCRmyPDF جای Docling/PaddleOCR را نمی‌گیرد؛ مخصوصاً چون هدف آن تولید PDF قابل جستجوست، نه لزوماً حفظ بهترین layout/table provenance. می‌تواند در مسیر archival/PDF normalization یک ابزار جانبی باشد.

---

## 7. مشکلات RAG فعلی که ارزش بهبود دارند

### 7.1 extraction به متن تخت تبدیل می‌شود

کد فعلی `str(element)` را با newline به متن تبدیل می‌کند. در نتیجه metadata مهمی مثل این‌ها از بین می‌رود:

- شماره صفحه؛
- heading و hierarchy؛
- نام sheet و cell range؛
- table structure؛
- slide number؛
- bounding box؛
- extraction confidence؛
- distinction بین caption، paragraph، header و footer.

این علت اصلی ضعف citation و افت retrieval روی table/form است.

### 7.2 JSON در allowlist هست، ولی parser صریح ندارد

JSON برای upload مجاز است، اما در مسیر extraction به `partition.auto` سپرده شده است. باید یا JSON را با parser deterministic به مسیرهای key/value تبدیل کرد، یا فعلاً از allowlist RAG حذف و پیام دقیق داد. قبول‌کردن فایل و fail کردن چند دقیقه بعد، UX و عملیات خوبی نیست.

### 7.3 Persian lexical search ضعیف‌تر از چیزی است که اسم hybrid القا می‌کند

FTS فعلی از `to_tsvector('simple', content)` استفاده می‌کند. این برای exact token مفید است، اما Persian normalization، نیم‌فاصله، تفاوت `ی/ي` و `ک/ك`، اعداد فارسی/لاتین، املای متغیر و typo را به‌طور تخصصی حل نمی‌کند.

بهترین مسیر کم‌هزینه فعلاً:

1. ستون normalized/search text جدا، بدون تغییر متن اصلی؛
2. normalize کردن Unicode، نیم‌فاصله، عربی/فارسی variants و اعداد؛
3. حفظ original برای citation؛
4. اضافه‌کردن `pg_trgm` برای شناسه، typo و substring؛
5. وزن‌دهی جدا به title، heading، identifier و body.

PostgreSQL برای `pg_trgm` ایندکس GIN/GiST و similarity/LIKE support دارد: [PostgreSQL pg_trgm](https://www.postgresql.org/docs/current/pgtrgm.html).

### 7.4 reranker هنوز در مسیر واقعی نیست

Hybrid score فعلی 80٪ vector و 20٪ lexical است، اما این وزن‌ها benchmark-derived نیستند و cross-encoder reranking وجود ندارد. مسیر بهتر:

```text
ACL
 -> dense + lexical top-50
 -> deduplicate document/section
 -> Qwen3-Reranker top-50
 -> top-5/10
 -> context budget و citation validation
```

Qwen3 reranker باید batch شود و top-K محدود بماند؛ rerank کردن کل corpus یا top-100 بدون اندازه‌گیری، سرعت را خراب می‌کند.

### 7.5 تعداد documentهای visible به‌صورت کامل به Python/SQL array می‌آید

`Document.search(visible_domain)` بدون limit تمام document idهای قابل‌مشاهده را می‌گیرد و سپس آن‌ها را به `ANY(%s)` می‌دهد. برای appliance کوچک قابل‌تحمل است؛ اما برای corpus بزرگ، ACL پررکورد یا relationهای زیاد می‌تواند memory و query planning را بد کند.

راه بهتر در آینده، بدون تغییر datastore، یکی از این‌هاست:

- temporary/materialized authorized scope با عمر transaction؛
- JOIN/EXISTS روی ACL/FGA در SQL؛
- partition یا scope key؛
- cap صریح همراه با fail-closed و metric.

این مورد باید با `EXPLAIN ANALYZE` و corpus واقعی ثابت شود، نه با حدس.

### 7.6 snapshot فعلی برای هر reindex کل شرکت را دوباره می‌بیند

`_rag_update_snapshot` برای محاسبهٔ active بودن، documentها و chunkهای revision را دوباره query می‌کند. در هر job کوچک و corpus بزرگ، این کار می‌تواند هزینهٔ indexing را بالا ببرد. بهتر است snapshot progress شمارنده/dirty marker داشته باشد و full digest فقط در مرحلهٔ activation یا certification انجام شود.

### 7.7 failure status برای کاربر کافی نیست

job خطا را ثبت می‌کند، اما Document Center وضعیت ingestion، parser، error code، retry count یا «قابل جستجو نیست» را به کاربر نشان نمی‌دهد. کاربر سند را upload شده می‌بیند ولی ممکن است هیچ chunk فعالی نداشته باشد.

حداقل status پیشنهادی:

```text
uploaded -> validating -> extracting -> ocr -> chunking -> embedding
         -> indexed | partial | failed
```

و error codeهای machine-readable:

```text
unsupported_type
invalid_signature
encrypted_document
parser_missing_dependency
ocr_empty
extracted_text_limit
index_embedding_unavailable
```

### 7.8 همهٔ فایل‌ها هم‌زمان نباید synchronous باشند

استخراج و embedding باید همیشه worker باشد. برای query چت، فقط retrieval و rerank باید synchronous با budget مشخص بماند. PDF/OCR/LibreOffice نباید در request thread اجرا شود.

---

## 8. policy پیشنهادی پذیرش فایل

### Tier A — production و اولویت بالا

```text
PDF, DOCX, XLSX, PPTX
TXT, MD, CSV, JSON
PNG, JPEG, WEBP, TIFF, BMP
HTML (اگر business واقعاً لازم دارد)
```

شرط: برای هر type حداقل یک fixture واقعی فارسی/انگلیسی و یک fixture خراب/رمزدار داشته باشیم.

### Tier B — فقط بعد از pilot

```text
DOC, XLS, PPT
ODT, ODS, ODP
RTF, EPUB, XML
EML, MSG
```

برای این Tier باید LibreOffice/pandoc و attachment policy مشخص شود.

### Tier C — فعلاً رد شود

```text
ZIP/RAR/7z
DOCM/XLSM/PPTM و هر macro-enabled file
EXE/DLL/SO/script
CAD و binary تخصصی
Audio/Video
PDF/Office encrypted یا password-protected
```

ردشدن باید در upload با دلیل دقیق باشد، نه اینکه سند ذخیره شود و بعداً silent empty result بدهد.

---

## 9. pipeline بهتر پیشنهادی

```text
1. Upload quarantine
   - size, extension, magic bytes, MIME sniff, hash
   - optional AV scan
   - archive/macro/encryption decision

2. Type detection
   - extension فقط hint باشد
   - libmagic/format detector + signature

3. Parser selection
   - Docling برای canonical structured extraction
   - PaddleOCR برای fa/ar scanned/image
   - LibreOffice فقط legacy Office compatibility
   - Unstructured fallback محدود و version-pinned

4. Canonical document
   - blocks, page, heading, table, sheet, slide, bbox
   - language, confidence, parser version
   - original text و normalized search text جدا

5. Validation
   - extracted characters/tokens/pages/rows/pixels/time
   - empty/low-confidence/partial status

6. Chunking
   - heading/table-aware، نه فقط character window
   - parent-child یا section metadata
   - chunk hash و source provenance

7. Embedding
   - batch، cache، model/revision contract
   - no partial activation

8. Retrieval
   - ACL/FGA first
   - exact identifier + normalized lexical + dense
   - pg_trgm/FTS candidate fusion
   - optional Qwen rerank

9. Answer gate
   - minimum score
   - citation validation
   - no-context => explicit unknown
   - audit and metrics
```

---

## 10. benchmark واقعی که قبل از ادعای «بهتر» لازم است

### Corpus ingestion

حداقل 10 نمونه از هر نوع Tier A:

- PDF دیجیتال با چندستونه؛
- PDF اسکن‌شدهٔ فارسی؛
- PDF مخلوط متن و تصویر؛
- DOCX با heading/table؛
- XLSX با چند sheet، merged cells و اعداد؛
- PPTX با text و image؛
- CSV/JSON بزرگ؛
- تصویر فارسی با کیفیت خوب و بد؛
- HTML/MD؛
- encrypted/corrupt/extension-mismatch fixtures.

### معیار extraction

- parse success rate؛
- exact text/character error rate؛
- Persian OCR CER/WER؛
- table cell precision/recall؛
- page/heading/sheet provenance accuracy؛
- empty extraction rate؛
- p50/p95 processing time؛
- peak RSS، temp disk و CPU؛
- retry و failure code correctness.

### معیار retrieval

- Recall@5/10/50؛
- Precision@k؛
- MRR و nDCG؛
- exact identifier hit rate؛
- Persian normalization hit rate؛
- table-question hit rate؛
- citation precision؛
- ACL leakage: صفر؛
- revoked access hit rate: صفر.

### معیار پاسخ

- grounded claim rate؛
- answer relevance؛
- abstention when context is insufficient؛
- citation coverage؛
- hallucination rate؛
- p50/p95/p99 retrieval + rerank + generation.

هیچ threshold عددی vendor یا blog نباید به‌عنوان pass/fail محصول پذیرفته شود؛ threshold باید بعد از baseline corpus مشتری تعیین شود.

---

## 11. اولویت اجرای پیشنهادی، بدون اضافه‌کردن framework

### P0 — اصلاحات policy و visibility

- یکی‌کردن upload policy بین chat و Document Center؛
- status و failure reason برای ingestion؛
- صریح‌کردن JSON/CSV parser؛
- dependency certification برای Unstructured؛
- تست magic bytes و encrypted/corrupt fixtures؛
- نشان‌دادن اینکه سند واقعاً `indexed` شده است.

### P1 — بهبود کیفیت extraction

- pilot موازی Docling و Unstructured، بدون تغییر production؛
- structured canonical output؛
- page/section/table/sheet provenance؛
- PaddleOCR فارسی/عربی برای scanned fixtures؛
- LibreOffice worker برای Tier B فقط در صورت نیاز.

### P2 — بهبود retrieval

- Persian/Arabic normalization؛
- pg_trgm برای identifier و typo؛
- title/heading/body weighted lexical fields؛
- Qwen reranker روی top-30/50؛
- query rewrite فقط برای queryهای مبهم، نه هر query.

### P3 — scale و operation

- محدودکردن visible scope بدون آرایهٔ unbounded؛
- snapshot progress incremental؛
- per-file timeout/RSS/temp-disk budget؛
- Prometheus metric برای parser، OCR، embedding، queue و failed jobs؛
- load test جدا برای chat و indexing.

## نتیجهٔ نهایی

RAG فعلی از نظر **امنیت پایه، ACL، queue durability و fail-closed indexing** مسیر خوبی دارد، اما از نظر «هر فایل را می‌گیرد»، «استخراج ساختاری»، «کیفیت فارسی»، «citation دقیق» و «سرعت واقعی inference» هنوز production-certified نیست.

سریع‌ترین مسیر بهترکردن آن این نیست که Qdrant، Haystack یا LlamaIndex اضافه شود. مسیر درست این است:

> **shared upload policy → Docling canonical extraction → PaddleOCR فارسی/عربی → metadata-aware chunking → pgvector + normalized lexical/pg_trgm → Qwen reranker → citation/abstention gate → measured observability**

در این مرحله هیچ تغییر کدی اعمال نشده؛ این فایل فقط نتیجهٔ audit و research است و قبل از implementation باید با corpus واقعی مشتری و DGX benchmark شود.
