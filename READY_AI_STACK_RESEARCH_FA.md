# Research: سریع‌ترین و کاربردی‌ترین AI Stack آماده برای Company Assistant

**تاریخ تحقیق:** 2026-09-04
**دامنه:** یک دستگاه مستقل برای هر مشتری، نصب native با systemd، بدون Docker، داده و مدل‌ها خارج از workspace، Odoo به‌عنوان ERP backend و Company Assistant به‌عنوان نقطهٔ مرکزی authorization/audit/risk.

## 1. نتیجهٔ اجرایی

برای این محصول، راه درست اضافه‌کردن ده‌ها framework نیست. سریع‌ترین مسیر قابل‌اعتماد این است:

1. **vLLM حفظ شود** و فقط build/configuration سازگار با DGX GB10/SM121 و مدل‌های تأییدشده انتخاب شود.
2. **PostgreSQL + pgvector حفظ شود**؛ چون سند، company، ACL، FGA، audit و backup همین‌جا هستند. فعلاً Qdrant/OpenSearch نباید به‌عنوان datastore دوم اضافه شود.
3. **Docling به‌عنوان parser اصلی اسناد** در یک worker native جداگانه اضافه شود؛ `Unstructured` به‌عنوان fallback فرمت‌های خاص باقی بماند.
4. **PaddleOCR/PP-OCR برای فارسی و عربی** به‌عنوان OCR تخصصی scanned documents اضافه شود؛ RapidOCR فعلی به‌تنهایی انتخاب مناسبی برای certification فارسی نیست.
5. **Qwen3-Embedding-0.6B حفظ/تأیید شود** و یک **Qwen3-Reranker-0.6B** از طریق endpoint آمادهٔ rerank vLLM به pipeline اضافه شود: hybrid retrieve تا top-50، rerank تا top-5/10.
6. **Prometheus + Grafana + exporters** اضافه شوند تا capacity با evidence واقعی اندازه‌گیری شود؛ vLLM خودش `/metrics` و شاخص‌های TTFT، TPOT، queue، KV-cache و success را ارائه می‌کند.
7. **pgBackRest** برای backup/PITR/restore certification اضافه شود.
8. LiteLLM، Haystack، LlamaIndex و Qdrant فقط برای evaluation یا سناریوی scale مشخص نگه داشته شوند، نه اینکه لایهٔ مرکزی فعلی را بی‌دلیل جایگزین کنند.

این پیشنهاد، بیشترین استفاده از ابزارهای آماده را با کمترین ریسک integration و کمترین duplication دارد.

---

## 2. وضعیت فعلی repository که در تصمیم مؤثر است

در checkout فعلی، اجزای زیر از قبل وجود دارند:

- vLLM با سه unit native برای chat، embedding و vision؛
- PostgreSQL/pgvector با HNSW و full-text index؛
- Redis برای lease و coordination؛
- Company Assistant، capability/risk/approval/audit و module binding؛
- ACL/FGA قبل از RAG retrieval؛
- extraction فعلی با Unstructured و OCR فعلی با RapidOCR؛
- benchmark برای chat/tool/RAG/embedding/vision و queue self-test برای burst صدتایی.

بنابراین اضافه‌کردن یک agent/RAG framework جدید، بخش زیادی از قابلیت‌های موجود را duplicate می‌کند و حتی ممکن است ACL مرکزی را دور بزند. ابزار جدید باید از طریق adapter reviewed و همان Company Assistant متصل شود، نه اینکه یک gateway یا memory مستقل بسازد.

---

## 3. ارزیابی گزینه‌ها

### A. vLLM — **انتخاب قطعی برای serving**

**وضعیت:** نگه‌داری و harden، نه تعویض.

