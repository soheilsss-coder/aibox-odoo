{
    "name": "AI Telegram Bridge",
    "version": "18.0.1.0.0",
    "summary": "Lets employees reach the Company Assistant from Telegram, through the existing AI Gateway - not a separate agent",
    "category": "Technical",
    "depends": ["base", "web", "ai_gateway"],
    "data": [
        "security/ir.model.access.csv",
        "security/telegram_rules.xml",
        "views/telegram_link_views.xml",
        "wizard/telegram_link_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
