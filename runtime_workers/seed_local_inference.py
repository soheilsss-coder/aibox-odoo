"""Idempotent seed for the CPU local-inference deployment (run via odoo-bin shell).

Mirrors the exact DB state previously applied by hand so a brand-new database
(created from scratch on any box) works as soon as the two OpenAI-compatible
runtime workers are up:

    * llm_provider "Local vLLM"  -> openai, http://127.0.0.1:8000/v1, api_key set
      (the openai python client refuses to send a request when api_key is null)
    * llm_model "local-model"     (chat)       and "embedding-model"
    * llm_assistant "Company Assistant" bound to provider/model so
      llm.thread.create() has the NOT NULL FK values
    * ai_model_profile "Qwen AWQ" (chat) and "Qwen3 Embedding" promoted to
      production + healthy so the production router authorizes them

Run with:
    python odoo-bin shell -c /workspace/odoo.conf -d <db> --no-http \
        < runtime_workers/seed_local_inference.py
"""
from odoo import api, fields, models

provider = env["llm.provider"].search([("name", "=", "Local vLLM")], limit=1)
if not provider:
    provider = env["llm.provider"].create({
        "name": "Local vLLM",
        "service": "openai",
        "api_base": "http://127.0.0.1:8000/v1",
    })
if not provider.api_key:
    provider.api_key = "local-inference-key"


def _get_model(name, mtype):
    m = env["llm.model"].search([("name", "=", name)], limit=1)
    if not m:
        m = env["llm.model"].create({
            "name": name,
            "model_use": mtype,
            "provider_id": provider.id,
        })
    if m.provider_id != provider:
        m.provider_id = provider.id
    return m


chat_model = _get_model("local-model", "chat")
emb_model = _get_model("embedding-model", "embedding")

assistant = env["llm.assistant"].search([("name", "=", "Company Assistant")], limit=1)
if not assistant:
    assistant = env["llm.assistant"].create({
        "name": "Company Assistant",
        "res_model": "res.users",
    })
if not assistant.provider_id:
    assistant.provider_id = provider.id
if not assistant.model_id:
    assistant.model_id = chat_model.id

profiles = {
    "Qwen AWQ": {
        "purpose": "chat",
        "provider": "vllm",
        "endpoint": "http://127.0.0.1:8000/v1",
        "model_id": "local-model",
        "quantization": "AWQ",
        "latency_ms": 230000,
        "security_score": 0.95,
        "benchmark_score": 0.9,
        "tool_calling_score": 0.85,
    },
    "Qwen3 Embedding": {
        "purpose": "embedding",
        "provider": "vllm",
        "endpoint": "http://127.0.0.1:8002/v1",
        "model_id": "embedding-model",
        "latency_ms": 1000,
        "security_score": 0.9,
        "benchmark_score": 0.85,
    },
}
for pname, vals in profiles.items():
    prof = env["ai.model.profile"].search([("name", "=", pname)], limit=1)
    if not prof:
        prof = env["ai.model.profile"].create(dict({"name": pname}, **vals))
    updates = dict(vals)
    updates.update({"active": True, "production": True, "health_state": "healthy"})
    if prof.read(updates.keys())[0] != updates:
        prof.write(updates)

env.cr.commit()
print("SEED_LOCAL_INFERENCE_OK")
print("REMINDER: export AI_RAG_EMBEDDING_DIM=384 unless the local embedder serves 1024-dim vectors")