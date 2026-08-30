"""Durable Event Bus worker. Run inside an Odoo shell process."""
import os
import time
while True:
    try:
        env["ai.integration.event.dispatcher"].sudo().dispatch_pending(limit=100)
        env.cr.commit()
    except Exception:
        env.cr.rollback()
    time.sleep(float(os.environ.get("AI_EVENT_WORKER_INTERVAL", "1")))
