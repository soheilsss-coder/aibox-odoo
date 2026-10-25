#!/usr/bin/env python3
"""Measure the real OpenAI-compatible serving path without claiming capacity.

Run this on the target host after the native serving units and the actual
model revision are healthy. It intentionally writes to /tmp by default so
responses, caches and benchmark artifacts do not enter the release workspace.
The companion ``61_v58_capacity_gate.py`` turns an evidence file into a
pass/fail decision; this script alone is measurement, not certification.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import os
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


SCENARIOS = {
    "chat": "Answer the user's short business question accurately and concisely.",
    "tool": "Decide whether a read-only task status lookup is needed. Do not mutate data.",
    "rag": "Answer using the provided document context and say when the context is insufficient.",
    "approval": "Explain that a high-risk write requires an explicit human approval before execution.",
    "vision": "Describe the supplied image conservatively and say when visual evidence is insufficient.",
    "embedding": "Create a stable semantic representation for this short business sentence.",
}

# A generated-in-memory 1x1 image keeps the benchmark self-contained; no image
# or model artifact is written to this repository.
_VISION_DATA_URI = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63606060000000040001f61738550000000049454e44ae426082")
).decode("ascii")


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return round(ordered[index], 3)


def scenario_payload(scenario: str, model: str, prompt: str, max_tokens: int) -> dict:
    user_content = prompt
    if scenario == "vision":
        user_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _VISION_DATA_URI}},
        ]
    messages = [
        {"role": "system", "content": SCENARIOS[scenario]},
        {"role": "user", "content": user_content},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if scenario == "tool":
        payload["tools"] = [{
            "type": "function",
            "function": {
                "name": "get_task_status",
                "description": "Read the status of one task without changing it.",
                "parameters": {
                    "type": "object",
                    "properties": {"task_id": {"type": "integer"}},
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
            },
        }]
        payload["tool_choice"] = "auto"
    return payload


def one_request(endpoint: str, model: str, scenario: str, prompt: str,
                max_tokens: int, timeout: float) -> dict:
    request_id = uuid.uuid4().hex
    started = time.perf_counter()
    first_byte = None
    chunks = 0
    output_chars = 0
    provider_output_tokens = None
    try:
        if scenario == "embedding":
            body = json.dumps({"model": model, "input": [prompt]}).encode("utf-8")
            request = Request(
                endpoint,
                data=body,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=timeout) as response:
                first_byte = time.perf_counter()
                parsed = json.loads(response.read().decode("utf-8"))
                vectors = parsed.get("data") or []
                if not vectors or not isinstance(vectors[0].get("embedding"), list):
                    raise ValueError("embedding response has no vector")
                embedding_dimension = len(vectors[0]["embedding"])
                status_code = response.status
            finished = time.perf_counter()
            return {
                "request_id": request_id,
                "ok": True,
                "status_code": status_code,
                "ttft_ms": round((first_byte - started) * 1000, 3),
                "e2e_ms": round((finished - started) * 1000, 3),
                "tpot_ms": 0.0,
                "output_tokens": 0,
                "embedding_dimension": embedding_dimension,
                "stream_chunks": 0,
            }
        body = json.dumps(scenario_payload(scenario, model, prompt, max_tokens)).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            headers={"Accept": "text/event-stream", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", "replace").strip()
                if line.startswith("data:") and line[5:].strip() != "[DONE]":
                    chunks += 1
                    if first_byte is None:
                        first_byte = time.perf_counter()
                    try:
                        event = json.loads(line[5:].strip())
                        usage = event.get("usage") or {}
                        if usage.get("completion_tokens") is not None:
                            provider_output_tokens = int(usage["completion_tokens"])
                        for choice in event.get("choices") or []:
                            delta = choice.get("delta") or {}
                            output_chars += len(str(delta.get("content") or ""))
                            for call in delta.get("tool_calls") or []:
                                output_chars += len(str((call.get("function") or {}).get("arguments") or ""))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
            status_code = response.status
        finished = time.perf_counter()
        ttft_ms = ((first_byte or finished) - started) * 1000
        e2e_ms = (finished - started) * 1000
        output_tokens = provider_output_tokens or max(1, output_chars // 4)
        return {
            "request_id": request_id,
            "ok": True,
            "status_code": status_code,
            "ttft_ms": round(ttft_ms, 3),
            "e2e_ms": round(e2e_ms, 3),
            "tpot_ms": round(max(0.0, e2e_ms - ttft_ms) / max(output_tokens, 1), 3),
            "output_tokens": output_tokens,
            "output_token_source": "provider_usage" if provider_output_tokens else "estimated_chars_div_4",
            "stream_chunks": chunks,
        }
    except Exception as exc:  # noqa: BLE001 - benchmark must record per-request failures
        return {
            "request_id": request_id,
            "ok": False,
            "ttft_ms": None,
            "e2e_ms": round((time.perf_counter() - started) * 1000, 3),
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        }


def run(args: argparse.Namespace) -> dict:
    endpoint = args.endpoint.rstrip("/")
    prompts = [
        "What are the next actions for the operations team?",
        "Summarize the request and identify any missing information.",
        "Which records should be reviewed before the deadline?",
        "Give a concise, actionable answer for the employee.",
    ]
    for _ in range(args.warmup):
        result = one_request(endpoint, args.model, args.scenario, prompts[0], args.max_tokens, args.timeout)
        if not result["ok"]:
            raise SystemExit(f"warmup failed: {result.get('error')}")

    jobs = [prompts[i % len(prompts)] for i in range(args.requests)]
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(one_request, endpoint, args.model, args.scenario, prompt,
                               args.max_tokens, args.timeout) for prompt in jobs]
        results = [future.result() for future in futures]
    elapsed = time.perf_counter() - started

    good = [item for item in results if item["ok"]]
    ttft = [item["ttft_ms"] for item in good if item["ttft_ms"] is not None]
    e2e = [item["e2e_ms"] for item in good]
    tpot = [item["tpot_ms"] for item in good if item.get("tpot_ms") is not None]
    return {
        "schema_version": 1,
        "benchmark": "v58-native-llm-serving",
        "created_at_epoch": time.time(),
        "endpoint": endpoint,
        "model_alias": args.model,
        "scenario": args.scenario,
        "requests": args.requests,
        "warmup": args.warmup,
        "concurrency": args.concurrency,
        "max_tokens": args.max_tokens,
        "elapsed_s": round(elapsed, 3),
        "throughput_requests_per_second": round(len(good) / elapsed, 3) if elapsed else 0,
        "summary": {
            "completed": len(good),
            "failed": len(results) - len(good),
            "error_rate": round((len(results) - len(good)) / len(results), 6) if results else 1,
            "ttft_ms": {"p50": percentile(ttft, 0.50), "p95": percentile(ttft, 0.95), "p99": percentile(ttft, 0.99)},
            "e2e_ms": {"p50": percentile(e2e, 0.50), "p95": percentile(e2e, 0.95), "p99": percentile(e2e, 0.99)},
            "tpot_ms": {"p50": percentile(tpot, 0.50), "p95": percentile(tpot, 0.95), "p99": percentile(tpot, 0.99)},
        },
        "results": results,
        # These fields must be populated by an evidence collector on the
        # target host before the capacity gate can certify production.
        "system_evidence": {
            "gpu_metrics": None,
            "queue_metrics": None,
            "db_redis_metrics": None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.getenv("AI_BENCHMARK_ENDPOINT", ""))
    parser.add_argument("--model", default=os.getenv("AI_BENCHMARK_MODEL", ""))
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="chat")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", default="/tmp/ai-v58-llm-benchmark.json")
    args = parser.parse_args()
    if not args.model:
        args.model = {"embedding": "embedding-model", "vision": "vision-model"}.get(args.scenario, "local-model")
    if not args.endpoint:
        port = {"embedding": 8002, "vision": 8001}.get(args.scenario, 8000)
        path = "/v1/embeddings" if args.scenario == "embedding" else "/v1/chat/completions"
        args.endpoint = "http://127.0.0.1:%d%s" % (port, path)
    if args.requests < 1 or args.requests > 10000 or args.concurrency < 1 or args.concurrency > args.requests:
        parser.error("requests must be 1..10000 and concurrency must be positive and no greater than requests")
    if args.warmup < 0 or args.warmup > 100 or args.max_tokens < 1 or args.timeout <= 0:
        parser.error("warmup, max-tokens and timeout must be positive bounded values")
    report = run(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    print(f"benchmark evidence written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
