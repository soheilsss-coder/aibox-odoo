{
    "name": "AI Semantic API",
    "version": "18.0.1.5.0",
    "summary": "Semantic REST endpoints (/api/hr/leaves, /api/documents, "
                "/api/admin/*, /api/integrations/*, ...) so a frontend never has to know an Odoo "
                "model name (roadmap #43-44). /api/rpc (the old generic ORM/RPC "
                "surface) is permanently disabled (hard 410, no fallback, no "
                "feature flag) - these semantic endpoints are the only "
                "supported API surface, not a wrapper alongside it. Phase 7 (#46 Admin Console, "
                "#47 Document Center) added the /api/admin/* namespace and "
                "document upload/delete/options endpoints. v22 merge round: "
                "updated for ai_gateway's _authenticate() 3-tuple return "
                "(roadmap #50's IP-flood check) - no route behavior changed. "
                "v23 audit round: fixed document 'department' restriction to "
                "actually match the 'group' restriction's self-service-only "
                "rule (was previously accepted, then silently rejected by "
                "ir.rule at create-time with a confusing error - now checked "
                "explicitly upfront), and documents_options() now returns "
                "only the caller's own department instead of every "
                "department in the company. v28: added /api/integrations/telegram* "
                "(status/generate-code/unlink) backing the frontend's new "
                "Integrations page (roadmap #60), so linking Telegram no "
                "longer requires opening the Odoo backend - ai_telegram_bridge "
                "stays a SOFT dependency (like ai.gateway.model.policy "
                "elsewhere in this file), these routes report "
                "'not available' rather than erroring when it isn't installed.",
    "category": "Technical",
    "depends": ["base", "hr", "hr_holidays", "ai_gateway", "ai_business_tools", "ai_rag"],
    "data": [],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
