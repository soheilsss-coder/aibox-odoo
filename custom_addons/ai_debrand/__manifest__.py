{
    "name": "White Label / Debranding",
    "version": "18.0.1.1.0",
    "summary": "Removes Odoo branding from backend, login page and emails. "
                "Install LAST, after every other module.",
    "category": "Technical",
    "depends": ["web", "mail", "ai_customer_plane"],
    "data": [
        "data/debrand_data.xml",
        "views/debrand_templates.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
