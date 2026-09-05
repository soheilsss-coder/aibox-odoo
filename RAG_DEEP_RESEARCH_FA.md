

---

## الحاقیهٔ اجرای مرحلهٔ اول — ۱۴۰۵/۰۶/۱۴

این الحاقیه وضعیت سورس فعلی را به‌روز می‌کند؛ بخش‌های قبلی این فایل نتیجهٔ research اولیه هستند.

### آنچه اکنون در کد پیاده‌سازی شده است

- retrieval به ترتیب `ACL/FGA → dense/FTS/pg_trgm candidates → RRF → reranker اختیاری → citation` اجرا می‌شود؛ raw scoreهای ناهم‌مقیاس مستقیماً با هم جمع نمی‌شوند.
- FTS از ستون materialized `search_vector` و GIN استفاده می‌کند و trigger/backfill دارد؛ `normalized_content` برای فارسی/عربی و trigram حفظ می‌شود.
- HNSW iterative scan در صورت وجود pgvector 0.8+ به‌صورت per-query تنظیم می‌شود و روی نسخه‌های قدیمی graceful fallback دارد.
- reranker فقط بعد از ACL و برای candidateهای محدود اجرا می‌شود؛ profile آن تا benchmark/health check production فعال نمی‌شود.
- memory fact به‌صورت native در Odoo ذخیره می‌شود: value و quote رمزنگاری، scope شرکت/کاربر/دپارتمان، status، confidence، زمان اعتبار، supersession، provenance و embedding version مستقل.
- extraction حافظه asynchronous است: پیام ورودی بعد از پذیرش turn در job صف می‌شود، extractor محلی JSON فقط quote verbatim را قبول می‌کند و نتیجه را `candidate` می‌نویسد. candidate در recall نمایش داده نمی‌شود و فقط با confirmation صریح به `confirmed` می‌رسد.
- برای تغییر مدل/نسخه، migration 1.4 embeddingهای fact را موقتاً `pending` می‌کند؛ vector قدیمی حذف نمی‌شود، اما تا reindex نسخهٔ فعال recall نمی‌شود. این مسیر rollback-safe است.

### benchmark واقعی فارسی و ACL

پس از نصب واقعی Odoo/PostgreSQL/pgvector و سرویس‌های native، benchmark endpoint زیر را برای هر persona و هر company اجرا کنید:

```bash
AI_RAG_BENCHMARK_API_KEY='key-from-secret-manager' \
python3 63_v58_rag_acl_benchmark.py \
  --requests 100 --concurrency 10 \
  --forbidden-document-name 'سند محرمانهٔ منابع انسانی' \
  --expected-document-name 'آیین‌نامه مرخصی' \
  --output /tmp/ai-v58-persian-rag-acl.json
```

این script فقط روی localhost/private appliance مجاز است، متن سند یا ID را در evidence ذخیره نمی‌کند و سه چیز را جدا گزارش می‌دهد: error rate، p50/p95/p99 latency و forbidden-marker leak. marker hit معیار precision/recall نیست؛ برای Recall@k و nDCG باید golden set واقعی مشتری با label صفحه/section ساخته شود. تا اجرای این benchmark و test منفی با دو persona، هیچ ادعای «کیفیت فارسی»، «p95» یا «ظرفیت ۱۰۰ concurrent» معتبر نیست.
