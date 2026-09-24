#!/usr/bin/env python3
"""Nova local brain - an OpenAI-compatible chat endpoint that OPERATES ODOO.

The offline contract double (mock_llm_server.py) proves the wire format but
deliberately never calls tools, so the appliance cannot demonstrate its core
promise ("an assistant that does the work") without egress to a real vendor.

This server closes that gap without pretending to be a neural LLM:

* it speaks the exact same OpenAI dialect (GET /v1/models, POST
  /v1/chat/completions, streaming + non-streaming), so ``llm.provider
  (service='openai')`` talks to it unchanged - swapping AI_LLM_API_BASE to a
  real vendor changes nothing on the Odoo side;
* when the user's request matches a tool the gateway offered, it emits a REAL
  OpenAI ``tool_calls`` response. odoo-llm then executes the actual business
  tool (hr.leave, project.task, ...) and calls back with the tool result -
  records are really created, exactly as with a frontier model;
* when the tool result comes back it summarises it into a friendly answer;
* otherwise it answers honestly: what it can do, and where an admin can plug a
  real LLM key (Admin -> AI Models).

Run:
    python runtime_workers/nova_brain_server.py --port 8000 --served-model nova-local-brain
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
import uuid
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_STATE_LOCK = threading.Lock()
_STATE = {"count": 0, "started_at": time.time(), "last": {}}

# Words that map a user phrase onto a tool-name token.
_SYNONYMS = {
    "leave": ["leave", "vacation", "time off", "holiday", "absence", "off"],
    "task": ["task", "todo", "to-do"],
    "attendance": ["attendance", "check-in", "checkin", "timesheet", "presence"],
    "document": ["document", "documents", "file", "knowledge", "policy", "policies"],
    "customer": ["customer", "client", "partner"],
    "invoice": ["invoice", "bill"],
    "quote": ["quote", "quotation", "estimate"],
    "sale": ["sale", "sales", "order", "sell"],
    "purchase": ["purchase", "buy", "vendor"],
    "project": ["project"],
    "employee": ["employee", "staff", "colleague", "person"],
    "report": ["report", "summary", "how many", "count", "stats"],
    "create": ["create", "new", "add", "request", "book", "make", "register", "submit", "open"],
    "get": ["get", "show", "list", "find", "what", "which", "how"],
    "send": ["send", "email", "mail"],
    "meeting": ["meeting", "calendar", "event", "schedule"],
}


def _split_name(name: str) -> list[str]:
    return [t for t in re.split(r"[_\-\s]|(?<=[a-z])(?=[A-Z])", name or "") if t]


def _tool_tokens(name: str, description: str) -> set[str]:
    tokens = set()
    for part in _split_name(name):
        tokens.add(part.lower())
    for word in re.findall(r"[a-zA-Z]{3,}", description or ""):
        tokens.add(word.lower())
    for group in _SYNONYMS.values():
        for phrase in group:
            if phrase in (name or "").lower() or phrase in (description or "").lower():
                tokens.add(phrase.split()[0])
    return tokens


def _pick_tool(message: str, tools: list[tuple]) -> tuple | None:
    """Score every offered tool against the user's message; return the best."""
    text = " " + re.sub(r"[^a-z0-9\s]", " ", message.lower()) + " "
    best, best_score = None, 0
    for name, description, _schema in tools:
        tokens = _tool_tokens(name, description)
        score = 0
        for token in tokens:
            if token and (" %s " % token) in text:
                score += 2
        for group in _SYNONYMS.values():
            hit_group = any((" %s " % w) in text or w in text for w in group)
            hit_tool = any(t in tokens for t in group)
            if hit_group and hit_tool:
                score += 1
        if score > best_score:
            best, best_score = (name, description, _schema), score
    return best if best_score >= 2 else None


_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}


def _parse_date(message: str, today: date | None = None) -> date | None:
    today = today or date.today()
    text = message.lower()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    if "tomorrow" in text:
        return today + timedelta(days=1)
    if "today" in text:
        return today
    if "next week" in text:
        return today + timedelta(days=8 - today.weekday())
    for word, idx in _WEEKDAYS.items():
        if word in text:
            delta = (idx - today.weekday()) % 7 or 7
            return today + timedelta(days=delta)
    return None


