# برنامه‌ی باز و مرحله‌ای ارتقای Document Ingestion / RAG

**تاریخ برنامه:** ۱۴۰۵/۰۶/۱۴ برابر با 2026-09-05
**شاخه:** `arena/01a054c0-aibox-odoo`
**آخرین commit مبنا:** `bf7a24e`
**وضعیت فعلی:** Source-verified؛ runtime-certified نیست.

این برنامه عمداً fail-closed است. هر مرحله باید evidence قابل بازتولید تولید کند؛
«کد وجود دارد» یا «تست static سبز است» جایگزین اجرای واقعی روی Odoo، PostgreSQL،
native OCR و DGX نمی‌شود.

---

## 1. نتیجه‌ی تست فعلی

### مواردی که اکنون سبز هستند

| گیت | نتیجه | شاهد |
|---|---:|---|
| قراردادهای Python و ingestion | PASS | ۳۳ تست unittest |
| policy مشترک upload | PASS | policy و round-trip test |
| extractor builtin JSON/HTML | PASS | `tests/test_rag_ingestion.py` |
| provenance chunk | PASS | page/section/type/coordinates/table/sheet/slide |
| ACL-before-retrieval source gate | PASS | `allowed_doc_ids` قبل از raw SQL |
| queue/lease self-test | PASS | ۱۴/۱۴ |
| burst مسیر chat | PASS | ۱۰۰/۱۰۰ در self-test موجود |
| static security gates | PASS | ۲۱/۲۱ |
| exhaustive source audit | PASS | ۹۴/۹۴ |
| frontend production build | PASS | Vite build |
| frontend dependency audit | PASS | ۰ vulnerability |
| dependency resolver | PASS | `pip --dry-run -r requirements.lock` |
| release manifest | PASS | ۴۳۹ ورودی، صفر mismatch |

### مواردی که عمداً هنوز PASS اعلام نشده‌اند

1. Odoo registry و migration روی database واقعی.
2. PostgreSQL extensionهای `vector` و `pg_trgm`، column/index و HNSW.
3. record rule، FGA، multi-company و ACL retrieval با userهای واقعی.
4. native OCR پس از نصب `libgl1`, `libglib2.0-0`, Tesseract و زبان فارسی.
5. rollback و savepoint worker روی PostgreSQL واقعی.
6. corpus benchmark فارسی واقعی مشتری.
7. ظرفیت، latency و memory روی DGX GB10.
8. ادعای ۱۰۰ concurrent یا production-ready.

---

## 2. تعریف هدف نهایی

قبل از هر ادعای production، این پنج gate باید هم‌زمان سبز شوند:

### Gate A — نصب native و dependency

- Python runtime نسخه‌ی مصوب.
- Odoo و `odoo-llm` از commit immutable.
- vLLM از نسخه‌ی immutable.
- PostgreSQL و pgvector نسخه‌ی مصوب.
- native OCR binaryها موجود.
- `pip check` بدون conflict.
- هیچ parser در runtime برای download مدل یا telemetry به اینترنت وابسته نباشد.

### Gate B — database و migration

- backup قابل restore تولید شده باشد.
- `ai_rag` بدون خطای registry upgrade شود.
- migration `18.0.1.3.0` اجرا شود.
- ستون‌ها و indexها در PostgreSQL واقعی دیده شوند.
- تعداد document/chunk قبل و بعد ثبت شود.
- rollback آزمایشی روی clone موفق باشد.

### Gate C — correctness و security

- ingest برای فرمت‌های Tier A روی corpus واقعی موفق باشد.
- ACL قبل از retrieval با دو user غیرمجاز و مجاز اثبات شود.
- citation از page/section/table/sheet/slide به رکورد صحیح برسد.
- فایل unsafe، ZIP traversal، فایل جعلی و oversize رد شوند.
- خطای parser در UI عمومی safe و در backend durable باشد.

### Gate D — worker و recovery

- process kill، DB disconnect، embedding timeout و parser failure تست شوند.
- job در `pending/running/done/failed` صحیح بماند.
- lease منقضی‌شده دوباره queue شود.
- chunkهای revision قبلی هنگام failure نابود نشوند.
- retry دستی فقط با authorization مناسب انجام شود.

### Gate E — performance و capacity

- benchmark با corpus فارسی customer-like اجرا شود.
- cold-start و warm-start جداگانه ثبت شوند.
- extraction، embedding، DB retrieval و end-to-end جدا اندازه‌گیری شوند.
- evidence همان run شامل GPU، queue، DB و Redis باشد.
- سپس `61_v58_capacity_gate.py` با threshold مصوب اجرا شود.

