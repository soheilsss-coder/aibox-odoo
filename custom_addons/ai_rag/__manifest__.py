{
    "name": "AI Document RAG",
    "version": "18.0.1.3.0",
    "summary": "Real semantic search over company.document (roadmap #27) - "
                "chunking + local embeddings (Qwen3-Embedding via vLLM) + "
                "pgvector, with access filtering applied BEFORE vector "
                "search, not after.",
    "category": "Technical",
    "depends": [
        "base", "mail",
        "llm", "llm_tool", "llm_assistant",
        "ai_gateway", "ai_control_plane", "ai_integration", "company_ai_demo", "ai_business_tools",
    ],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "security/chunk_rules.xml",
        "security/rag_index_rules.xml",
        "data/tool_risk_data.xml",
        "data/cron_data.xml",
        "data/event_subscriptions.xml",
        "views/document_chunk_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
