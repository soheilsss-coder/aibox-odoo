#!/usr/bin/env python3
"""Fail closed unless a real serving and system evidence report passes.

This gate intentionally has no optimistic defaults. It is a deployment-time
check, not a build-time claim: run it against a benchmark report generated on
the target machine and enrich ``system_evidence`` with GPU, queue, database
and Redis observations from the same run.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def number(value, label):
    if not isinstance(value, (int, float)):
        raise ValueError(f"missing numeric metric: {label}")
    return float(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--max-p95-ttft-ms", type=float, default=float(os.getenv("AI_MAX_P95_TTFT_MS", "0")))
    parser.add_argument("--max-p95-e2e-ms", type=float, default=float(os.getenv("AI_MAX_P95_E2E_MS", "0")))
    parser.add_argument("--max-error-rate", type=float, default=float(os.getenv("AI_MAX_ERROR_RATE", "0")))
    parser.add_argument("--min-completed", type=int, default=int(os.getenv("AI_MIN_COMPLETED", "1")))
    args = parser.parse_args()

    try:
        report = json.loads(args.report.read_text())
    except (OSError, TypeError, ValueError) as exc:
        print("CAPACITY GATE: FAIL")
        print(f"- invalid benchmark report: {type(exc).__name__}")
        return 1
    if not isinstance(report, dict):
        print("CAPACITY GATE: FAIL")
        print("- benchmark report must be a JSON object")
        return 1
    failures = []
    summary = report.get("summary") or {}
    ttft_p95 = number((summary.get("ttft_ms") or {}).get("p95"), "summary.ttft_ms.p95")
    e2e_p95 = number((summary.get("e2e_ms") or {}).get("p95"), "summary.e2e_ms.p95")
    error_rate = number(summary.get("error_rate"), "summary.error_rate")
    completed = int(summary.get("completed", 0))

    # A zero threshold means "not configured", which is deliberately a
    # failure rather than an accidental unlimited threshold.
    for value, threshold, label in (
        (ttft_p95, args.max_p95_ttft_ms, "p95 TTFT"),
        (e2e_p95, args.max_p95_e2e_ms, "p95 end-to-end latency"),
    ):
        if threshold <= 0 or value > threshold:
            failures.append(f"{label} {value} exceeds/unconfigured threshold {threshold}")
    if error_rate < 0 or error_rate > 1 or error_rate > args.max_error_rate:
        failures.append(f"error rate {error_rate} exceeds/invalid against {args.max_error_rate}")
    if completed < args.min_completed:
        failures.append(f"completed requests {completed} is below {args.min_completed}")

    evidence = report.get("system_evidence") or {}
    for key in ("gpu_metrics", "queue_metrics", "db_redis_metrics"):
        if not evidence.get(key):
            failures.append(f"missing same-run system evidence: {key}")

    if failures:
        print("CAPACITY GATE: FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("CAPACITY GATE: PASS (bounded to the measured workload and environment)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