---

## 3. فازهای اجرایی پیشنهادی

## فاز 0 — Freeze و baseline

**هدف:** مشخص‌کردن دقیق نسخه و جلوگیری از تغییر هم‌زمان.

### اقدامات

1. branch release را freeze کنید.
2. مقدارهای زیر را ثبت کنید:
   - `ODOO_COMMIT_SHA`
   - `ODOO_LLM_COMMIT_SHA`
   - `VLLM_VERSION`
   - `PYTHON_RUNTIME_VERSION`
   - `MODEL_REVISION_QWEN`
   - `MODEL_REVISION_EMBEDDING`
   - `AI_RAG_INDEX_VERSION`
   - PostgreSQL/pgvector version
3. از DB و model directory inventory بگیرید.
4. checksum release را تولید و نگه‌داری کنید.

### خروجی و معیار خروج

- `DEPLOYMENT_ARTIFACTS.lock` کامل.
- checksum بدون mismatch.
- نسخه‌ها در ticket/deployment record ثبت شده باشند.
- هیچ تغییر code بدون commit review شده وارد فاز بعد نشود.

---

## فاز 1 — آماده‌سازی appliance

**هدف:** ساخت محیط native بدون Docker.

### اجرای پیشنهادی

```bash
export AI_GATEWAY_ENV=production
export ODOO_DB=company_ai
export INSTALL_OS_DEPS=1

./01_setup_base.sh
python3 -m pip install --dry-run \
  --ignore-installed --break-system-packages \
  -r requirements.lock
```

سپس روی venv واقعی:

```bash
pip install -r requirements.lock
pip check
python - <<'PY'
import docling
import unstructured
import fitz
import openpyxl
import docx
import pptx
print("parser imports ok")
PY
```

### نکته‌ی مهم OCR

اگر import `rapidocr_onnxruntime` با خطای `libGL.so.1` شکست خورد:

1. وجود `libgl1` و `libglib2.0-0` را بررسی کنید.
2. `ldconfig -p | grep -E 'libGL|libgthread'` اجرا کنید.
3. venv را حذف نکنید؛ ابتدا OS dependency را اصلاح کنید.
4. دوباره import و سپس تصویر فارسی واقعی را تست کنید.

### معیار خروج

- `pip check` سبز.
- import همه‌ی parserها سبز.
- telemetry و self-download مدل در trace شبکه دیده نشود.
- سرویس‌ها هنوز start نشوند تا فاز database تمام شود.

---

## فاز 2 — database clone و migration

**هدف:** اجرای امن migration قبل از production database.

### ترتیب

1. از database production backup بگیرید.
2. backup را روی DB clone restore کنید.
3. سرویس Odoo و worker را روی clone متوقف کنید.
4. source/addons را deploy کنید.
5. module upgrade را اجرا کنید:

```bash
AI_MODULE_MODE=upgrade \
ODOO_DB=company_ai_clone \
./02_install_modules.sh
```

6. migration را بررسی کنید:
   - `rag_ingestion_state`
   - `rag_ingestion_error`
   - `rag_ingestion_checksum`
   - `normalized_content`
   - provenance columns
7. index/extension را از PostgreSQL بررسی کنید:

```sql
SELECT extname FROM pg_extension
WHERE extname IN ('vector', 'pg_trgm');

SELECT indexname
FROM pg_indexes
WHERE tablename = 'ai_document_chunk';
```

8. تعدادها را قبل و بعد ثبت کنید:
   - documents with file
   - chunks
   - indexed/failed/pending/empty
   - chunks with normalized content

### معیار خروج

- registry upgrade بدون traceback.
- migration idempotent روی clone.
- تعداد فایل‌ها کم نشده باشد.
- `pg_trgm` و vector در نسخه‌ی PostgreSQL هدف قابل استفاده باشند.
- rollback clone موفق باشد.

### rollback

اگر migration یا registry شکست خورد:

1. worker و Odoo را متوقف کنید.
2. DB clone را حذف کنید.
3. backup را دوباره restore کنید.
4. علت را اصلاح کنید.
5. روی production database تا عبور clone هیچ upgradeی اجرا نکنید.

---

## فاز 3 — corpus و correctness

**هدف:** اندازه‌گیری کیفیت واقعی، نه فرضی.

### corpus حداقل پیشنهادی

با اجازه‌ی مشتری و بدون خروج داده از appliance:

