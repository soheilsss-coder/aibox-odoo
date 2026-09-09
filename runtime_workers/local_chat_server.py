#!/usr/bin/env python3
"""CPU-backed OpenAI-compatible chat server for the exact AWQ chat model.

vLLM is CUDA-only in the shipped wheels and this environment has no GPU, so
this service exposes the OpenAI /v1 API surface (GET /v1/models and
POST /v1/chat/completions, streaming + non-streaming) on top of the exact
qwen3-30b-a3b-instruct-2507-awq model via transformers + compressed-tensors.

The gateway (ai.model.profile / llm.provider) talks to this endpoint exactly
as it would to vLLM, so nothing else in the platform changes.
"""
import json
import os
import threading
import time
import uuid

import torch
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_PATH = os.environ.get("AI_VLLM_MODEL_PATH", "/workspace/models/qwen3-30b-a3b-instruct-2507-awq")
SERVED_MODEL = os.environ.get("AI_VLLM_SERVED_MODEL", "local-model")
HOST = os.environ.get("AI_VLLM_HOST", "127.0.0.1")
PORT = int(os.environ.get("AI_VLLM_PORT", "8000"))
MAX_MODEL_LEN = int(os.environ.get("AI_VLLM_MAX_MODEL_LEN", "32768"))

tokenizer = None
model = None
_gen_lock = threading.Lock()

app = FastAPI(title="AIBOX Local Chat (CPU transformers)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str
    content: str | None = None
    name: str | None = None


class ChatRequest(BaseModel):
    model: str = SERVED_MODEL
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    max_completion_tokens: int | None = Field(default=None, gt=0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    tools: list | None = None
    tool_choice: str | dict | None = None
    stop: str | list | None = None


class EmbeddingRequest(BaseModel):
    model: str = SERVED_MODEL
    input: str | list[str]


def _app_init():
    global tokenizer, model
    started = time.time()
    print(f"CHAT_SERVER loading model {MODEL_PATH}", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        trust_remote_code=True,
        dtype=torch.float32,
        low_cpu_mem_usage=True,
        device_map="cpu",
    )
    model.eval()
    print(f"CHAT_SERVER model ready in {time.time()-started:.0f}s", flush=True)


@app.on_event("startup")
def _startup():
    _app_init()


def _cost_tokens(text: str) -> dict:
    ids = tokenizer.encode(text or "")
    return {
        "prompt_tokens": 0,
        "completion_tokens": len(ids),
        "total_tokens": len(ids),
    }


def _make_message(role, content):
    return {"role": role, "content": content}


def _openai_chunk(delta: dict, index: int = 0, finish_reason=None, model=SERVED_MODEL):
    choice = {
        "index": index,
        "delta": delta,
        "logprobs": None,
        "finish_reason": finish_reason,
    }
    return {
        "id": "chatcmpl-%s" % uuid.uuid4().hex[:16],
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [choice],
    }


def _split_tool_call_text(text: str):
    """Best-effort recovery of Qwen3 tool-call JSON embedded in the
    assistant turn. If the model emits JSON objects with name/arguments
    they are returned as OpenAI tool_calls; otherwise the whole turn is
    plain assistant content."""
    tools = []
    lines = text.replace("\r\n", "\n").split("\n")
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("{") and s.endswith("}"):
            try:
                obj = json.loads(s)
            except Exception:
                continue
            name = obj.get("name") or (obj.get("function") or {}).get("name")
            args = obj.get("arguments")
            if args is None:
                args = (obj.get("function") or {}).get("arguments") or {}
            if name:
                tools.append({
                    "id": "call_%s" % uuid.uuid4().hex[:12],
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args),
                    },
                })
    return tools


def _generate(payload: ChatRequest):
    msgs = [{"role": m.role, "content": m.content or ""} for m in payload.messages]
    tools = payload.tools
    kwargs = {}
    if tools:
        kwargs["tools"] = tools
    prompt = tokenizer.apply_chat_template(
        msgs, tokenize=False, add_generation_prompt=True, **kwargs
    )
    inputs = tokenizer(prompt, return_tensors="pt")
    ids_len = inputs["input_ids"].shape[1]
    gen_kwargs = {
        "max_new_tokens": payload.max_tokens or payload.max_completion_tokens or 512,
        "do_sample": False,
    }
    if payload.temperature is not None and payload.temperature > 0:
        gen_kwargs["do_sample"] = True
        gen_kwargs["temperature"] = payload.temperature
    if payload.top_p is not None:
        gen_kwargs["top_p"] = payload.top_p
    with _gen_lock, torch.no_grad():
        out = model.generate(**inputs, **gen_kwargs)
    new_ids = out[0][ids_len:]
    text = tokenizer.decode(new_ids, skip_special_tokens=True)
    return text, len(new_ids)


def _completion_response(payload: ChatRequest):
    text, ntok = _generate(payload)
    tool_calls = _split_tool_call_text(text)
    if tool_calls:
        content = None
        finish_reason = "tool_calls"
    else:
        content = text.strip()
        finish_reason = "stop"
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-%s" % uuid.uuid4().hex[:16],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.model,
        "choices": [{"index": 0, "message": message, "logprobs": None, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": ntok,
            "total_tokens": ntok,
        },
    }


def _stream_generate(payload: ChatRequest):
    text, ntok = _generate(payload)
    yield "data: " + json.dumps(_openai_chunk({"role": "assistant", "content": ""}, finish_reason=None)) + "\n\n"
    words = text.split(" ")
    for i, w in enumerate(words):
        sep = " " if i < len(words) - 1 else ""
        yield "data: " + json.dumps(_openai_chunk({"content": w + sep})) + "\n\n"
    yield "data: " + json.dumps(_openai_chunk({}, finish_reason="stop")) + "\n\n"
    yield "data: [DONE]\n\n"


@app.get("/v1/models")
def v1_models():
    return {
        "object": "list",
        "data": [{
            "id": SERVED_MODEL,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "local",
        }],
    }


@app.get("/v1/model")
def v1_model():
    return {"id": SERVED_MODEL, "object": "model", "owned_by": "local"}


@app.post("/v1/chat/completions")
async def chat_completions(payload: ChatRequest):
    if not model:
        return JSONResponse({"error": "model not ready"}, status_code=503)
    if payload.stream:
        return StreamingResponse(_stream_generate(payload), media_type="text/event-stream; charset=utf-8")
    return _completion_response(payload)


@app.post("/v1/embeddings")
async def embeddings(payload: EmbeddingRequest):
    return JSONResponse({"error": "this chat service does not serve embeddings; use 127.0.0.1:8002/v1"}, status_code=404)


@app.post("/v1/completions")
async def completions(payload: ChatRequest):
    return _completion_response(payload)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")