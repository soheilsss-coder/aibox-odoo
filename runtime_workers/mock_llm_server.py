#!/usr/bin/env python3
"""OpenAI-compatible test double for verifying the appliance without egress.

The production code path is ``llm.provider(service='openai')`` -> OpenAI SDK ->
``{api_base}/chat/completions``. Verifying that path against a real vendor from
a machine with no route to ``api.openai.com`` is impossible, and faking the
Odoo side instead would verify the wrong thing.

So this implements the *other* end of the same contract, byte-for-byte where it
matters:

    GET  /v1/models              -> model list
    POST /v1/chat/completions    -> non-streaming + SSE streaming
    POST /v1/embeddings          -> deterministic vectors of a fixed dimension
    GET  /v1/health              -> what this double received last (debug aid)

Because it speaks the real dialect, swapping ``AI_LLM_API_BASE`` from this
double to ``https://api.openai.com/v1`` changes nothing in the appliance: same
request shape, same response shape. The only difference is that this one runs
offline, answers in milliseconds, and records what it was sent so you can prove
the gateway forwarded the right model, messages and tool schema.

Deliberately NOT implemented: tool execution, function-calling loops, vision
inputs, rate limits. This is a contract double, not a model.

Run:
    python runtime_workers/mock_llm_server.py --port 8000
    python runtime_workers/mock_llm_server.py --port 8002 --served-model embedding-model --embedding-dim 384
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_STATE_LOCK = threading.Lock()
_STATE = {
    "requests": [],       # bounded ring of the last N requests, for debugging
    "count": 0,
    "started_at": time.time(),
}
_MAX_HISTORY = 20


def _record(kind: str, payload: dict) -> None:
    with _STATE_LOCK:
        _STATE["count"] += 1
        _STATE["requests"].append(
            {
                "seq": _STATE["count"],
                "kind": kind,
                "at": time.time(),
                "model": payload.get("model"),
                "stream": bool(payload.get("stream")),
                "n_messages": len(payload.get("messages") or []),
                "n_tools": len(payload.get("tools") or []),
                "tool_names": [
                    (t.get("function") or {}).get("name") for t in (payload.get("tools") or [])
                ],
                "last_user_message": next(
                    (m.get("content") for m in reversed(payload.get("messages") or [])
                     if m.get("role") == "user"),
                    None,
                ),
            }
        )
        if len(_STATE["requests"]) > _MAX_HISTORY:
            del _STATE["requests"][0 : len(_STATE["requests"]) - _MAX_HISTORY]


def _deterministic_vector(text: str, dim: int) -> list:
    """A stable, unit-length vector derived from the text.

    Deterministic on purpose: the same chunk must embed identically across
    index rebuilds, otherwise similarity comparisons between two runs of the
    verification script would be meaningless.
    """
    out = []
    for i in range(dim):
        digest = hashlib.sha256(("%d\x00%s" % (i, text)).encode("utf-8")).digest()
        out.append((int.from_bytes(digest[:4], "big") / 0xFFFFFFFF) * 2.0 - 1.0)
    norm = math.sqrt(sum(v * v for v in out)) or 1.0
    return [v / norm for v in out]


def make_handler(served_model: str, embedding_model: str, embedding_dim: int, latency_ms: int):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # -- plumbing -------------------------------------------------
        def log_message(self, fmt, *args):  # keep stdout readable
            print("[mock-llm] %s" % (fmt % args), flush=True)

        def _send_json(self, obj: dict, status: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}

        # -- routes ---------------------------------------------------
        def do_GET(self):  # noqa: N802 - http.server API
            if self.path.rstrip("/") in ("/v1/models", "/models"):
                return self._send_json(
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": m,
                                "object": "model",
                                "created": int(_STATE["started_at"]),
                                "owned_by": "mock",
                            }
                            for m in {served_model, embedding_model}
                            if m
                        ],
                    }
                )
            if self.path.rstrip("/") in ("/v1/health", "/health", "/"):
                with _STATE_LOCK:
                    snapshot = {
                        "status": "ok",
                        "served_model": served_model,
                        "embedding_model": embedding_model,
                        "embedding_dim": embedding_dim,
                        "requests": _STATE["count"],
                        "uptime_s": round(time.time() - _STATE["started_at"], 1),
                        "recent": list(_STATE["requests"]),
                    }
                return self._send_json(snapshot)
            return self._send_json(
                {"error": {"message": "not found: %s" % self.path, "type": "invalid_request_error"}},
                status=404,
            )

        def do_POST(self):  # noqa: N802 - http.server API
            path = self.path.rstrip("/")
            payload = self._read_json()
            if path.endswith("/chat/completions") or path.endswith("/completions"):
                return self._chat(payload)
            if path.endswith("/embeddings"):
                return self._embed(payload)
            return self._send_json(
                {"error": {"message": "not found: %s" % self.path, "type": "invalid_request_error"}},
                status=404,
            )

        # -- implementations ------------------------------------------
        def _echo_reply(self, payload: dict) -> str:
            """Report exactly what the gateway sent, and say plainly this is a stand-in.

            A test double that quietly pretends to be a model is worse than
            useless: someone reads a plausible sentence and assumes the LLM
            link works. So the reply leads with what it is, then dumps the
            request the appliance actually produced - which is the part worth
            inspecting when a real provider misbehaves.
            """
            messages = payload.get("messages") or []
            system = next((m.get("content") or "" for m in messages if m.get("role") == "system"), "")
            last_user = next(
                (m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"),
                "",
            )
            tools = [
                (t.get("function") or {}).get("name") for t in (payload.get("tools") or [])
            ]
            model = payload.get("model") or served_model
            roles = ", ".join(m.get("role") or "?" for m in messages)
            return (
                "STAND-IN RESPONSE - no real LLM is attached to this endpoint.\n"
                "Point AI_LLM_API_BASE / AI_LLM_API_KEY at a real provider for real answers.\n"
                "\n"
                "--- what the appliance sent ---\n"
                "model        : %s\n"
                "messages     : %d  (%s)\n"
                "tools        : %s\n"
                "max_tokens   : %s   temperature: %s   stream: %s\n"
                "system prompt: %s\n"
                "user message : %s"
                % (
                    model,
                    len(messages),
                    roles or "none",
                    ", ".join(t for t in tools if t) or "none offered",
                    payload.get("max_tokens") or payload.get("max_completion_tokens") or "-",
                    payload.get("temperature", "-"),
                    bool(payload.get("stream")),
                    (system[:300] + ("..." if len(system) > 300 else "")) or "(none)",
                    last_user[:400] or "(none)",
                )
            )

        def _chat(self, payload: dict) -> None:
            _record("chat", payload)
            model = payload.get("model") or served_model
            text = self._echo_reply(payload)
            completion_id = "chatcmpl-%s" % uuid.uuid4().hex[:20]
            if latency_ms:
                time.sleep(latency_ms / 1000.0)

            if payload.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()

                def chunk(delta: dict, finish: str | None = None) -> bytes:
                    obj = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [
                            {"index": 0, "delta": delta, "logprobs": None, "finish_reason": finish}
                        ],
                    }
                    return ("data: %s\n\n" % json.dumps(obj, ensure_ascii=False)).encode("utf-8")

                try:
                    self.wfile.write(chunk({"role": "assistant", "content": ""}))
                    for word in text.split(" "):
                        self.wfile.write(chunk({"content": word + " "}))
                    self.wfile.write(chunk({}, finish="stop"))
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return

            return self._send_json(
                {
                    "id": completion_id,
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": text},
                            "logprobs": None,
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": sum(
                            max(1, len((m.get("content") or "").split()))
                            for m in (payload.get("messages") or [])
                        ),
                        "completion_tokens": len(text.split()),
                        "total_tokens": 0,
                    },
                }
            )

        def _embed(self, payload: dict) -> None:
            _record("embeddings", payload)
            raw = payload.get("input")
            inputs = raw if isinstance(raw, list) else [raw or ""]
            data = [
                {
                    "object": "embedding",
                    "index": i,
                    "embedding": _deterministic_vector(str(t), embedding_dim),
                }
                for i, t in enumerate(inputs)
            ]
            return self._send_json(
                {
                    "object": "list",
                    "data": data,
                    "model": payload.get("model") or embedding_model,
                    "usage": {"prompt_tokens": sum(len(str(t).split()) for t in inputs), "total_tokens": 0},
                }
            )

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--served-model", default="mock-chat-model")
    parser.add_argument("--embedding-model", default="mock-embedding-model")
    parser.add_argument("--embedding-dim", type=int, default=384)
    parser.add_argument("--latency-ms", type=int, default=0,
                        help="artificial per-request latency, to exercise gateway timeouts")
    args = parser.parse_args()

    handler = make_handler(
        args.served_model, args.embedding_model, args.embedding_dim, args.latency_ms
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(
        "[mock-llm] listening on http://%s:%d/v1  chat=%s embedding=%s dim=%d"
        % (args.host, args.port, args.served_model, args.embedding_model, args.embedding_dim),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