def _parse_span(message: str) -> int:
    m = re.search(r"(\d+)\s*(day|days)", message.lower())
    return max(1, int(m.group(1))) if m else 1


def _extract_title(message: str) -> str:
    m = re.search(r"[\"'']([^\"'']{3,120})[\"'']", message)
    if m:
        return m.group(1).strip()
    m = re.search(r"(?:called|named|titled|about|for)\s+(.{3,120})", message, re.I)
    if m:
        captured = re.split(
            r"\s+(?:for|with|by|until|before|deadline|due|starting|from|assign(?:ed)?\s+to)\s+",
            m.group(1), flags=re.I)[0]
        return captured.strip(" .!?,")
    cleaned = re.sub(r"\s+", " ", message).strip(" .!?")
    return (cleaned[:80] + "...") if len(cleaned) > 83 else cleaned


def _build_arguments(message: str, schema: dict) -> str:
    """Fill a tool's arguments from the message using its JSON schema."""
    args: dict = {}
    props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
    required = schema.get("required") or [] if isinstance(schema, dict) else []
    parsed_date = _parse_date(message)
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", message)
    for prop, spec in props.items():
        ptype = (spec or {}).get("type") if isinstance(spec, dict) else None
        pname = prop.lower()
        if ptype == "integer" or ptype == "number":
            m = re.search(r"(\d+)", message)
            if m:
                args[prop] = int(m.group(1))
        elif "email" in pname:
            if email:
                args[prop] = email.group(0)
        elif "date" in pname or "deadline" in pname or "due" in pname:
            if parsed_date:
                args[prop] = parsed_date.isoformat()
                if any(w in pname for w in ("end", "to", "until")) and any(
                        ("from" in p.lower() or "start" in p.lower()) for p in props):
                    args[prop] = (parsed_date + timedelta(days=_parse_span(message) - 1)).isoformat()
        elif "code" in pname or "barcode" in pname or "identification" in pname or "depends" in pname:
            pass  # identity codes / dependency lists: never guessed from prose
        elif ptype == "string" and any(w in pname for w in ("assignee", "employee", "user", "person", "partner", "customer", "client")):
            m = re.search(
                r"(?:for|assign(?:ed)?\s+to|to)\s+([\w\u0600-\u06FF][\w\u0600-\u06FF .+-]*?)"
                r"(?=\s+(?:with|by|until|before|deadline|due|starting|from)\b|$)", message, re.I)
            if m:
                captured = m.group(1).strip()
                if "@" not in captured or "email" in pname:
                    args[prop] = captured
            elif email and "email" in pname:
                args[prop] = email.group(0)
        elif ptype == "string" and (pname == "name" or any(w in pname for w in ("title", "summary", "description", "content", "subject", "reason"))):
            args[prop] = _extract_title(message)
    for prop in required:
        if prop in args:
            continue
        spec = props.get(prop) or {}
        ptype = spec.get("type") if isinstance(spec, dict) else None
        pname = prop.lower()
        if ("date" in pname or "deadline" in pname or "due" in pname) and ptype == "string":
            base = parsed_date or (date.today() + timedelta(days=1))
            args[prop] = base.isoformat()
        # Other required fields we could not infer are deliberately LEFT OUT:
        # the tool reports the missing field and the brain asks the user for
        # it in natural language - never invent data.
    return json.dumps(args, ensure_ascii=False)


_MISSING_ASKS = [
    ("deadline", "by when is it due? (e.g. 2026-10-01 or \"next Friday\")"),
    ("due", "by when is it due?"),
    ("assignee_name", "who should it be assigned to?"),
    ("assignee_email", "what is the assignee's work email?"),
    ("employee_code", "what is the employee code?"),
    ("assignee", "who should it be assigned to?"),
    ("employee", "which employee is this for?"),
    ("date_from", "which date should it start?"),
    ("date_to", "until which date?"),
    ("project", "which project does it belong to?"),
]


