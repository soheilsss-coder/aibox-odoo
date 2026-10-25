#!/usr/bin/env python3
"""CPU-backed OpenAI-compatible embedding server.

Exposes POST /v1/embeddings for the platform's RAG (ai.rag / llm.pgvector).
Uses a small multilingual embedding model so Persian + English documents
get embeddings on machines without a GPU; the chat model is never used here.
"""
import json
import os
import threading
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

MODEL_NAME = os.environ.get("AI_VLLM_EMBEDDING_MODEL_PATH", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
SERVED_MODEL = os.environ.get("AI_VLLM_EMBEDDING_MODEL", "embedding-model")
HOST = os.environ.get("AI_VLLM_HOST", "127.0.0.1")
PORT = int(os.environ.get("AI_VLLM_PORT", "8002"))

encoder = None
_enc_lock = threading.Lock()

app = FastAPI(title="AIBOX Local Embedding (CPU)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _app_init():
    global encoder
    started = time.time()
    print(f"EMBEDDING_SERVER loading {MODEL_NAME}", flush=True)
    from sentence_transformers import SentenceTransformer

    encoder = SentenceTransformer(MODEL_NAME)
    print(f"EMBEDDING_SERVER ready in {time.time()-started:.0f}s", flush=True)


@app.on_event("startup")
def _startup():
    _app_init()


class EmbeddingRequest(BaseModel):
    model: str = SERVED_MODEL
    input: str | list[str]


@app.get("/v1/models")
def v1_models():
    return {
        "object": "list",
        "data": [{"id": SERVED_MODEL, "object": "model", "created": int(time.time()), "owned_by": "local"}],
    }


@app.post("/v1/embeddings")
async def embeddings(payload: EmbeddingRequest):
    if not encoder:
        return JSONResponse({"error": "embedding model not ready"}, status_code=503)
    texts = payload.input if isinstance(payload.input, list) else [payload.input]
    texts = [t or " " for t in texts]
    with _enc_lock:
        vecs = encoder.encode(texts, normalize_embeddings=True)
    data = []
    for i, vec in enumerate(vecs):
        data.append({
            "object": "embedding",
            "index": i,
            "embedding": [float(x) for x in vec],
        })
    return {
        "object": "list",
        "data": data,
        "model": payload.model,
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")