vLLM به‌صورت رسمی OpenAI-compatible chat، embeddings و scoring/rerank API دارد؛ مستندات فعلی آن `/v1/chat/completions`، `/v1/embeddings` و `/rerank`/`/v1/rerank` را پوشش می‌دهد. این با client و model registry فعلی سازگار است: [vLLM Online Serving](https://docs.vllm.ai/en/stable/serving/online_serving/).

برای DGX Spark، خود پروژهٔ vLLM تأکید می‌کند که GB10 دارای unified CPU/GPU memory است و مدل، سیستم‌عامل، runtime و KV cache از همان pool استفاده می‌کنند؛ همچنین DGX Spark برای single-user یا small-batch مناسب‌تر از high-concurrency سنگین است. تنظیم `max-num-seqs` و `gpu-memory-utilization` باید با benchmark واقعی انجام شود، نه حدس: [vLLM on DGX Spark](https://vllm.ai/blog/2026-06-01-vllm-dgx-spark).

**کاری که باید انجام شود:**

- نسخهٔ vLLM/PyTorch/CUDA را با build سازگار با SM121 روی خود DGX تأیید کنید؛ `pip install vllm==...` بدون compatibility test کافی نیست.
- chat و embedding فعلی باقی بمانند.
- reranker به‌صورت unit جداگانه یا مدل score روی همان serving stack آزمایش شود؛ هم‌زمانی آن با chat باید از نظر unified memory اندازه‌گیری شود.
- `/metrics` به Prometheus وصل شود.
- `--max-num-seqs=32` فعلی به‌عنوان ظرفیت واقعی تلقی نشود؛ آن فقط تنظیم فعلی scheduler است.

**نتیجه:** vLLM قابل یکپارچه‌سازی کامل است و تعویض آن با Ollama، llama.cpp یا TGI در این معماری توصیه نمی‌شود.

### B. Qwen3-Embedding — **انتخاب مناسب فعلی**

مدل رسمی Qwen3-Embedding-0.6B ویژگی‌های زیر را اعلام می‌کند: بیش از 100 زبان، context تا 32K، خروجی تا 1024 dimension، MRL و instruction-aware بودن: [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B).

این دقیقاً با dimension فعلی 1024 و سرویس embedding موجود سازگار است. نکتهٔ مهم: model card توصیه می‌کند query با instruction مناسب ساخته شود؛ پس benchmark باید جداگانه برای فارسی، انگلیسی، code، شناسه و query کوتاه انجام شود.

**پیشنهاد عملی:**

- ابتدا 0.6B را نگه دارید تا latency و memory مناسب بماند.
- اگر Recall@10 یا nDCG روی golden set کافی نبود، 4B را به‌صورت candidate آزمایش کنید؛ آن مدل dimension پیش‌فرض بزرگ‌تری دارد و تغییر آن migration/reindex واقعی می‌خواهد.
- بدون benchmark، فقط به جدول MTEB اعتماد نکنید؛ معیار اصلی باید اسناد واقعی مشتری و فارسی باشد.

### C. Qwen3-Reranker-0.6B — **بیشترین بهبود کیفیت با کمترین integration**

Qwen3-Reranker-0.6B برای reranking، بیش از 100 زبان و context تا 32K دارد: [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B). vLLM نیز API رسمی rerank/score دارد: [vLLM scoring and rerank APIs](https://docs.vllm.ai/en/stable/serving/online_serving/).

**Pipeline پیشنهادی:**

```text
ACL/FGA
  -> lexical BM25 + dense vector candidate retrieval (top 50)
  -> deduplicate by chunk/document
  -> Qwen3-Reranker-0.6B (top 50 -> top 5/10)
  -> citation-safe context
  -> LLM
```

این بهتر از بالا بردن بی‌حد `top_k` است. Reranker نباید قبل از ACL اجرا شود و نباید متن غیرمجاز را حتی برای scoring ببیند.

**ریسک:** reranker روی همان GB10 می‌تواند با chat رقابت کند. سه حالت باید benchmark شود:

1. reranker CPU؛
2. reranker روی همان GPU با admission محدود؛
3. reranker فقط برای queryهای مبهم/پرریسک و bypass برای exact identifier.

### D. Docling — **parser اصلی پیشنهادی**

Docling به‌صورت local/offline و MIT عرضه می‌شود و PDF، Office، HTML و image را با reading order، table، formula، OCR، provenance و structured output پردازش می‌کند: [Docling official](https://docling.ai/). مستندات آن chunkهای structure-aware و provenance صفحه/ناحیه را نیز پوشش می‌دهد.

این برای citation فعلی یک پیشرفت واقعی است؛ citation فقط نام سند نباشد، بلکه بتواند page، section، table و bounding box را هم نگه دارد.

**نحوهٔ integration بدون بازطراحی محصول:**

- یک `ai-document-worker.service` native با queue فعلی RAG؛
- مدل‌ها و cache در `/opt/models` یا `/var/cache/ai-box`، نه workspace؛
- خروجی canonical در JSON/Markdown داخلی شامل:
  - text؛
  - page number؛
  - heading path؛
  - table structure؛
  - provenance/bounding box؛
  - extraction confidence؛
- chunk و embedding فعلی از همین خروجی استفاده کنند؛
- Unstructured برای فرمت‌هایی که Docling در certification corpus ضعیف‌تر است fallback بماند.

**تصمیم:** بله، یکپارچه‌سازی ارزشمند است؛ اما باید به‌صورت worker/adapter انجام شود، نه import پراکنده در چند tool.

### E. PaddleOCR / PP-OCRv5 — **OCR مناسب‌تر برای فارسی**

مستندات رسمی PP-OCRv5، مدل `arabic_PP-OCRv5_mobile_rec` را برای Arabic، Persian، Uyghur، Urdu، Pashto، Kurdish، Sindhi و Balochi معرفی می‌کند: [PP-OCRv5 multilingual](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html). مخزن رسمی PaddleOCR نیز PP-StructureV3، document parsing و پوشش چندزبانه را ارائه می‌دهد: [PaddleOCR repository](https://github.com/PaddlePaddle/PaddleOCR).

**پیشنهاد:**

- برای scanned Persian/Arabic، PaddleOCR مسیر اصلی OCR شود.
- RapidOCR فعلی فقط fallback یا مسیر سبک CPU باشد.
- OCR زبان سند را از metadata، script detection یا تنظیم customer profile بگیرد؛ یک مدل واحد برای همهٔ زبان‌ها کیفیت یکسان نمی‌دهد.
- جدول‌ها و فرم‌ها با PP-StructureV3 یا Docling مقایسه شوند؛ یکی را بدون corpus test قطعی اعلام نکنید.

### F. pgvector — **فعلاً حفظ شود**

pgvector جدید قابلیت HNSW، exact/approximate search، half/binary/sparse vectors و ACID/JOINهای PostgreSQL را دارد. نسخهٔ فعلی upstream در زمان این تحقیق v0.8.6 است: [pgvector README](https://github.com/pgvector/pgvector/blob/master/README.md).

مهم‌ترین نکته برای سیستم فعلی این است که در queryهای HNSW دارای filter، filter ممکن است بعد از scan اعمال شود و result کمتر از `k` برگردد. pgvector برای این موضوع `hnsw.iterative_scan = strict_order/relaxed_order` و `hnsw.max_scan_tuples` دارد. پس HNSW بدون `EXPLAIN ANALYZE` و بدون iterative scan، evidence کافی نیست.

**پیشنهاد DBA:**

- pgvector را به نسخهٔ certified حداقل 0.8.6 ارتقا/تأیید کنید؛
- برای queryهای ACL-filtered، `SET LOCAL hnsw.iterative_scan = strict_order` در مسیر precision یا `relaxed_order` همراه با sort نهایی در مسیر latency؛
- `hnsw.ef_search` و `hnsw.max_scan_tuples` را per-query یا per-transaction تنظیم کنید؛
- `EXPLAIN (ANALYZE, BUFFERS)` و تعداد result بعد از ACL ثبت شود؛
- اگر ACL selectivity بسیار پایین است، partial index/partitioning یا vector store تخصصی را فقط بعد از benchmark بررسی کنید.

**چرا Qdrant فعلاً نه؟** چون Qdrant filtering، hybrid query، quantization و snapshot خوبی دارد: [Qdrant Search](https://qdrant.tech/documentation/search/search/) و [Qdrant Snapshots](https://qdrant.tech/documentation/snapshots/). اما اضافه‌کردنش یعنی datastore دوم، sync ACL/FGA، backup جداگانه، restore جداگانه، secret/API policy و احتمال divergence با company.document. در appliance تک‌مشتری با PostgreSQL مرکزی، این هزینه فعلاً از سود آن بیشتر است.

### G. Qdrant — **گزینهٔ scale، نه نصب فوری**

Qdrant زمانی توجیه دارد که یکی از این شرایط ثابت شود:

- میلیون‌ها chunk در یک appliance؛
- query latency PostgreSQL با iterative scan هنوز از SLO خارج است؛
- vector filtering/quantization و snapshotهای مستقل ارزش عملی ایجاد کند؛
- یا retrieval به‌صورت مستقل از ERP scale شود.

در آن حالت، بهترین integration آماده، Qdrant + payload index + dense/sparse hybrid + alias-based reindex است. ولی ACL باید به‌صورت deny-by-default در payload و query filter تکرار شود و PostgreSQL همچنان source of truth بماند.

### H. OpenSearch — **برای enterprise search بزرگ، نه حالا**

OpenSearch hybrid search را با BM25 و neural/k-NN و search pipeline/normalization ارائه می‌کند: [OpenSearch hybrid search tutorial](https://docs.opensearch.org/latest/tutorials/vector-search/neural-search-tutorial/). مزیت مهم آن efficient k-NN filtering است که filter را داخل vector query و حین search اجرا می‌کند؛ post-filtering ممکن است کمتر از `k` result بدهد: [OpenSearch vector filtering](https://docs.opensearch.org/latest/vector-search/filter-search-knn/index/).

**مزایا:** full-text/facets/analytics، filtered k-NN، hybrid pipeline و observability قوی.
**معایب برای این appliance:** JVM/heap، cluster/service دوم، security/index ACL، backup جدا و پیچیدگی native installation.

**تصمیم:** اگر corpus یا search scope از توان pgvector عبور کرد، OpenSearch از Qdrant برای search+facets مناسب‌تر است؛ امروز اضافه‌کردن آن premature است.

### I. Haystack و LlamaIndex — **frameworkهای pipeline، نه محصول runtime فعلی**

Haystack آمادهٔ Qdrant hybrid retriever، sparse+dense و RRF دارد: [Haystack QdrantHybridRetriever](https://docs.haystack.deepset.ai/docs/qdranthybridretriever). این برای prototype/evaluation مفید است.

اما Haystack/LlamaIndex خودشان ACL مرکزی، Odoo record rules، approval، audit، binding و customer onboarding را حل نمی‌کنند. اضافه‌کردن آن‌ها به production path یعنی یک orchestration layer دوم و مقدار زیادی adapter. بنابراین:

- برای **offline RAG evaluation** قابل استفاده‌اند؛
- برای **مسیری که پاسخ مشتری را تولید می‌کند** فعلاً اضافه نشوند؛
- اگر بعداً Qdrant/OpenSearch انتخاب شد، Haystack می‌تواند adapter pipeline باشد، ولی source of truth و policy همچنان Company Assistant بماند.

### J. LiteLLM — **فقط اگر multi-provider واقعی لازم شد**

LiteLLM unified OpenAI-format برای 100+ provider، retry/fallback، router و proxy با virtual keys/budgets/observability دارد: [LiteLLM official](https://docs.litellm.ai/docs/).

ولی gateway فعلی همین حالا API key، ACL، risk، approval، audit، queue، Redis lease و model registry دارد. قرار دادن LiteLLM جلوی آن یا پشت آن می‌تواند دو policy plane بسازد و fallback مدل را بدون approval/quality contract وارد کند.

**تصمیم:**

- برای benchmark چند provider یا failover cloud، SDK/Router آن قابل بررسی است؛
- برای product path فعلی اضافه نشود؛
- اگر روزی لازم شد، LiteLLM فقط پشت Model Router بیاید و هر fallback همان capability/risk/audit contract را حفظ کند.

### K. Observability — **حتماً اضافه شود**

vLLM metricهای request-level و engine-level ارائه می‌کند: running/waiting/swapped، KV-cache، TTFT، inter-token latency، E2E، prompt/generation tokens و success: [vLLM Metrics](https://docs.vllm.ai/en/stable/design/metrics/).

پشتهٔ آمادهٔ پیشنهادی native:

- Prometheus؛
- Grafana؛
- node_exporter؛
- postgres_exporter؛
- redis_exporter؛
- scrape کردن `/metrics` هر vLLM unit؛
- log/audit فعلی Odoo؛
- alert برای queue waiting، KV-cache، preemption، p95 TTFT، p99 E2E، error rate، Redis outage و RAG job failure.

این بخش هیچ framework agent جدیدی نمی‌خواهد و بیشترین ارزش را برای اثبات capacity دارد.

### L. pgBackRest — **حتماً برای backup/restore certification**

برای یک دستگاه مستقل، backup قابل‌اعتماد باید full/diff/incremental، WAL/PITR، retention، encryption، verify و restore test داشته باشد. pgBackRest ابزار آمادهٔ مناسب PostgreSQL است؛ بهتر از اینکه فقط `pg_dump` و یک cron دستی به‌عنوان backup معرفی شود. در هر appliance باید restore روی مسیر/DB جداگانه به‌طور دوره‌ای آزمایش شود.

---

## 4. جدول تصمیم نهایی

| ابزار | اضافه شود؟ | نقش | روش integration | ریسک |
|---|---:|---|---|---|
| vLLM | بله، حفظ شود | chat/embedding/rerank/vision | systemd + pinned GB10 build | unified-memory و SM121 |
| Qwen3 Embedding 0.6B | بله | dense retrieval | unit فعلی embedding | کیفیت فارسی باید benchmark شود |
| Qwen3 Reranker 0.6B | بله، مرحلهٔ بعد | rerank top-50 | unit/endpoint score vLLM | رقابت با chat روی یک GPU |
| Docling | بله | structured extraction/provenance | document worker | dependency/model cache و CPU time |
| PaddleOCR PP-OCRv5 | بله | فارسی/عربی OCR | OCR worker/fallback | مدل زبان و کیفیت جدول |
| pgvector 0.8.6+ | بله، حفظ و upgrade | vector store مرکزی | same PostgreSQL + iterative scan | filtered HNSW باید EXPLAIN شود |
| Prometheus/Grafana/exporters | بله | evidence/operations | native systemd | retention/storage |
| pgBackRest | بله | backup/PITR/restore | native package + scheduled jobs | restore باید واقعاً test شود |
| Qdrant | فعلاً خیر | scale vector store | فقط pilot جدا | ACL/data sync و service دوم |
| OpenSearch | فعلاً خیر | large search/facets | فقط اگر pgvector fail شود | JVM/cluster/ACL/backup |
| Haystack | فقط evaluation | pipeline experiment | خارج از product path | duplicate orchestration |
| LlamaIndex | فقط evaluation | ingestion/retrieval experiment | خارج از product path | duplicate state/policy |
| LiteLLM | فعلاً خیر | multi-provider router | فقط پشت Model Router در آینده | duplicate gateway/fallback policy |
| Pinecone/managed RAG | خیر | cloud vector/RAG | incompatible with data residency | cloud dependency |
| Milvus/Weaviate/Chroma | خیر فعلی | alternate vector DB | unnecessary service/ops | Docker/native complexity |

---

## 5. معماری پیشنهادی نهایی

```text
Customer document
  -> document intake policy + checksum
  -> Docling worker
       -> PaddleOCR for fa/ar scans
       -> Unstructured fallback
  -> canonical structured document + provenance
  -> safe chunker
  -> central Qwen3 embedding service
  -> PostgreSQL/pgvector
       (dense + FTS + ACL metadata + snapshot version)

User query
  -> Company Assistant authorization / FGA / company scope
  -> exact identifier detector
  -> pgvector HNSW iterative scan + PostgreSQL FTS
  -> dedup top-50
  -> Qwen3 reranker top-50 -> top-5/10
  -> citation-safe excerpts with page/heading/table provenance
  -> approved LLM context
  -> response + citations + audit

Operational plane
  -> Redis lease/queue
  -> vLLM /metrics
  -> Prometheus/Grafana/exporters
  -> pgBackRest + WAL/PITR
```

---

## 6. برنامهٔ اجرای بدون framework جدید

### مرحلهٔ 1 — کم‌ریسک و فوری

- نسخهٔ vLLM و CUDA مخصوص DGX را pin و روی خود device validate کنید.
- pgvector را به نسخهٔ certified ارتقا دهید و iterative HNSW scan را فعال کنید.
- Prometheus/Grafana و exporters را native نصب کنید.
- Qwen3-Embedding-0.6B را با golden set فارسی/انگلیسی/identifier benchmark کنید.
- pgBackRest و restore drill را نصب کنید.

### مرحلهٔ 2 — بیشترین gain کیفیت

- Docling worker را اضافه کنید.
- PaddleOCR فارسی/عربی را به‌عنوان OCR انتخابی/خودکار اضافه کنید.
- provenance را تا page/heading/table/bbox حفظ کنید.
- Qwen3-Reranker-0.6B را برای top-50 candidate آزمایش کنید.

### مرحلهٔ 3 — certification

برای حداقل این دسته‌ها golden set بسازید:

- فارسی اداری؛
- انگلیسی؛
- code/SKU/identifier؛
- جدول و فرم؛
- scanned Persian؛
- ACL دو شرکت/دو department؛
- revoked grant؛
- answer بدون context کافی؛
- citation page/section.

معیارها:

- extraction accuracy و table cell accuracy؛
- Recall@5/10/50؛
- MRR و nDCG@10؛
- citation precision؛
- grounded answer rate؛
- ACL leakage = صفر؛
- p50/p95/p99 retrieval و rerank؛
- p50/p95/p99 TTFT/TPOT/E2E؛
- vLLM waiting/running/KV/preemption؛
- GPU/CPU/unified-memory pressure؛
- Redis/PostgreSQL lock/query/error؛
- backup restore RTO/RPO.

---

## 7. نکتهٔ حیاتی دربارهٔ «۱۰۰ concurrent»

هیچ ابزار آماده‌ای یک DGX Spark را به‌طور جادویی به ۱۰۰ inference فعال با latency ثابت تبدیل نمی‌کند. ۱۰۰ concurrent باید به‌عنوان **۱۰۰ ورودی هم‌زمان که queue و continuous batching آن‌ها را مدیریت می‌کند** تعریف شود؛ نه اینکه الزاماً هر ۱۰۰ درخواست هم‌زمان روی GPU decode شوند.

مستندات رسمی vLLM نیز برای DGX Spark آن را بیشتر مناسب single-user/small-batch می‌داند و توصیه می‌کند `max-num-seqs` پایین بماند. پس اگر benchmark نشان داد p95 یا error rate در ۱۰۰ درخواست قابل قبول نیست، راه‌حل‌های واقعی عبارت‌اند از:

- مدل کوچک‌تر یا quantization مناسب؛
- کاهش context/max output؛
- reranker CPU یا rerank انتخابی؛
- جداکردن embedding/rerank از chat؛
- دستگاه دوم یا multi-node؛
- admission policy شفاف، نه افزایش صوری queue.

---

## 8. نتیجهٔ نهایی

**بله، می‌شود تقریباً تمام قابلیت‌های مهم را با ابزارهای آماده یکپارچه کرد؛ اما نه با اضافه‌کردن یک framework بزرگ و جایگزین‌کردن هستهٔ فعلی.** ترکیب پیشنهادی نهایی:

> **vLLM + Qwen3 Embedding/Reranker + Docling + PaddleOCR + PostgreSQL/pgvector + Redis + Prometheus/Grafana + pgBackRest**

این stack هم native/systemd قابل اجراست، هم با دادهٔ محلی و ACL مرکزی سازگار است، هم کمترین تکرار معماری را دارد. Qdrant/OpenSearch/Haystack/LlamaIndex/LiteLLM گزینه‌های معتبر هستند، اما فقط برای thresholdهای مشخص و با evidence وارد شوند؛ نصب فوری آن‌ها سرعت توسعه را بیشتر نمی‌کند و در این پروژه احتمالاً سخت‌ترش می‌کند.

**مرز صداقت:** این research قابلیت‌های رسمی ابزارها و مسیر integration را مشخص می‌کند؛ کیفیت واقعی فارسی، planner، latency و ظرفیت همچنان باید روی corpus و DGX هدف benchmark شود.