- ۲۰ PDF متنی و ۲۰ PDF اسکن‌شده
- ۲۰ DOCX شامل heading و table
- ۱۰ XLSX با چند sheet و نام فارسی
- ۱۰ PPTX چنداسلایدی
- ۱۰ HTML/JSON/CSV
- حداقل ۳۰٪ متن فارسی/عربی مختلط با اعداد و ZWNJ
- فایل‌های خراب، خالی، oversize و filenameهای adversarial

برای هر فایل gold metadata ثبت شود:

```json
{
  "file": "policy-01.pdf",
  "expected_pages": [2, 4],
  "expected_sections": ["مرخصی"],
  "expected_terms": ["استحقاق", "روز کاری"],
  "expected_tables": [],
  "expected_acl_users": ["hr-manager"],
  "forbidden_acl_users": ["warehouse-user"]
}
```

### سنجه‌ها

- extraction success rate
- empty extraction rate
- parser fallback rate
- page/section citation precision
- sheet/slide/table citation precision
- Persian lexical recall
- exact identifier recall
- ACL false-positive count — باید صفر باشد
- checksum/idempotency behavior
- median و p95 extraction time
- memory peak برای فایل‌های بزرگ

### معیار خروج پیشنهادی

Thresholdها باید بعد از baseline corpus تعیین شوند؛ در کد hard-code نشوند.
اما این موارد absolute هستند:

- ACL leakage: صفر
- unsafe upload acceptance: صفر
- raw customer text در log: صفر
- network call برای parser/runtime: صفر
- data loss در reindex failure: صفر

---

## فاز 4 — failure و recovery

**هدف:** اثبات durable behavior.

### سناریوهای اجباری

1. Docling exception.
2. Unstructured dependency missing.
3. OCR empty.
4. embedding endpoint timeout.
5. embedding dimension mismatch.
6. PostgreSQL disconnect هنگام create chunk.
7. kill کردن worker هنگام `extracting`.
8. kill کردن worker هنگام `embedding`.
9. lease expiration.
10. retry manual توسط owner.
11. retry توسط user غیرمالک.
12. concurrent enqueue برای یک document.
13. حذف document هنگام pending job.
14. index revision ناقص و active snapshot قدیمی.

### evidence لازم

برای هر سناریو:

- قبل/بعد state
- job id
- document id داخلی در evidence خصوصی
- تعداد chunk قبل/بعد
- snapshot status
- log correlation id
- نتیجه‌ی UI عمومی safe

---

## فاز 5 — ACL و retrieval واقعی

**هدف:** اطمینان از اینکه parser یا vector search هیچ authorizationی را دور نمی‌زند.

### ماتریس user

حداقل:

- system admin
- company user
- department user
- group user
- personal owner
- user بدون grant
- delegated user
- user از company دیگر

### تست‌ها

برای یک query یکسان:

1. document مجاز باید قابل retrieval باشد.
2. document غیرمجاز نباید در vector result باشد.
3. document غیرمجاز نباید در lexical result باشد.
4. document غیرمجاز نباید در trigram result باشد.
5. citation نباید از document غیرمجاز ساخته شود.
6. global grant نباید record rule native را دور بزند.
7. overflow authorized scope باید fail-closed شود.

نتیجه‌ی قابل قبول برای leakage فقط **صفر** است؛ p95 یا average برای این گیت معنی ندارد.

---

## فاز 6 — performance و DGX

**هدف:** اندازه‌گیری واقعی روی target، نه sandbox.

### benchmark warm-up

```bash
python3 60_v58_llm_benchmark.py \
  --endpoint http://127.0.0.1:8000/v1/chat/completions \
  --model local-model \
  --scenario chat \
  --warmup 10 \
  --requests 100 \
  --concurrency 10 \
  --output /tmp/ai-chat-benchmark.json
```

برای embedding، vision، tool و RAG نیز run جداگانه تولید شود. مقدارهای واقعی
مدل و endpoint باید از systemd unit همان appliance خوانده شوند.

### capacity gate

Thresholdهای واقعی را بعد از baseline مصوب کنید، سپس:

```bash
python3 61_v58_capacity_gate.py \
  /tmp/ai-chat-benchmark.json \
  --min-completed 100 \
  --min-concurrency 100 \
  --max-p95-ttft-ms <approved> \
  --max-p95-e2e-ms <approved> \
  --max-error-rate 0
```

گزارش بدون این سه evidence معتبر نیست:

- `gpu_metrics`
- `queue_metrics`
- `db_redis_metrics`

اجرای benchmark با ۱۰۰ concurrency تا زمانی که روی DGX و با evidence سیستم انجام
نشده باشد فقط برنامه‌ی test است، نه نتیجه.

---

## فاز 7 — certification ماژول و production canary

