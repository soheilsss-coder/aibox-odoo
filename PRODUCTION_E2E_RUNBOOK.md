# Production E2E Runbook

Run these on the real DGX/production instance after installing v35.

1. Install modules with `02_install_modules.sh`.
2. Start PostgreSQL and verify pgvector >= 0.8.2.
3. Start main vLLM, vision and embedding services.
4. Start Odoo and workers.
5. Configure Buzz and Telegram credentials.
6. Configure `AI_GATEWAY_ALLOWED_ORIGIN` to the exact frontend origin.
7. Run authentication/authorization matrix for CEO, HR, Finance, Warehouse and Employee users.
8. Run workflow scenarios: leave, task, approval, calendar, notification, escalation.
9. Run file scenarios: private/shared/department/company ACL, RAG retrieval and export.
10. Run collaboration scenarios: DM/team/department/company and Agent-in-channel.
11. Run Telegram text/file/voice and webhook retry/deduplication scenarios.
12. Run voice STT/TTS and vision/blueprint benchmarks.
13. Run ERP module certification for HR, Sales, CRM, Purchase, Stock, Accounting, Project, Manufacturing, Calendar, Documents and POS/Restaurant.
14. Run tuning/evaluation suites and compare candidate models before promotion.
15. Record every check in `ai.production.check` and certify only if every required check is PASS.
