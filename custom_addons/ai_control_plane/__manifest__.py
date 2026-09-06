{
    "name": "AI Control Plane",
    "version": "18.0.6.0.0",
    "summary": "Central capabilities, authorization metadata, module discovery and durable domain events",
    "category": "Technical",
    "depends": ["base", "mail", "ai_gateway", "ai_business_tools"],
    "data": [
        "security/ir.model.access.csv",
        "security/control_rules.xml",
        "data/cron_data.xml",
        "data/capability_data.xml",
        "data/policy_data.xml",
        "data/classification_data.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
    "post_init_hook": "post_init_hook",
}
