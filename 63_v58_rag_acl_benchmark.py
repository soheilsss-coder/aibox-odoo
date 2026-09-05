#!/usr/bin/env python3
"""Measure the live Persian RAG endpoint and its ACL boundary.

This is intentionally a local-appliance benchmark. It sends only the supplied
queries to the configured Odoo endpoint, never to a cloud service, and stores
counts/timings rather than document excerpts. Run it on the customer host
with a restricted API key and forbidden document markers appropriate to that
fixture. It is evidence, not a production-capacity claim.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import socket
import statistics
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_QUERIES = [
    "شرایط مرخصی سالانه و نحوه محاسبه مانده آن چیست؟",
    "آخرین مهلت تأیید درخواست خرید چه زمانی است؟",
    "برای گزارش فروش ماهانه کدام اطلاعات لازم است؟",
    "اگر اطلاعات کافی در اسناد وجود ندارد، صریحاً اعلام کن.",
]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * fraction))))
    return round(values[index], 3)


def _local_endpoint(endpoint: str) -> bool:
    host = (urlparse(endpoint).hostname or "").casefold()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress_is_private(host)
    except ValueError:
        return False


def ipaddress_is_private(host: str) -> bool:
    import ipaddress
    return ipaddress.ip_address(host).is_private


def one_request(endpoint: str, api_key: str, query: str, timeout: float,
                forbidden: tuple[str, ...], expected: tuple[str, ...]) -> dict:
    started = time.perf_counter()
    try:
        body = json.dumps({"query": query, "top_k": 8}, ensure_ascii=False).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-API-Key": api_key,
            },
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            status = response.status
        results = payload.get("results") if isinstance(payload, dict) else None
        results = results if isinstance(results, list) else []
        # Do not write excerpts or document ids to the evidence file. Names
        # are only compared to caller-provided fixture markers in memory.
        names = [str(item.get("document_name") or "") for item in results if isinstance(item, dict)]
        forbidden_seen = any(marker.casefold() in name.casefold() for marker in forbidden for name in names)
        expected_seen = any(marker.casefold() in name.casefold() for marker in expected for name in names)
        return {
            "ok": 200 <= status < 300 and not forbidden_seen,
            "status_code": status,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "result_count": len(results),
            "forbidden_seen": forbidden_seen,
            "expected_seen": expected_seen,
        }
    except (HTTPError, URLError, TimeoutError, socket.timeout, ValueError) as exc:
        return {
            "ok": False,
            "status_code": getattr(exc, "code", None),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "error_type": type(exc).__name__,
        }


def run(args: argparse.Namespace) -> dict:
    queries = args.query or DEFAULT_QUERIES
    jobs = [queries[index % len(queries)] for index in range(args.requests)]
    forbidden = tuple(args.forbidden_document_name or ())
    expected = tuple(args.expected_document_name or ())
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(one_request, args.endpoint, args.api_key, query,
                               args.timeout, forbidden, expected) for query in jobs]
        results = [future.result() for future in futures]
    elapsed = time.perf_counter() - started
    successful = [result for result in results if result["ok"]]
    latencies = [result["latency_ms"] for result in results]
    violations = sum(1 for result in results if result.get("forbidden_seen"))
    expected_checks = sum(1 for result in results if result.get("expected_seen"))
    return {
        "schema_version": 1,
        "benchmark": "v58-local-persian-rag-acl",
        "endpoint": args.endpoint,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "elapsed_s": round(elapsed, 3),
        "queries_are_persian_fixture": True,
        "acl_fixture": {
            "forbidden_marker_count": len(forbidden),
            "expected_marker_count": len(expected),
            "forbidden_leak_violations": violations,
            "expected_marker_hits": expected_checks,
        },
        "summary": {
            "completed": len(successful),
            "failed": len(results) - len(successful),
            "error_rate": round((len(results) - len(successful)) / len(results), 6) if results else 1,
            "latency_ms": {
                "p50": percentile(latencies, 0.50),
                "p95": percentile(latencies, 0.95),
                "p99": percentile(latencies, 0.99),
            },
            "mean_latency_ms": round(statistics.fmean(latencies), 3) if latencies else None,
        },
        "results": results,
        "limitations": [
            "Recall/precision requires a labeled customer fixture; marker hits are not a quality score.",
            "Run separately for each ACL persona/company and compare forbidden markers.",
            "This report does not certify model quality, p95 capacity, or production readiness.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.getenv("AI_RAG_BENCHMARK_ENDPOINT", "http://127.0.0.1:8069/api/documents/search"))
    parser.add_argument("--api-key", default=os.getenv("AI_RAG_BENCHMARK_API_KEY", ""))
    parser.add_argument("--query", action="append", help="Persian query; repeat for a labeled fixture")
    parser.add_argument("--forbidden-document-name", action="append", default=[], help="Marker that must never appear for this API key")
    parser.add_argument("--expected-document-name", action="append", default=[], help="Optional marker expected in authorized results")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", default="/tmp/ai-v58-persian-rag-acl.json")
    parser.add_argument("--allow-nonlocal-endpoint", action="store_true")
    args = parser.parse_args()
    if not args.api_key:
        parser.error("--api-key or AI_RAG_BENCHMARK_API_KEY is required")
    if not args.allow_nonlocal_endpoint and not _local_endpoint(args.endpoint):
        parser.error("endpoint must be localhost/private appliance; use --allow-nonlocal-endpoint only for an explicitly approved lab")
    if args.requests < 1 or args.requests > 10000 or args.concurrency < 1 or args.concurrency > args.requests:
        parser.error("requests must be 1..10000 and concurrency must be positive and no greater than requests")
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    report = run(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    print(f"local Persian RAG/ACL evidence written to {output}")
    return 0 if report["summary"]["failed"] == 0 and report["acl_fixture"]["forbidden_leak_violations"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
