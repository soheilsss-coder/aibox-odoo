{
    "name": "AI Customer Control Plane",
    "version": "18.0.9.0.0",
    "summary": "Customer roles, policy, delegation, access review, SSO and SCIM control plane",
    "category": "Technical",
    "depends": [
        "base",
        "mail",
        "ai_control_plane",
        "ai_integration"
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/customer_rules.xml",
        "data/roles.xml",
        "data/scim_data.xml",
        "views/excel_role_import_views.xml"
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3"
}
