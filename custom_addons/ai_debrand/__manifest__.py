{
    "name": "White Label / Debranding",
    "version": "18.0.1.0.0",
    "summary": "Removes Odoo branding from backend, login page and emails. "
                "Install LAST, after every other module.",
    "category": "Technical",
    "depends": ["web", "mail"],
    "post_init_hook": "post_init_hook",
    "assets": {
        "web.assets_frontend": ["/ai_debrand/static/src/js/debrand.js"],
        "web.assets_backend": ["/ai_debrand/static/src/js/debrand.js"],
    },
    "data": [
        "data/debrand_data.xml",
        "views/debrand_templates.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
