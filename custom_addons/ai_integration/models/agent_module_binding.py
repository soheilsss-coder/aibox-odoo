import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AiAgentModuleBinding(models.Model):
    """The explicit runtime join between the installed modules and the agent.

    Installing a business module and installing the local model/tools are two
    different lifecycle events. This model makes the second relationship
    durable and observable: every installed module gets a binding to the
    Company Assistant, while only registered tools with an installed owner are
    attached to the assistant. User authorization is still evaluated for each
    thread and each execution; this record is not a privilege grant.
    """

    _name = "ai.integration.agent.module"
    _description = "AI Agent Module Connection"
    _order = "module_label, id"

    agent_id = fields.Many2one("llm.assistant", required=True, ondelete="cascade", index=True)
    module_id = fields.Many2one("ai.control.module", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        ondelete="restrict", index=True,
    )
    module_name = fields.Char(related="module_id.technical_name", store=True, index=True)
    module_label = fields.Char(related="module_id.name", store=True)
    state = fields.Selection([
        ("connected", "Connected"),
        ("connected_no_tools", "Connected / no approved tools"),
        ("error", "Connection error"),
        ("disconnected", "Disconnected"),
    ], required=True, default="connected", index=True)
    connection_level = fields.Selection([
        ("read_only", "Read and audit baseline"),
        ("operational", "Reviewed operational tools"),
    ], required=True, default="read_only")
    operation_ids = fields.Many2many(
        "ai.integration.operation", "ai_agent_module_operation_rel",
        "binding_id", "operation_id", string="Registered operations",
    )
    tool_ids = fields.Many2many(
        "llm.tool", "ai_agent_module_tool_rel",
        "binding_id", "tool_id", string="Agent tools",
    )
    operation_count = fields.Integer(default=0)
    tool_count = fields.Integer(default=0)
    last_sync = fields.Datetime(readonly=True)
    error = fields.Text(readonly=True)
    active = fields.Boolean(default=True, index=True)

    _sql_constraints = [
        (
            "agent_module_company_unique",
            "unique(agent_id, module_id, company_id)",
            "Each installed module can have one active agent connection per company.",
        ),
    ]

    # The old business tools predate the unified operation registry. Their
    # ownership is explicit here rather than inferred from a method name. This
    # keeps legacy tools connected while preserving the same installed-module
    # gate as the reviewed operations.
    _DIRECT_TOOL_MODULES = {
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
        "analyze_image": "company_ai_demo",
        "search_internet": "company_ai_demo",
        "list_available_tools": "ai_business_tools",
        "fill_document_template": "ai_business_tools",
        "generate_qweb_report": "ai_business_tools",
        "create_scheduled_command": "ai_business_tools",
        "send_personal_message": "mail",
        "schedule_meeting": "calendar",
        "generic_read": "ai_integration",
        "search_documents_semantic": "ai_rag",
        "generate_artifact": "ai_experience",
        "run_reviewed_operation": "ai_integration",
    }

    @api.model
    def _installed_names(self):
        return set(self.env["ir.module.module"].sudo().search([
            ("state", "=", "installed"),
        ]).mapped("name"))

    @api.model
    def _assistant(self):
        if "llm.assistant" not in self.env:
            return False
        return self.env["llm.assistant"].sudo().search([
            ("name", "=", "Company Assistant"), ("active", "=", True),
        ], limit=1)

    @api.model
    def _tools_for_module(self, module_name, operations, installed_names):
        """Resolve only actual tool records owned by this installed module.

        Reviewed operations may have a first-class registry name instead of a
        Python ``llm.tool`` record. In that case the single reviewed-operation
        dispatcher is attached to the agent; it still re-checks the nested
        operation, capability, risk and approval contract at execution time.
        """
        Tool = self.env["llm.tool"].sudo()
        names = set()
        for operation in operations:
            if operation.tool_name:
                names.add(operation.tool_name)
        names.update(
            name for name, owner in self._DIRECT_TOOL_MODULES.items()
            if owner == module_name and owner in installed_names
        )
        tools = Tool.search([("name", "in", sorted(names))]) if names else Tool.browse()
        if operations and "ai_integration" in installed_names:
            dispatcher = Tool.search([("name", "=", "run_reviewed_operation")], limit=1)
            tools |= dispatcher
        return tools

    @api.model
    def sync_installed_module_bindings(self):
        """Create/update the Company Assistant connection for every install.

        This method is idempotent and safe to call from the automatic module
        onboarding cron, the integration post-migration, and the chat safety
        path. It never grants a user permission: the chat path intersects the
        binding with the current user's capability/risk allowlist.
        """
        assistant = self._assistant()
        installed_names = self._installed_names()
        Module = self.env["ai.control.module"].sudo()
        installed_modules = Module.search([
            ("technical_name", "in", sorted(installed_names)),
            ("active", "=", True),
        ])
        Operation = self.env["ai.integration.operation"].sudo()
        Binding = self.sudo()
        now = fields.Datetime.now()
        result = {"assistant": bool(assistant), "connected_modules": 0, "attached_tools": 0}

        if not assistant:
            _logger.error("Cannot connect installed modules: Company Assistant is unavailable")
            for module in installed_modules:
                binding = Binding.search([
                    ("module_id", "=", module.id), ("company_id", "=", self.env.company.id),
                ], limit=1)
                values = {
                    "state": "error", "connection_level": "read_only", "operation_count": 0,
                    "tool_count": 0, "last_sync": now,
                    "error": "the Company Assistant is not available",
                    "active": True,
                }
                if binding:
                    binding.write(values)
                # There is no valid binding row without an agent_id. The
                # module status below is the durable error surface until the
                # seeded Company Assistant becomes available.
                module.write({
                    "agent_connected": False, "agent_connection_state": "error",
                    "agent_tool_count": 0, "agent_operation_count": 0,
                    "agent_last_sync": now, "agent_error": values["error"],
                })
            return result

        all_tools = self.env["llm.tool"].sudo().browse()
        for module in installed_modules:
            operations = Operation.search([
                ("module_name", "=", module.technical_name), ("active", "=", True),
            ])
            tools = self._tools_for_module(module.technical_name, operations, installed_names)
            all_tools |= tools
            reviewed = operations.filtered(
                lambda op: op.source == "reviewed" and op.coverage == "reviewed_operational"
            )
            binding = Binding.search([
                ("agent_id", "=", assistant.id), ("module_id", "=", module.id),
                ("company_id", "=", self.env.company.id),
            ], limit=1)
            values = {
                "agent_id": assistant.id,
                "module_id": module.id,
                "company_id": self.env.company.id,
                "state": "connected" if tools else "connected_no_tools",
                "connection_level": "operational" if reviewed else "read_only",
                "operation_ids": [(6, 0, operations.ids)],
                "tool_ids": [(6, 0, tools.ids)],
                "operation_count": len(operations),
                "tool_count": len(tools),
                "last_sync": now,
                "error": False,
                "active": True,
            }
            if binding:
                binding.write(values)
            else:
                binding = Binding.create(values)
            module.write({
                "agent_connected": True,
                "agent_connection_state": "connected" if tools else "connected_no_tools",
                "agent_tool_count": len(tools),
                "agent_operation_count": len(operations),
                "agent_last_sync": now,
                "agent_error": False,
            })
            result["connected_modules"] += 1
            result["attached_tools"] += len(tools)

        # A removed/uninstalled module is never left in the agent's active
        # tool catalog. Keep its binding for audit history, but disconnect it.
        stale = Binding.search([
            ("company_id", "=", self.env.company.id),
            ("module_name", "not in", sorted(installed_names)),
            ("active", "=", True),
        ])
        stale.write({
            "active": False, "state": "disconnected", "tool_ids": [(5, 0, 0)],
            "operation_ids": [(5, 0, 0)], "tool_count": 0, "operation_count": 0,
            "last_sync": now,
        })

        # Keep the actual assistant record in sync for the third-party thread
        # framework. Chat still applies a per-user allowlist to every thread;
        # this write only expresses which installed-module tools belong to this
        # agent and is not authorization.
        assistant.sudo().write({"tool_ids": [(6, 0, all_tools.ids)]})
        return result

    @api.model
    def refresh_if_stale(self, max_age_seconds=15):
        """Avoid a full binding write on every chat turn.

        The post-install hook and one-minute cron are the normal refresh paths.
        This bounded check only closes a short install-to-cron window and
        recovers a worker after a restart; the hot chat path stays read-mostly.
        """
        try:
            max_age_seconds = max(1, min(int(max_age_seconds), 300))
        except (TypeError, ValueError):
            max_age_seconds = 15
        bindings = self.sudo().search([
            ("company_id", "=", self.env.company.id),
        ], limit=200)
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), seconds=max_age_seconds)
        installed_names = self._installed_names()
        bound_names = set(bindings.filtered(lambda binding: binding.active).mapped("module_name"))
        missing_install_bindings = installed_names - bound_names
        if (
            not bindings
            or missing_install_bindings
            or any(not binding.last_sync or binding.last_sync < cutoff for binding in bindings)
        ):
            return self.sync_installed_module_bindings()
        return True

    @api.model
    def tool_ids_for_agent(self, assistant):
        bindings = self.sudo().search([
            ("agent_id", "=", assistant.id),
            ("company_id", "=", self.env.company.id),
            ("state", "in", ("connected", "connected_no_tools")),
            ("active", "=", True),
        ])
        ids = set(bindings.mapped("tool_ids").ids)
        return self.env["llm.tool"].browse(sorted(ids))

    @api.model
    def binding_for_module(self, module_name, assistant=None):
        domain = [
            ("module_name", "=", module_name),
            ("company_id", "=", self.env.company.id),
            ("active", "=", True),
        ]
        if assistant:
            domain.append(("agent_id", "=", assistant.id))
        return self.sudo().search(domain, limit=1)
