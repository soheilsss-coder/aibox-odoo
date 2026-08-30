# Release v34 — Unified Enterprise AI Experience

## Implemented

- Fixed the production chat gate: semantic `/api/chat` no longer depends on generic ORM/RPC being enabled.
- Fixed chat continuation: an owned `thread_id` is now reused instead of being silently replaced by a new thread on every message.
- Kept per-user tool allowlisting and thread ownership checks.
- Added `ai_experience` module with semantic APIs for workspace, departments, role-aware agents, tasks, approvals, notifications and model registry.
- Added secure file analysis API for text/CSV/JSON, PDF, DOCX, XLSX and images (image analysis uses the configured vision endpoint).
- Added artifact generation for CSV, JSON, SVG, XLSX, PDF, DOCX and PPTX where the corresponding runtime library is installed.
- Added user-owned artifact download endpoint with ownership enforcement.
- Added `generate_artifact` AI tool and central risk/capability registration.
- Added role-to-agent mapping so every role can have a dedicated Agent identity at the UX layer while remaining bounded by the user's effective permissions.
- Rebuilt the frontend into a unified enterprise workspace: dashboard, AI chat, voice input/output, file analysis, tasks, calendar, departments, knowledge, approvals, agents, notifications, documents and administration navigation.
- Added responsive desktop/mobile UI and capability-aware navigation.

## Verification performed in this environment

- Python compileall: PASS
- Python manifest parsing: PASS
- XML parsing: PASS
- Shell syntax: PASS
- Existing static security audit: PASS
- Existing release audit: PASS
- Chat continuation/security invariant test: PASS
- New Experience API route invariant test: PASS
- ZIP integrity: verified after packaging

## Runtime limitations

This environment does not contain the project's real Odoo runtime (`/opt/odoo/odoo-bin`) or a usable frontend dependency installation, so a live PostgreSQL/Odoo/vLLM/Buzz end-to-end run and Vite production build could not be executed here. The release therefore must be treated as **Release Candidate**, not as a claim of 100% production E2E verification.

Before customer delivery, run the supplied deployment/acceptance scripts on the actual target server and verify: Odoo + PostgreSQL, vLLM text model, vision model, Buzz/Hermes, RAG/vector store, browser voice APIs, optional artifact libraries, reverse proxy/TLS and real user/role scenarios.
