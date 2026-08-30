"""RAG indexing worker. Run inside an Odoo shell process."""
import os, time
while True:
    try:
        env["ai.document.index.job"].sudo().process(limit=10)
        env.cr.commit()
    except Exception:
        env.cr.rollback()
    time.sleep(float(os.environ.get("AI_RAG_WORKER_INTERVAL", "1")))
