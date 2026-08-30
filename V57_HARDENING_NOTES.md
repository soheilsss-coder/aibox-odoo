# v57 — Direct Source Hardening Candidate

This release is a source-hardening candidate derived from v56. It was reviewed against the actual source tree, not only against release-status documents.

## Direct code fixes

1. **Central execution gate:** fixed a real runtime defect where `authorize()` referenced an undefined `binding` variable. The gate now resolves `ai.control.tool.binding`, verifies its capability/risk values against the canonical operation/risk registry, and safely falls back to the central risk registry for native `llm.tool` methods that do not need ERP business adapters.
2. **Approval execution:** fixed an unbound approval target variable and retained row locking, immutable payload hashing and one-shot execution checks.
3. **Generic read adapter:** added a strict read-only `generic_read` tool for newly installed Odoo models. It uses only ORM search/read, never sudo for business records, parses domains with `ast.literal_eval`, caps domain clauses and result size, removes sensitive fields, and requires model discovery plus the central read capability. It exposes no create/write/unlink/method execution.
4. **Telegram media:** added document/photo ingestion through `ir.attachment`, real-user ownership, common `/api/chat` attachment handling, and local voice transcription via pinned `faster-whisper==1.2.1`. Telegram remains a thin relay into the same user-authenticated AI gateway.
5. **Chat attachment security:** `/api/chat` now validates attachment ownership before associating an attachment with a user-owned thread.
6. **RAG model routing:** embedding requests now use the benchmark-certified Model Router and reject embedding-dimension mismatches.
7. **Deployment:** Redis is provisioned/enabled by the base installer; vLLM installation requires an explicit validated `VLLM_VERSION`; `faster-whisper` is pinned.

## Static verification executed

- Python compileall: PASS
- Bash syntax (`bash -n`): PASS
- Existing exhaustive source audit: 94/94 PASS
- Existing production static gate: 21/21 PASS
- Existing v47 static security suite: PASS
- Existing final release audit: PASS
- New direct-source hardening audit (`59_v57_hardening_audit.py`): PASS

## Important boundary

This is **not** a fabricated production certification. Runtime certification still requires a real Odoo/PostgreSQL/Redis/pgvector/vLLM stack, including real DGX GB10 model serving, Telegram/Buzz/SSO tests, module certification and end-to-end authorization tests. The production gate must remain FAIL until those runtime probes actually pass.
