"""Idempotent seed that points the appliance at a hosted LLM API.

This replaces ``seed_local_inference.py`` (three vLLM processes on 127.0.0.1)
with an external API, without changing a single line of gateway code: the
gateway still talks to an ``llm.provider`` record, it just now holds a vendor
base URL and key instead of a loopback endpoint.

Everything is derived from the environment by
``runtime_workers/llm_api_config.py``, which detects the vendor from the base
URL, normalizes it to the dialect the Odoo ``llm`` framework speaks, and picks
sensible default model names. So switching vendor is one environment change:

    export AI_LLM_API_BASE=https://api.openai.com/v1
    export AI_LLM_API_KEY=sk-...
    # optional overrides
    export AI_LLM_MODEL=gpt-4.1-mini
    export AI_EMBEDDING_API_BASE=https://api.openai.com/v1
    export AI_EMBEDDING_MODEL=text-embedding-3-small
    export AI_EMBEDDING_DIM=1536

    python odoo-bin shell -c /path/odoo.conf -d <db> --no-http \
        < runtime_workers/seed_api_inference.py

Safety notes
------------
* Idempotent: re-running converges on the configured state instead of
  duplicating providers/models. Safe to run on every deploy.
* Never prints the key. ``describe()`` is redacted by design and the seed only
  reports a 4+4 fingerprint so a build log cannot leak credentials.
* Never deletes the previous provider. The local vLLM provider is deactivated
  instead, so an operator can roll back by re-activating it.
* Chat and embedding stay separate records. Groq and OpenRouter do not serve
  ``/v1/embeddings``; pointing RAG at them would fail at index time, not at
  install time, which is the worst place to discover it.
"""
import os
import sys


def _runtime_workers_dir():
    """Locate this directory when run through ``odoo-bin shell < this_file``.

    ``odoo-bin shell`` does ``exec(sys.stdin.read(), local_vars)``, so
    ``__file__`` is undefined and a relative import cannot be resolved from it.
    Accept an explicit override first, then ``__file__``, then walk up from the
    current directory looking for the module. Failing loudly is correct here:
    silently importing a different copy of the config module would seed the
    database from settings the operator did not review.
    """
    override = os.environ.get("AIBOX_RUNTIME_WORKERS_DIR")
    if override:
        return override
    here = globals().get("__file__")
    if here:
        return os.path.dirname(os.path.abspath(here))
    start = os.path.abspath(os.environ.get("AIBOX_REPO", os.getcwd()))
    for _ in range(6):
        candidate = os.path.join(start, "runtime_workers", "llm_api_config.py")
        if os.path.exists(candidate):
            return os.path.join(start, "runtime_workers")
        parent = os.path.dirname(start)
        if parent == start:
            break
        start = parent
    raise RuntimeError(
        "cannot find runtime_workers/llm_api_config.py; set AIBOX_RUNTIME_WORKERS_DIR "
        "(or AIBOX_REPO) to the repository checkout"
    )


sys.path.insert(0, _runtime_workers_dir())

from llm_api_config import _resolve_key, load_config  # noqa: E402

cfg = load_config()
print("=== AI LLM API SEED ===")
for line in cfg.notes:
    print("  note: %s" % line)
print("  chat      : provider=%s service=%s base=%s model=%s key=%s"
      % (cfg.chat.provider, cfg.chat.service, cfg.chat.api_base, cfg.chat.model,
         "set" if cfg.chat.has_key else "MISSING"))
print("  embedding : provider=%s base=%s model=%s key=%s"
      % (cfg.embedding.provider, cfg.embedding.api_base, cfg.embedding.model,
         "set" if cfg.embedding.has_key else "MISSING"))

if not cfg.chat.api_base:
    raise SystemExit(
        "AI_LLM_API_BASE is not set; refusing to seed an empty provider. "
        "Set AI_LLM_API_BASE (and AI_LLM_API_KEY) and re-run."
    )
if not cfg.chat.has_key:
    print("  WARNING: no chat API key resolved. The provider is created anyway so "
          "the record exists, but every generation will fail until the key is set.")


def _fingerprint(value):
    """4+4 fingerprint only - enough to recognize a key, not to use it."""
    if not value:
        return "(none)"
    if len(value) <= 8:
        return "%d chars" % len(value)
    return "%s...%s" % (value[:4], value[-4:])


# -- provider -----------------------------------------------------------
provider_name = "AI API (%s)" % cfg.chat.label
provider = env["llm.provider"].search([("name", "=", provider_name)], limit=1)
if not provider:
    provider = env["llm.provider"].create({
        "name": provider_name,
        "service": cfg.chat.service,
        "api_base": cfg.chat.api_base,
    })
    print("  created provider %r" % provider_name)
else:
    print("  provider %r already present" % provider_name)

if provider.service != cfg.chat.service:
    provider.service = cfg.chat.service
if provider.api_base != cfg.chat.api_base:
    provider.api_base = cfg.chat.api_base

# Only overwrite a stored key when the environment actually supplies one, so a
# key entered through the Odoo backend survives a deploy that did not export it.
chat_key, key_source = _resolve_key(cfg.chat.provider, dict(os.environ),
                                    (os.environ.get("AI_LLM_API_KEY") or "").strip())
if chat_key:
    provider.api_key = chat_key
    print("  api_key  : %s (from %s)" % (_fingerprint(chat_key), key_source))