# --- document-aware answering (upload a PDF/TXT/DOCX and ask about it) ------
_STOP = set(("the a an and or of to in on for with is are was were be been being this that these those it its as at "
             "by from we you i our your their they he she them then than so if not no yes do does did done about "
             "into over under more most some any can could should would will shall may might must have has had "
             "what which who whom when where why how please tell give show me my very also just only").split())


def _tokens(text):
    return [t for t in re.findall(r"[a-zA-Z\u0600-\u06FF0-9]{2,}", (text or "").lower()) if t not in _STOP]


def _sentences(text):
    # ":" stays INSIDE a sentence: labels like "Incident SLA: ..." carry the
    # very tokens a question matches on; splitting after ":" deleted them.
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip() for p in parts if len(p.strip()) >= 25]


def _stem(t):
    return t[:5] if len(t) > 5 else t


def _document_answer(message):
    """Answer questions ABOUT an uploaded document by quoting it verbatim.

    The appliance's /api/files/analyze extracts the file text and the UI sends
    it as 'Consider the attached file X. Extracted analysis: ... User request:
    ...'. Instead of hallucinating, this brain answers extractively: it quotes
    the sentences that actually match the question (or ranks them by term
    frequency for summarize-style asks), and says so honestly.
    """
    marker = "Extracted analysis:"
    if marker not in message:
        return None
    start = message.find(marker) + len(marker)
    qidx = message.rfind("User request:")
    doc = message[start:qidx if qidx != -1 else len(message)].strip()
    question = (message[qidx + len("User request:"):].strip() if qidx != -1 else "") or "Summarize the important points"
    fm = re.search(r"attached file\s+(.+?)\.", message)
    fname = fm.group(1).strip() if fm else "the file"
    sents = _sentences(doc)
    if not sents:
        return ("I opened %s but no readable text could be extracted from it "
                "(scanned/image PDFs need OCR). Upload a text-based PDF or a .txt/.docx and I can read it."
                % fname)
    qtoks = {_stem(t) for t in _tokens(question)}
    overlap = [(s, len(qtoks & {_stem(t) for t in _tokens(s)})) for s in sents]
    quoted = [s for s, n in sorted(overlap, key=lambda x: x[1], reverse=True)[:3] if n > 0]
    if quoted:
        return ("Here is exactly what %s says - the parts that answer \"%s\":\n\n%s\n\n"
                "(Quoted verbatim from the document; nothing invented.)"
                % (fname, question[:120], "\n\n".join("- " + s for s in quoted)))
    # summarize-style: rank by term frequency
    freq = {}
    for t in _tokens(doc):
        freq[t] = freq.get(t, 0) + 1
    top = sorted(sents, key=lambda s: sum(freq.get(t, 0) for t in set(_tokens(s))), reverse=True)[:3]
    numbers = re.findall(r"[\d][\d,.]*\s?(?:%|EUR|USD|Toman|hours?|days?|people|users?)?", doc)[:6]
    return ("I read %s (~%d words). The key points:\n%s%s\n\nAsk me anything specific about it and I will quote the exact lines."
            % (fname, len(_tokens(doc)),
               "\n".join("- " + s for s in top),
               ("\nNotable figures: %s" % ", ".join(numbers)) if numbers else ""))


