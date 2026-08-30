# ---------------------------------------------------------------------
# ERP Adapter convention (roadmap item #10)
#
# There is no separate/formal adapter class between "business logic"
# and "Odoo details" - deliberately, per the roadmap item's own
# recommendation: a full interface layer isn't worth building until a
# second ERP is actually on the table. Instead, the informal adapter
# IS a coding convention every *_tools.py file in this module (and in
# company_ai_demo) follows:
#
#   - Only call standard Odoo model methods to mutate data
#     (hr.leave.action_approve(), task.activity_schedule(), ...),
#     never self.env.cr.execute() / raw SQL, for anything that reads
#     or writes business records. Odoo's own ORM methods are what
#     carries ACL/ir.rule/mail-thread/audit-trail behavior with them;
#     raw SQL silently bypasses all of that.
#   - The only files in this whole codebase that DO use cr.execute()
#     are ai_rag/models/document_chunk.py (pgvector's `<=>` operator
#     has no ORM equivalent - ACL is enforced by pre-filtering ids via
#     a normal ORM search() first, see roadmap #27) and
#     ai_business_tools/models/audit_log.py (read-only aggregate
#     queries for the observability snapshot, roadmap #48) - both
#     documented exceptions, not business-action code.
#   - Verified (v18): every *_tools.py file below, plus
#     company_ai_demo/models/hr_decree.py and leave_request.py, is
#     free of raw SQL - confirmed by grep across the whole tree, not
#     just asserted.
#
# If a second ERP or a major internal refactor ever becomes real, this
# convention is exactly what makes it tractable: any tool method that
# broke that convention would be the one place that needs untangling
# first. Until then, a formal adapter class would just be indirection
# with no second implementation to justify it.
# ---------------------------------------------------------------------

from . import context_firewall
from . import audit_log
from . import idempotency
from . import approval
from . import access_grant
from . import access_review_tools
from . import tool_risk
from . import tool_registry
from . import approval_matrix
from . import model_policy
from . import hr_leave_tools
from . import task_tools
from . import task_automation
from . import company_document
from . import identity_integrity
from . import attendance_tools
from . import communication_tools
from . import calendar_tools
from . import document_tools
from . import scheduled_command_tools

from . import approval_history
