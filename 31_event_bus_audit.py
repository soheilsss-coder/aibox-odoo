#!/usr/bin/env python3
"""Static audit for the durable event bus release."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent / "custom_addons"
required = [
    ROOT / "ai_control_plane/models/event.py",
    ROOT / "ai_integration/models/event_dispatch.py",
    ROOT / "ai_integration/security/ir.model.access.csv",
    ROOT / "ai_integration/data/cron_data.xml",
    ROOT / "ai_integration/data/adapter_data.xml",
]
for p in required:
    assert p.exists(), f"missing: {p}"

for p in ROOT.rglob("*.py"):
    ast.parse(p.read_text(encoding="utf-8"), filename=str(p))

event = (ROOT / "ai_control_plane/models/event.py").read_text()
dispatch = (ROOT / "ai_integration/models/event_dispatch.py").read_text()
assert "FOR UPDATE SKIP LOCKED" in dispatch
assert "idempotency_key" in dispatch
assert "dead_letter" in dispatch
assert "locked_at" in dispatch
assert "correlation_id" in event
assert "causation_id" in event
assert "event_key_unique" in event

# The task automation must publish through the durable event outbox,
# not directly to Odoo's realtime bus.
task = (ROOT / "ai_business_tools/models/task_automation.py").read_text()
assert 'self.env["ai.control.event"].publish' in task
assert '"ai_task_event"' not in task

print("EVENT_BUS_AUDIT: PASS")