def _decide(payload: dict) -> dict:
    """Return an OpenAI message dict: either a tool_call or plain content."""
    messages = payload.get("messages") or []
    tools = []
    for t in payload.get("tools") or []:
        fn = t.get("function") or t
        if fn.get("name"):
            tools.append((fn["name"], fn.get("description") or "", fn.get("parameters") or {}))

    last_user = ""
    for m in messages:
        if m.get("role") == "user":
            last_user = m.get("content") or ""

    # Summarise ONLY when the conversation ends with a tool result (i.e. this
    # is the tool-execution follow-up call). Older tool messages deep in the
    # history must not hijack a fresh user request.
    if messages and messages[-1].get("role") == "tool":
        print("[nova-brain] tool result: %.500r" % (messages[-1].get("content"),), flush=True)
        return {"role": "assistant", "content": _summarise_result(messages[-1].get("content") or "")}

    doc_answer = _document_answer(last_user)
    if doc_answer:
        return {"role": "assistant", "content": doc_answer}

    pick = _pick_tool(last_user, tools)
    if pick:
        name, _desc, schema = pick
        arguments = _build_arguments(last_user, schema)
        print("[nova-brain] tool_call %s(%s) for %r" % (name, arguments, last_user[:80]), flush=True)
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_%s" % uuid.uuid4().hex[:24],
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }],
        }
    return {"role": "assistant", "content": _plain_answer(last_user, tools)}


def _summarise_result(raw: str) -> str:
    snippet = (raw or "").strip()
    try:
        data = json.loads(snippet)
        if isinstance(data, dict):
            flat = " ".join("%s %s" % (k, v) for k, v in data.items()
                            if isinstance(v, (str, int, float, bool)))
            snippet = flat.strip() or snippet
    except (ValueError, TypeError):
        pass
    lowered = snippet.lower()
    # Only treat it as a "need more info" answer when the tool actually
    # reported a problem - success payloads also CONTAIN words like
    # "deadline" or "assignee" as dictionary keys.
    has_problem = any(t in lowered for t in ("error", "missing", "notfound", "invalid", "failed"))
    asks = [ask for token, ask in _MISSING_ASKS if token in lowered] if has_problem else []
    if asks:
        return ("Almost! To do that in Odoo I still need a detail:\n%s\n\n"
                "Tell me and I'll create it right away."
                % "\n".join("- " + a for a in asks))
    if "missing" in lowered and "field" in lowered:
        return ("Almost! To do that in Odoo I still need a couple of details - e.g. "
                "who it's for (name or work email) and by when it's due. "
                "Tell me and I'll create it right away.")
    if "notfound" in lowered or "error" in lowered or "invalid" in lowered or "failed" in lowered:
        return ("I tried that in Odoo, but it didn't go through:\n\n%s\n\n"
                "Want me to adjust the details and try again?") % snippet[:400]
    detail = snippet[:400]
    try:
        data = json.loads((raw or "").strip())
        if isinstance(data, dict):
            detail = "\n".join("- %s: %s" % (k, v) for k, v in data.items()
                               if isinstance(v, (str, int, float, bool)))
    except (ValueError, TypeError):
        pass
    return ("Done - I executed that in Odoo for real:\n%s\n\n"
            "Anything else - another record, a report, or a follow-up?") % detail


def _plain_answer(message: str, tools: list[tuple]) -> str:
    text = (message or "").strip().lower()
    catalogue = "\n".join("- %s" % name for name, _d, _s in tools[:10]) if tools else ""
    if any(g in text for g in ("hi", "hello", "hey", "salam", "good morning", "good afternoon")):
        return ("Hi! I'm Nova, running on the appliance's built-in local brain. "
                "I can actually operate your Odoo - just ask in plain words, e.g.:\n"
                "\"Request 2 days of leave starting next Monday\" or \"Create a task called Draft Q4 plan\".")
    if "what can you do" in text or "help" in text or "capability" in text:
        return ("I'm Nova's local brain. I execute real Odoo tools for you:\n%s\n\n"
                "Try: \"request time off for next week\", \"create a task called ...\", "
                "\"show attendance report\". Admins can plug any OpenAI-compatible LLM "
                "(OpenRouter, Groq, local llama.cpp, ...) in Admin -> AI Models for full "
                "natural-language power." % (catalogue or "- operate your Odoo data"))
    return ("I'm Nova's built-in local brain (no external LLM key is configured on this "
            "appliance yet). I can still DO things in Odoo - try:\n"
            "\"Request 2 days leave starting next Monday\"\n"
            "\"Create a task called Prepare budget review\"\n"
            "\"How many documents do we have?\"\n\n"
            "For free-form conversation an admin can connect a real LLM key in "
            "Admin -> AI Models - it takes effect immediately, no restart.")


