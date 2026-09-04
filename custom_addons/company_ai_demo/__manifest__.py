{
    "name": "Company AI Demo",
    "version": "18.0.1.3.0",
    "summary": "Demo company, role-based users, and custom LLM tools",
    "category": "Human Resources",
    "depends": [
        "base", "hr", "hr_attendance", "hr_holidays",
        "account", "stock",
        "llm", "llm_tool", "llm_openai", "llm_thread",
        "llm_assistant", "llm_knowledge",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/demo_company_data.xml",
        "data/llm_agent_data.xml",
        "data/vision_config_data.xml",
        "data/memory_cron_data.xml",
        "security/memory_rules.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
