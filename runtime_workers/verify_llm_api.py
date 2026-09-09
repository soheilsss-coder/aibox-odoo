#!/usr/bin/env python3
"""End-to-end check of the configured LLM API, with the raw output printed.

Answers one question precisely: *is the API the appliance is pointing at
actually reachable and speaking the dialect we expect?* It does that by making
the same calls the gateway makes and printing what came back - status code,
headers, full JSON body, latency, token counts - instead of a bare PASS/FAIL.

Checks, in order:
    1. GET  {api_base}/models                - is the endpoint alive at all
    2. POST {api_base}/chat/completions      - the real generation path
    3. POST {api_base}/chat/completions      - the same call with stream=true
    4. POST {embedding_base}/embeddings      - the RAG path, incl. dimension

Exit code is 0 only when the checks that were *requested* all passed, so this
is usable as a deploy gate.

Examples:
    python runtime_workers/verify_llm_api.py
    python runtime_workers/verify_llm_api.py --verbose
    AI_LLM_API_BASE=https://api.openai.com/v1 AI_LLM_API_KEY=sk-... \
        python runtime_workers/verify_llm_api.py --no-embeddings
    python runtime_workers/verify_llm_api.py --timeout 30 --prompt "سلام، خودت رو معرفی کن"
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm_api_config import _resolve_key, load_config  # noqa: E402

# The appliance pins TLS verification on. An appliance that silently accepts a
# bad certificate for its LLM traffic would leak prompts to whoever is
# intercepting, so this script keeps verification on and reports the failure
# rather than retrying insecurely.
_SSL_CONTEXT = ssl.create_default_context()

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def _c(text: str, color: str, enabled: bool) -> str:
    return "%s%s%s" % (color, text, RESET) if enabled else text


class Report:
    def __init__(self, color: bool):
        self.color = color
        self.results = []

    def step(self, title: str):
        print("\n%s" % _c("── %s " % title.ljust(66, "─"), DIM, self.color))

    def ok(self, name: str, detail: str = ""):
        self.results.append((True, name, detail))
        print("%s %s%s" % (_c("PASS", GREEN, self.color), name,
                           _c("  %s" % detail, DIM, self.color) if detail else ""))

    def fail(self, name: str, detail: str = ""):
        self.results.append((False, name, detail))
        print("%s %s%s" % (_c("FAIL", RED, self.color), name,
                           ("  %s" % detail) if detail else ""))

    def warn(self, name: str, detail: str = ""):
        print("%s %s%s" % (_c("WARN", YELLOW, self.color), name,
                           ("  %s" % detail) if detail else ""))

    def info(self, text: str):
        print("     %s" % text)

    def summary(self) -> int:
        passed = sum(1 for good, _, _ in self.results if good)
        total = len(self.results)
        print("\n%s" % _c("─" * 72, DIM, self.color))
        color = GREEN if passed == total else RED
        print(_c("%d/%d checks passed" % (passed, total), color, self.color))
        for good, name, detail in self.results:
            if not good:
                print("  %s %s — %s" % (_c("FAILED", RED, self.color), name, detail))
        return 0 if passed == total else 1


def _request(url: str, payload: Optional[dict], api_key: str, timeout: float,
             stream: bool = False) -> Tuple[int, Dict[str, str], bytes, float]:
    """Return (status, headers, body, elapsed_seconds)."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer %s" % api_key
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            body = resp.read()
            return resp.status, dict(resp.headers), body, time.time() - started
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read(), time.time() - started
    except (urllib.error.URLError, ssl.SSLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return 0, {}, ("transport error: %s" % reason).encode("utf-8"), time.time() - started
    except Exception as exc:  # noqa: BLE001 - report, never crash the gate
        return 0, {}, ("unexpected error: %r" % (exc,)).encode("utf-8"), time.time() - started


def _pretty(body: bytes, limit: int = 4000) -> str:
    try:
        text = json.dumps(json.loads(body.decode("utf-8")), ensure_ascii=False, indent=2)
    except (ValueError, UnicodeDecodeError):
        text = body.decode("utf-8", "replace")
    if len(text) > limit:
        text = text[:limit] + "\n... [truncated %d chars]" % (len(text) - limit)
    return text


def _show(report: Report, status: int, headers: Dict[str, str], body: bytes,
          elapsed: float, verbose: bool, expected: Tuple[int, ...] = (200,)) -> Optional[dict]:
    label = "%d in %d ms" % (status, round(elapsed * 1000))
    if status in expected:
        report.ok(label)
    else:
        report.fail(label)
    if verbose or status not in expected:
        for key in ("content-type", "x-request-id", "x-ratelimit-remaining-requests",
                    "openai-model", "anthropic-ratelimit-requests-remaining"):
            if key in headers:
                report.info("%s: %s" % (key, headers[key]))
        print(_pretty(body))
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def check_models(report: Report, base: str, key: str, timeout: float, verbose: bool) -> bool:
    report.step("1. GET %s/models" % base)
    status, headers, body, elapsed = _request(base.rstrip("/") + "/models", None, key, timeout)
    data = _show(report, status, headers, body, elapsed, verbose)
    if status != 200:
        return False
    ids = [m.get("id") for m in (data or {}).get("data", []) if isinstance(m, dict)]
    report.info("%d models advertised: %s" % (len(ids), ", ".join(ids[:10]) or "(none)"))
    return True


def check_chat(report: Report, base: str, key: str, model: str, prompt: str,
               timeout: float, verbose: bool) -> bool:
    report.step("2. POST %s/chat/completions  (model=%s)" % (base, model))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are the company assistant. Answer briefly."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 200,
        "temperature": 0.2,
        "stream": False,
    }
    report.info("request payload: %s" % json.dumps(payload, ensure_ascii=False)[:600])
    status, headers, body, elapsed = _request(base.rstrip("/") + "/chat/completions",
                                             payload, key, timeout)
    data = _show(report, status, headers, body, elapsed, verbose)
    if status != 200 or not data:
        return False
    try:
        message = data["choices"][0]["message"]["content"] or ""
        finish = data["choices"][0].get("finish_reason")
        usage = data.get("usage") or {}
    except (KeyError, IndexError, TypeError) as exc:
        report.fail("response is not shaped like a chat completion", str(exc))
        return False
    report.ok("assistant replied (%d chars, finish_reason=%s)" % (len(message), finish))
    print("\n%s\n%s\n%s" % (_c("─" * 20 + " model output " + "─" * 20, DIM, report.color),
                            message, _c("─" * 54, DIM, report.color)))
    if usage:
        report.info("usage: prompt=%s completion=%s total=%s"
                    % (usage.get("prompt_tokens"), usage.get("completion_tokens"),
                       usage.get("total_tokens")))
    return True