class Handler(BaseHTTPRequestHandler):
    server_version = "NovaBrain/1.0"

    def log_message(self, fmt, *args):
        print("[nova-brain] %s" % (fmt % args), flush=True)

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

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/").endswith(("/v1/models", "/models")):
            return self._send_json({
                "object": "list",
                "data": [{"id": HANDLER_CONF["served_model"], "object": "model",
                          "created": int(_STATE["started_at"]), "owned_by": "nova"}],
            })
        if self.path.rstrip("/") in ("/v1/health", "/health", "/"):
            with _STATE_LOCK:
                return self._send_json({
                    "status": "ok", "server": "nova-brain",
                    "served_model": HANDLER_CONF["served_model"],
                    "requests": _STATE["count"],
                    "uptime_s": round(time.time() - _STATE["started_at"], 1),
                    "last": _STATE["last"],
                })
        return self._send_json(
            {"error": {"message": "not found: %s" % self.path, "type": "invalid_request_error"}},
            status=404)

    def do_POST(self):  # noqa: N802
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._send_json(
                {"error": {"message": "not found: %s" % self.path, "type": "invalid_request_error"}},
                status=404)
        payload = self._read_json()
        with _STATE_LOCK:
            _STATE["count"] += 1
            _STATE["last"] = {
                "model": payload.get("model"),
                "stream": bool(payload.get("stream")),
                "tools": [((t.get("function") or t).get("name")) for t in payload.get("tools") or []],
            }
        try:
            message = _decide(payload)
        except Exception as exc:  # noqa: BLE001 - never crash the worker
            message = {"role": "assistant",
                       "content": "Brain hiccup: %s" % exc}
        if payload.get("stream"):
            return self._stream(message, payload)
        return self._complete(message, payload)

    # -- OpenAI dialect ---------------------------------------------------
    def _chunk(self, delta: dict, finish: str | None = None) -> bytes:
        obj = {
            "id": "chatcmpl-%s" % uuid.uuid4().hex[:24],
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": HANDLER_CONF["served_model"],
            "choices": [{"index": 0, "delta": delta, "logprobs": None, "finish_reason": finish}],
        }
        return ("data: %s\n\n" % json.dumps(obj, ensure_ascii=False)).encode("utf-8")

    def _stream(self, message: dict, payload: dict) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(self._chunk({"role": "assistant", "content": ""}))
            if message.get("tool_calls"):
                call = message["tool_calls"][0]
                fn = call["function"]
                self.wfile.write(self._chunk({"tool_calls": [{
                    "index": 0, "id": call["id"], "type": "function",
                    "function": {"name": fn["name"], "arguments": ""},
                }]}))
                args = fn.get("arguments") or "{}"
                for i in range(0, len(args), 96):
                    self.wfile.write(self._chunk({"tool_calls": [{
                        "index": 0, "function": {"arguments": args[i:i + 96]}}]}))
                self.wfile.write(self._chunk({}, finish="tool_calls"))
            else:
                text = message.get("content") or ""
                for word in text.split(" "):
                    self.wfile.write(self._chunk({"content": word + " "}))
                    self.wfile.flush()
                    time.sleep(0.015)
                self.wfile.write(self._chunk({}, finish="stop"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _complete(self, message: dict, payload: dict) -> None:
        finish = "tool_calls" if message.get("tool_calls") else "stop"
        self._send_json({
            "id": "chatcmpl-%s" % uuid.uuid4().hex[:24],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": HANDLER_CONF["served_model"],
            "choices": [{"index": 0, "message": message, "logprobs": None, "finish_reason": finish}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })


HANDLER_CONF = {"served_model": "nova-local-brain"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--served-model", default="nova-local-brain")
    args = parser.parse_args()
    HANDLER_CONF["served_model"] = args.served_model
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("[nova-brain] serving model %r on %s:%s (tool-calling enabled)"
          % (args.served_model, args.host, args.port), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