### module certification

روی Odoo shell واقعی:

```bash
/opt/odoo/src/odoo/odoo-bin shell \
  -c /etc/odoo/odoo.conf \
  -d company_ai < 62_v58_module_certification.py
```

### universal integration certification

```bash
/opt/odoo/src/odoo/odoo-bin shell \
  -c /etc/odoo/odoo.conf \
  -d company_ai < 48_auto_integration_certification.py
```

هر دو باید fail-closed سبز شوند. اگر یکی fail شد:

- canary متوقف شود.
- `03_start_all.sh` اجرا نشود.
- خروجی و آخرین database snapshot حفظ شود.

### canary

1. یک tenant/appliance clone.
2. یک گروه کوچک user مجاز.
3. ingest محدود با corpus non-sensitive یا customer-approved.
4. monitor status/error/queue/DB/GPU.
5. یک rollback window مشخص.
6. سپس افزایش تدریجی corpus و user.

---

## فاز 8 — production rollout و rollback

### قبل از rollout

- backup restore test سبز.
- همه‌ی checksumها سبز.
- systemd unitها `daemon-reload` شده‌اند.
- Odoo module upgrade روی clone سبز.
- active snapshot معتبر است.
- worker queue خالی یا برنامه‌ریزی‌شده است.
- مدل و embedding revision ثبت شده‌اند.

### rollout

```bash
./01_setup_base.sh
AI_MODULE_MODE=upgrade ODOO_DB=company_ai ./02_install_modules.sh
AI_GATEWAY_ENV=production ./03_start_all.sh
```

سپس:

1. health check Odoo.
2. health check PostgreSQL/Redis.
3. health check vLLM.
4. health check event worker و RAG worker.
5. ingest یک فایل کوچک synthetic.
6. ingest یک فایل واقعی approved.
7. query با user مجاز و غیرمجاز.
8. بررسی citation و status UI.

### rollback trigger

هر کدام از موارد زیر rollback را فعال می‌کند:

- ACL leakage حتی یک مورد
- data loss یا حذف chunkهای revision سالم
- migration traceback یا registry corruption
- error rate بالاتر از threshold مصوب
- queue stuck بدون lease recovery
- network call از parser/runtime
- mismatch embedding dimension
- citation نادرست در سناریوی critical business

---

## 4. backlog ارتقا بعد از certification

این موارد فقط بعد از سبزشدن runtime gate انجام شوند:

### اولویت P0

- اجرای واقعی migration روی PostgreSQL clone
- تست OCR فارسی/عربی روی اسکن‌های مشتری
- تست ACL چندشرکتی و FGA
- failure injection worker
- backup/restore و rollback

### اولویت P1

- parser cache بر مبنای checksum با invalidation امن
- ingest progress درصدی برای فایل‌های چندصفحه‌ای
- metrics dashboard برای parser/fallback/error/queue
- retention policy برای error و extraction metadata
- dead-letter queue با operator action
- reindex بر اساس revision به‌جای overwrite مستقیم

### اولویت P2

- table-aware chunking با header propagation
- sheet-aware retrieval filters
- citation preview با bounding box
- deduplication در سطح فایل با SHA-256
- multilingual analyzer قابل benchmark
- archive quarantine مستقل در صورت نیاز واقعی

### چیزهایی که فعلاً انجام نشوند

- اضافه‌کردن framework جدید بدون benchmark
- فعال‌کردن `unstructured[all-docs]` فقط برای افزایش فهرست formatها
- ارسال فایل به API ابری برای parsing/OCR/embedding
- حذف ACL به امید اینکه vendor آن را حل کند
- ادعای capacity بدون DGX evidence
- اجرای migration روی production بدون clone و restore test

---

## 5. تصمیم نهایی برای release

### قابل انتشار به canary وقتی

- فازهای ۰ تا ۵ سبز باشند.
- هیچ P0 باز وجود نداشته باشد.
- runtime evidence به commit و artifact lock متصل باشد.

### قابل انتشار عمومی وقتی

- canary بدون leakage/data-loss تمام شود.
- فاز ۶ روی target واقعی سبز باشد.
- فاز ۷ certification کامل PASS بدهد.
- rollback در زمان توافق‌شده اثبات شده باشد.

### وضعیت فعلی

در زمان نگارش این برنامه، repository در سطح source و static verification آماده‌ی
ورود به **فاز ۰ و فاز ۱** است؛ اما به‌دلیل نبود Odoo/PostgreSQL/DGX در این محیط،
فازهای ۲ تا ۷ هنوز باید روی appliance واقعی اجرا شوند.