def check_stream(report: Report, base: str, key: str, model: str, prompt: str,
                 timeout: float, verbose: bool) -> bool:
    report.step("3. POST %s/chat/completions  (stream=true)" % base)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 120,
        "stream": True,
    }
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if key:
        headers["Authorization"] = "Bearer %s" % key
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions",
                                data=json.dumps(payload).encode("utf-8"),
                                headers=headers, method="POST")
    started = time.time()
    chunks = 0
    text_parts = []
    first_token_ms = None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            ctype = resp.headers.get("content-type", "")
            report.info("HTTP %d, content-type=%s" % (resp.status, ctype))
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunks += 1
                if first_token_ms is None:
                    first_token_ms = (time.time() - started) * 1000
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0].get("delta") or {}
                    text_parts.append(delta.get("content") or "")
                except (ValueError, KeyError, IndexError):
                    continue
    except urllib.error.HTTPError as exc:
        report.fail("HTTP %d" % exc.code, exc.read().decode("utf-8", "replace")[:500])
        return False
    except Exception as exc:  # noqa: BLE001
        report.fail("streaming request failed", repr(exc))
        return False

    if chunks == 0:
        report.fail("no SSE chunks received")
        return False
    report.ok("%d chunks, first token in %d ms, total %d ms"
              % (chunks, round(first_token_ms or 0), round((time.time() - started) * 1000)))
    if verbose:
        print("".join(text_parts))
    return True


