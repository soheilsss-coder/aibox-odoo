"""Static invariants for v44 RAG/Event integration."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAG = ROOT / "custom_addons" / "ai_rag"

checks = {
    "rag_subscriber_exists": (RAG / "models/event_subscriber.py").exists(),
    "rag_event_subscriptions": (RAG / "data/event_subscriptions.xml").exists(),
    "document_create_publishes_event": 'event_type="document.created"' in (RAG / "models/rag_index.py").read_text(),
    "document_update_publishes_event": 'event_type="document.updated"' in (RAG / "models/rag_index.py").read_text(),
    "no_direct_enqueue_in_document_create_write": 'self.env["ai.document.index.job"].enqueue(doc)' not in (RAG / "models/rag_index.py").read_text().split('def cron_reindex_stale_documents', 1)[0],
    "embedding_stays_in_async_job": 'def _rag_reindex' in (RAG / "models/rag_index.py").read_text() and 'def cron_process' in (RAG / "models/index_job.py").read_text(),
    "explicit_calendar_subscriber": 'ai.integration.calendar.subscriber' in (ROOT / "custom_addons/ai_integration/models/event_subscribers.py").read_text(),
    "explicit_memory_subscriber": 'ai.integration.memory.subscriber' in (ROOT / "custom_addons/ai_integration/models/event_subscribers.py").read_text(),
}
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'} {name}")
if not all(checks.values()):
    raise SystemExit(1)
