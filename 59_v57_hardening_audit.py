#!/usr/bin/env python3
"""Source-level hardening audit for the v57 candidate.

This intentionally checks implementation facts, not release documents.
It is safe to run without Odoo and is complementary to the 94/94 source
contract audit. Runtime certification still requires a real Odoo stack.
"""
from pathlib import Path
import ast
import sys

ROOT = Path(__file__).resolve().parent
errors = []

def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")

def require(condition, label):
    if not condition:
        errors.append(label)

# Critical regression fixed after direct source review.
gate = read("custom_addons/ai_gateway/models/execution_gate.py")
require('binding = None' in gate and 'ai.control.tool.binding' in gate, "execution gate binding must be explicitly resolved")
require('except AccessError:' in gate and 'ai.gateway.tool.risk' in gate, "legacy/native tools must have a safe central risk fallback")
require('unregistered_tool' in gate, "unknown tools must remain deny-by-default")

# Generic read adapter: read-only, no sudo, model discovery required.
generic = read("custom_addons/ai_integration/models/generic_read.py")
require('@llm_tool(read_only_hint=True)' in generic, "generic read must be read-only tool")
require('require(capability)' not in generic, "generic read must not use a per-model capability without checking registration")
require('search(parsed_domain, limit=limit)' in generic, "generic read must use ORM search")
require('Model.sudo()' not in generic and "Model = self.env[model].sudo()" not in generic, "generic read must never sudo business records")
require('create(' not in generic and 'write(' not in generic and 'unlink(' not in generic, "generic read adapter must not expose writes")
require('ast.literal_eval' in generic, "generic read domain parser must not eval arbitrary code")

# Telegram media ownership + file/voice pipeline.
tg = read("custom_addons/ai_telegram_bridge/controllers/telegram.py")
require('getFile' in tg and 'ir.attachment' in tg, "Telegram documents/images must enter the common attachment pipeline")
require('faster_whisper' in tg, "Telegram voice must have a transcription path")
require('with_user(user.id)' in tg, "Telegram attachments must be owned by the real Odoo user")
require('attachment_ids' in tg, "Telegram must pass media into the shared chat pipeline")

# Gateway attachment ownership.
require('attachment_ownership_denied' in read("custom_addons/ai_gateway/controllers/gateway.py"), "chat attachment ownership must be enforced")

# Approval runtime safety.
approval = read("custom_addons/ai_business_tools/models/approval.py")
require('target = self.env[rec.action_model].browse' in approval, "approval target must always be initialized")
require('FOR UPDATE' in approval, "approval execution must be row-locked")
require('approval_payload_hash' in approval and 'executed_at' in approval, "approval payload must be immutable and one-shot")

# RAG must route through a certified embedding model and validate dimensions.
embed = read("custom_addons/ai_rag/models/embedding_client.py")
require('ai.model.router' in embed and 'purpose="embedding"' in embed, "RAG embedding must use the model registry/router")
require('len(v) != 1024' in embed, "RAG embedding dimension must be validated")

# Deployment dependencies.
base = read("01_setup_base.sh")
require('redis-server' in base and 'systemctl enable --now redis-server' in base, "base installer must provision Redis")
require('VLLM_VERSION' in base and 'vllm==${VLLM_VERSION}' in base, "vLLM version must be explicitly pinned for deployment")
require('faster-whisper==1.2.1' in base, "voice dependency must be pinned")

# Parse every Python/XML/SH source after changes.
for p in ROOT.rglob("*.py"):
    if "node_modules" in p.parts:
        continue
    try:
        ast.parse(p.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"python parse: {p}: {exc}")

if errors:
    print("HARDENING FAIL")
    for e in errors:
        print("-", e)
    sys.exit(1)
print("HARDENING PASS: direct-source regression/security checks passed")
