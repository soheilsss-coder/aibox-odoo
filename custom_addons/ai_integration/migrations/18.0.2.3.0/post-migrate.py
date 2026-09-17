"""Create the durable module-to-agent catalog on upgrade."""

from odoo import SUPERUSER_ID, api


UNIFIED_TOOL_MODULES = {
    "hr.employee.read_self": "hr",
    "hr.leave.create_request": "hr_holidays",
    "project.task.create": "project",
    "sale.order.create": "sale",
    "purchase.rfq.create": "purchase",
    "stock.transfer.confirm": "stock",
    "account.invoice.post": "account",
    "crm.lead.create": "crm",
    "hr.attendance.check_in": "hr_attendance",
    "hr.expense.create": "hr_expense",
    "mrp.production.create": "mrp",
    "calendar.event.create": "calendar",
    "documents.document.create": "documents",
    "helpdesk.ticket.create": "helpdesk",
    "pos.order.create": "point_of_sale",
    "pos.restaurant.table_status": "pos_restaurant",
    "pos.restaurant.order_note.update": "pos_restaurant",
    "run_reviewed_operation": "ai_integration",
    "event.read_summary": "event",
    "lunch.read_summary": "lunch",
    "maintenance.read_summary": "maintenance",
    "quality.read_summary": "quality",
    "repair.read_summary": "repair",
    "sale_management.read_summary": "sale_management",
    "sale_renting.read_summary": "sale_renting",
    "sale_subscription.read_summary": "sale_subscription",
    "website.read_summary": "website",
    "mass_mailing.read_summary": "mass_mailing",
}


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Risk = env["ai.gateway.tool.risk"].sudo()
    for tool_name, module_name in UNIFIED_TOOL_MODULES.items():
        Risk.search([("tool_name", "=", tool_name)], limit=1).write({
            "module_name": module_name,
        })
    # This also refreshes the canonical installed-module registry. It is
    # intentionally idempotent; the same method runs after later installs from
    # the restart-safe onboarding cron.
    env["ai.control.module"].sync_installed_modules()