def check_embeddings(report: Report, base: str, key: str, model: str,
                     expected_dim: int, timeout: float, verbose: bool) -> bool:
    report.step("4. POST %s/embeddings  (model=%s)" % (base, model))
    payload = {"model": model, "input": ["قرارداد شماره ۱۴۰۳", "quarterly sales report"]}
    status, headers, body, elapsed = _request(base.rstrip("/") + "/embeddings",
                                             payload, key, timeout)
    data = _show(report, status, headers, body, elapsed, verbose)
    if status != 200 or not data:
        return False
    items = data.get("data") or []
    if not items:
        report.fail("no embeddings returned")
        return False
    dims = {len(item.get("embedding") or []) for item in items}
    report.info("vectors=%d dimensions=%s" % (len(items), sorted(dims)))
    if len(dims) != 1:
        report.fail("inconsistent embedding dimensions", str(sorted(dims)))
        return False
    dim = dims.pop()
    if expected_dim and dim != expected_dim:
        report.warn(
            "dimension %d != AI_EMBEDDING_DIM %d — set AI_EMBEDDING_DIM=%d before "
            "indexing or existing vectors will be rejected" % (dim, expected_dim, dim)
        )
        report.info("export AI_EMBEDDING_DIM=%d" % dim)
    else:
        report.ok("dimension %d matches AI_EMBEDDING_DIM" % dim)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the configured LLM API endpoint")
    parser.add_argument("--prompt", default="Say 'AIBOX LLM link verified' and nothing else.")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--verbose", action="store_true", help="print full response bodies")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--no-embeddings", action="store_true",
                        help="skip the embedding check (chat-only vendors)")
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument("--json", action="store_true", help="also dump the resolved config as JSON")
    args = parser.parse_args()

    color = sys.stdout.isatty() and not args.no_color
    report = Report(color)

    cfg = load_config()
    chat_key, key_source = _resolve_key(cfg.chat.provider, dict(os.environ),
                                       (os.environ.get("AI_LLM_API_KEY") or "").strip())
    emb_key = (os.environ.get("AI_EMBEDDING_API_KEY") or chat_key or "").strip()

    print(_c("AIBOX LLM API VERIFICATION", DIM, color))
    print("  chat      : %s  ->  %s  [%s]" % (cfg.chat.provider, cfg.chat.api_base, cfg.chat.model))
    print("              service=%s key=%s (%s)"
          % (cfg.chat.service, "set" if chat_key else "MISSING", key_source))
    print("  embedding : %s  ->  %s  [%s]  key=%s"
          % (cfg.embedding.provider, cfg.embedding.api_base, cfg.embedding.model,
             "set" if emb_key else "MISSING"))
    print("  budget    : latency<= %d ms, max_output_tokens=%d"
          % (cfg.latency_budget_ms, cfg.max_output_tokens))
    for note in cfg.notes:
        report.info(note)
    if args.json:
        print(json.dumps(cfg.describe(), ensure_ascii=False, indent=2))

    if not cfg.chat.api_base:
        report.fail("no chat endpoint configured", "set AI_LLM_API_BASE")
        return report.summary()
    if not chat_key:
        report.warn("no chat API key", "some self-hosted endpoints accept an empty key")

    check_models(report, cfg.chat.api_base, chat_key, args.timeout, args.verbose)
    check_chat(report, cfg.chat.api_base, chat_key, cfg.chat.model, args.prompt,
               args.timeout, args.verbose)
    if not args.no_stream:
        check_stream(report, cfg.chat.api_base, chat_key, cfg.chat.model, args.prompt,
                     args.timeout, args.verbose)
    if not args.no_embeddings and cfg.embedding and cfg.embedding.api_base:
        expected_dim = 0
        try:
            expected_dim = int(os.environ.get("AI_RAG_EMBEDDING_DIM")
                               or os.environ.get("AI_EMBEDDING_DIM") or 0)
        except ValueError:
            expected_dim = 0
        check_embeddings(report, cfg.embedding.api_base, emb_key, cfg.embedding.model,
                         expected_dim, args.timeout, args.verbose)
    elif not args.no_embeddings:
        report.warn("embedding check skipped", "no embedding endpoint configured")

    return report.summary()


if __name__ == "__main__":
    raise SystemExit(main())
