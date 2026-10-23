"""Attach an explicit addon owner to every pre-existing AI tool risk row.

The risk table is shared by the tool registry and is loaded from noupdate data,
so changing the XML alone does not backfill databases that already installed
this addon. The owner is used to keep stale optional-module tools out of the
agent catalog and execution gate.
"""

from odoo import SUPERUSER_ID, api


TOOL_MODULES = {
    "list_pending_leaves": "hr_holidays",
    "create_leave_request": "hr_holidays",
    "approve_leave": "hr_holidays",
    "reject_leave": "hr_holidays",
    "list_overdue_tasks": "project",
    "create_task": "project",
    "get_task_status": "project",
    "list_my_tasks": "project",
    "list_documents": "company_ai_demo",
    "get_document": "company_ai_demo",
    "list_elevated_access": "ai_business_tools",
    "grant_temporary_access": "ai_business_tools",
    "check_identity_integrity": "ai_business_tools",
    "recall_memory": "company_ai_demo",
    "save_memory": "company_ai_demo",
    "get_attendance_report": "hr_attendance",
    "get_my_attendance_summary": "hr_attendance",
    "get_current_datetime": "company_ai_demo",
    "read_attached_file": "company_ai_demo",
    "search_internet": "company_ai_demo",
    "analyze_image": "company_ai_demo",
    "generic_read": "ai_integration",
    "list_available_tools": "ai_business_tools",
    "fill_document_template": "ai_business_tools",
    "generate_qweb_report": "ai_business_tools",
    "create_scheduled_command": "ai_business_tools",
    "send_personal_message": "mail",
    "schedule_meeting": "calendar",
}


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Risk = env["ai.gateway.tool.risk"].sudo()
    for tool_name, module_name in TOOL_MODULES.items():
        Risk.search([("tool_name", "=", tool_name)], limit=1).write({
            "module_name": module_name,
        })
