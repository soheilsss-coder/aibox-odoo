"""
Observability report (roadmap #48) - run with:
  /opt/odoo/odoo-bin shell -c /opt/odoo.conf -d company_ai < 12_observability_report.py

Prints the same numbers GET /api/metrics returns (both call the same
ai.gateway.audit.log.observability_snapshot() so they can never
disagree) - useful for a quick "is this box healthy" check without
needing a privileged API key or curl, e.g. from a cron that emails
the output, or just by hand before/after a delivery.
"""

if "ai.gateway.audit.log" not in env:
    print("ai_business_tools is not installed - nothing to report.")
else:
    snap = env["ai.gateway.audit.log"].sudo().observability_snapshot()

    print("=== AI Gateway - Observability Snapshot ===")
    print(f"Requests, last hour:   {snap['requests_last_hour']}")
    print(f"Requests, last 24h:    {snap['requests_last_24h']}")
    print(f"Errors, last 24h:      {snap['errors_last_24h']}")
    print(f"Error rate, last 24h:  {snap['error_rate_24h'] * 100:.1f}%")
    avg = snap["avg_duration_ms_24h"]
    print(f"Avg RPC/chat latency:  {f'{avg} ms' if avg is not None else 'n/a (no rpc/chat calls yet)'}")
    print(f"Last call at:          {snap['last_call_at'] or 'never'}")
    print("\nTop actions (last 24h):")
    if not snap["top_actions_24h"]:
        print("  (none)")
    for row in snap["top_actions_24h"]:
        print(f"  {row['action']:<40} {row['calls']}")

    if snap["requests_last_hour"] == 0 and snap["requests_last_24h"] == 0:
        print("\n⚠️  No activity at all in the last 24 hours - if this is a live "
              "deployment (not a fresh demo install), check that the gateway is "
              "actually being called.")
    if snap["error_rate_24h"] > 0.1:
        print(f"\n⚠️  Error rate over 10% in the last 24h ({snap['error_rate_24h'] * 100:.1f}%) - worth investigating.")