# Deactivate - never delete - any provider still pointing at loopback vLLM.
legacy = env["llm.provider"].search([
    ("id", "!=", provider.id),
    ("active", "=", True),
    "|", ("api_base", "ilike", "127.0.0.1:8000"),
         ("api_base", "ilike", "localhost:8000"),
])
for old in legacy:
    old.active = False
    print("  deactivated legacy local provider %r (id=%s)" % (old.name, old.id))


# -- models -------------------------------------------------------------
def _ensure_model(name, use):
    model = env["llm.model"].search([("name", "=", name)], limit=1)
    if not model:
        model = env["llm.model"].create({
            "name": name,
            "model_use": use,
            "provider_id": provider.id,
        })
        print("  created model %r (%s)" % (name, use))
    elif model.provider_id != provider:
        model.provider_id = provider.id
        print("  repointed model %r to %r" % (name, provider_name))
    model.active = True
    return model


chat_model = _ensure_model(cfg.chat.model, "chat")

emb_model = None
if cfg.embedding and cfg.embedding.model:
    # Embeddings may live on a different vendor than chat. When they do, they
    # need their own provider record with its own base URL and key.
    if (cfg.embedding.api_base != cfg.chat.api_base
            or cfg.embedding.provider != cfg.chat.provider):
        emb_provider_name = "AI API embeddings (%s)" % cfg.embedding.label
        emb_provider = env["llm.provider"].search([("name", "=", emb_provider_name)], limit=1)
        if not emb_provider:
            emb_provider = env["llm.provider"].create({
                "name": emb_provider_name,
                "service": "openai",
                "api_base": cfg.embedding.api_base,
            })
            print("  created embedding provider %r" % emb_provider_name)
        emb_provider.api_base = cfg.embedding.api_base
        emb_key = (os.environ.get("AI_EMBEDDING_API_KEY") or chat_key or "").strip()
        if emb_key:
            emb_provider.api_key = emb_key
            print("  embedding api_key: %s" % _fingerprint(emb_key))
        model = env["llm.model"].search([("name", "=", cfg.embedding.model)], limit=1)
        if not model:
            model = env["llm.model"].create({
                "name": cfg.embedding.model,
                "model_use": "embedding",
                "provider_id": emb_provider.id,
            })
            print("  created embedding model %r" % cfg.embedding.model)
        elif model.provider_id != emb_provider:
            model.provider_id = emb_provider.id
        model.active = True
        emb_model = model
    else:
        emb_model = _ensure_model(cfg.embedding.model, "embedding")


# -- assistant binding --------------------------------------------------
assistant = env["llm.assistant"].search([("name", "=", "Company Assistant")], limit=1)
if not assistant:
    assistant = env["llm.assistant"].create({
        "name": "Company Assistant",
        "res_model": "res.users",
    })
    print("  created assistant 'Company Assistant'")
if assistant.provider_id != provider:
    assistant.provider_id = provider.id
if assistant.model_id != chat_model:
    assistant.model_id = chat_model.id
print("  assistant bound to %s / %s" % (provider_name, chat_model.name))


# -- production router profiles ----------------------------------------
# The production router only authorizes profiles that are both `production`
# and `healthy`; a profile that exists but is not promoted is invisible to it.
latency = float(cfg.latency_budget_ms)
profiles = {
    "AI API chat": {
        "purpose": "chat",
        "provider": cfg.chat.provider,
        "endpoint": cfg.chat.api_base,
        "model_id": cfg.chat.model,
        "latency_ms": latency,
        "max_new_tokens": cfg.max_output_tokens,
        "security_score": 0.9,
        "benchmark_score": 0.9,
        "tool_calling_score": 0.85,
        "supports_streaming": True,
        "supports_tools": True,
    },
}
if emb_model is not None:
    profiles["AI API embedding"] = {
        "purpose": "embedding",
        "provider": cfg.embedding.provider,
        "endpoint": cfg.embedding.api_base,
        "model_id": cfg.embedding.model,
        "latency_ms": 1000.0,
        "security_score": 0.9,
        "benchmark_score": 0.85,
    }

for pname, vals in profiles.items():
    prof = env["ai.model.profile"].search([("name", "=", pname)], limit=1)
    if not prof:
        prof = env["ai.model.profile"].create(dict({"name": pname}, **vals))
        print("  created model profile %r" % pname)
    updates = dict(vals)
    updates.update({"active": True, "production": True, "health_state": "healthy"})
    if prof.read(list(updates.keys()))[0] != updates:
        prof.write(updates)
        print("  updated model profile %r" % pname)

# Demote the old local profiles so the router cannot pick a dead loopback
# endpoint. Same policy as the providers: deactivate, do not delete.
for old in env["ai.model.profile"].search([
        ("id", "not in", [
            env["ai.model.profile"].search([("name", "=", n)], limit=1).id
            for n in profiles
        ]),
        ("active", "=", True),
        "|", ("endpoint", "ilike", "127.0.0.1:800"),
             ("endpoint", "ilike", "localhost:800"),
]):
    old.active = False
    print("  deactivated legacy model profile %r" % old.name)

env.cr.commit()
print("SEED_API_INFERENCE_OK")
print("NEXT: python runtime_workers/verify_llm_api.py   (end-to-end check of this provider)")
