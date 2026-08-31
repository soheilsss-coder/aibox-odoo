import json
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class AiUnifiedOperation(models.Model):
    _name = 'ai.integration.operation'
    _description = 'Unified Capability Tool Business Operation'
    _order = 'module_name, tool_name'

    tool_name = fields.Char(required=True, index=True)
    module_name = fields.Char(required=True, index=True)
    adapter_id = fields.Many2one('ai.integration.adapter', required=True, ondelete='cascade')
    capability_name = fields.Char(required=True, index=True)
    operation = fields.Selection([
        ('read', 'Read'), ('create', 'Create'), ('update', 'Update'),
        ('delete', 'Delete'), ('approve', 'Approve'), ('execute', 'Execute')
    ], required=True, default='execute')
    risk_level = fields.Integer(required=True, default=0)
    handler_key = fields.Selection([
        ('hr_employee_read_self', 'Read Current Employee'),
        ('hr_leave_create', 'Create Leave Request'),
        ('project_task_create', 'Create Project Task'),
        ('sale_order_create', 'Create Sales Order'),
        ('purchase_rfq_create', 'Create Purchase RFQ'),
        ('stock_picking_confirm', 'Confirm Stock Transfer'),
        ('account_move_post', 'Post Invoice'),
        ('crm_lead_create', 'Create CRM Lead'),
        ('hr_attendance_checkin', 'Employee Check In'),
        ('hr_expense_create', 'Create Expense'),
        ('mrp_production_create', 'Create Manufacturing Order'),
        ('calendar_event_create', 'Create Calendar Event'),
        ('documents_create', 'Create Document'),
        ('helpdesk_ticket_create', 'Create Helpdesk Ticket'),
        ('pos_order_create', 'Create POS Order'),
        ('pos_restaurant_table_status', 'Read Restaurant Table Status'),
        ('pos_restaurant_order_note_update', 'Update Restaurant Order Note'),
    ], required=True)
    active = fields.Boolean(default=True)
    description = fields.Text()
    contract_version = fields.Integer(default=1, required=True)

    _sql_constraints = [
        ('tool_unique', 'unique(tool_name)', 'Each tool must have exactly one unified operation registry entry.'),
    ]


class AiUnifiedAdapterService(models.AbstractModel):
    _name = 'ai.integration.adapter.service'
    _description = 'Reviewed Business Adapter Execution Service'

    @api.model
    def _model(self, name):
        if name not in self.env:
            raise UserError('required ERP module/model is not installed: %s' % name)
        # Defense in depth: reviewed adapters must still run under the real
        # user's Odoo ACL/record-rule context. The central gateway decides
        # AI authorization first; Odoo remains the second enforcement layer.
        return self.env[name]

    @api.model
    def execute(self, operation, args=None, user=None):
        args = args or {}
        user = user or self.env.user
        if not operation.active:
            raise AccessError('integration operation is disabled')
        if 'ai.gateway.execution.gate' in self.env:
            # The operation itself is registered in the same central registry;
            # capability/risk/approval are checked before this method is reached.
            self.env['ai.gateway.execution.gate'].authorize(
                operation.tool_name, args=args, context_label='adapter:%s' % operation.handler_key,
            )
        handler = getattr(self, '_handle_%s' % operation.handler_key, None)
        if not handler:
            raise UserError('unimplemented reviewed adapter handler: %s' % operation.handler_key)
        return handler(args, user)

    def _handle_hr_employee_read_self(self, args, user):
        employee = self.env["hr.employee"].search([("user_id", "=", user.id)], limit=1)
        if not employee:
            raise UserError("no employee is linked to the current user")
        return {"record_id": employee.id, "model": "hr.employee", "name": employee.name,
                "job_id": employee.job_id.id if employee.job_id else False,
                "department_id": employee.department_id.id if employee.department_id else False,
                "work_email": employee.work_email or False}

    def _handle_hr_leave_create(self, args, user):
        Leave = self._model('hr.leave')
        employee = Leave.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
        if not employee:
            raise UserError('no employee is linked to the current user')
        vals = {
            'employee_id': employee.id,
            'holiday_status_id': int(args['leave_type_id']),
            'request_date_from': args.get('date_from'),
            'request_date_to': args.get('date_to'),
            'name': args.get('description') or 'AI leave request',
        }
        return {'record_id': Leave.create(vals).id, 'model': 'hr.leave', 'status': 'created'}

    def _handle_project_task_create(self, args, user):
        Task = self._model('project.task')
        vals = {'name': args['name']}
        for key in ('project_id', 'user_ids', 'date_deadline', 'description'):
            if key in args:
                vals[key] = args[key]
        rec = Task.create(vals)
        return {'record_id': rec.id, 'model': 'project.task', 'status': 'created'}

    def _handle_sale_order_create(self, args, user):
        Order = self._model('sale.order')
        vals = {'partner_id': int(args['partner_id'])}
        for key in ('date_order', 'client_order_ref', 'note'):
            if key in args:
                vals[key] = args[key]
        rec = Order.create(vals)
        return {'record_id': rec.id, 'model': 'sale.order', 'status': 'created'}

    def _handle_purchase_rfq_create(self, args, user):
        Order = self._model('purchase.order')
        vals = {'partner_id': int(args['partner_id'])}
        for key in ('date_order', 'notes'):
            if key in args:
                vals[key] = args[key]
        rec = Order.create(vals)
        return {'record_id': rec.id, 'model': 'purchase.order', 'status': 'created'}

    def _handle_stock_picking_confirm(self, args, user):
        Picking = self._model('stock.picking')
        rec = Picking.browse(int(args['picking_id'])).exists()
        if not rec:
            raise UserError('stock transfer not found')
        rec.action_confirm()
        return {'record_id': rec.id, 'model': 'stock.picking', 'status': rec.state}


    def _emit_business_event(self, event_type, payload, user):
        if 'ai.control.event' in self.env:
            self.env['ai.control.event'].sudo().publish(
                event_type=event_type,
                payload=payload,
                user=user,
            )

    def _create_with_allowed_fields(self, model_name, args, allowed, defaults=None):
        Model = self._model(model_name)
        vals = dict(defaults or {})
        for key in allowed:
            if key in args and args[key] not in (None, '') and key in Model._fields:
                vals[key] = args[key]
        if not vals:
            raise UserError('no valid fields were supplied for %s' % model_name)
        return Model.create(vals)

    def _handle_crm_lead_create(self, args, user):
        rec = self._create_with_allowed_fields('crm.lead', args,
            ('name','partner_id','email_from','phone','description','user_id','team_id','type'),
            {'name': args.get('name') or 'AI lead'})
        self._emit_business_event('crm.lead.created', {'record_id': rec.id, 'model': rec._name}, user)
        return {'record_id': rec.id, 'model': rec._name, 'status': 'created'}

    def _handle_hr_attendance_checkin(self, args, user):
        Attendance = self._model('hr.attendance')
        employee = self.env['hr.employee'].search([('user_id','=',user.id)], limit=1)
        if not employee:
            raise UserError('no employee is linked to the current user')
        vals = {'employee_id': employee.id}
        if args.get('check_in') and 'check_in' in Attendance._fields:
            vals['check_in'] = args['check_in']
        rec = Attendance.create(vals)
        self._emit_business_event('hr.attendance.checked_in', {'record_id': rec.id, 'employee_id': employee.id}, user)
        return {'record_id': rec.id, 'model': 'hr.attendance', 'status': 'checked_in'}

    def _handle_hr_expense_create(self, args, user):
        Expense = self._model('hr.expense')
        employee = self.env['hr.employee'].search([('user_id','=',user.id)], limit=1)
        if not employee:
            raise UserError('no employee is linked to the current user')
        vals = {'name': args.get('name') or 'AI expense', 'employee_id': employee.id}
        for key in ('product_id','total_amount','quantity','description','date','currency_id','company_id'):
            if key in args and key in Expense._fields:
                vals[key] = args[key]
        rec = Expense.create(vals)
        self._emit_business_event('hr.expense.created', {'record_id': rec.id}, user)
        return {'record_id': rec.id, 'model': 'hr.expense', 'status': 'created'}

    def _handle_mrp_production_create(self, args, user):
        vals = {'product_id': int(args['product_id']), 'product_qty': float(args.get('product_qty', 1))}
        if args.get('bom_id'):
            vals['bom_id'] = int(args['bom_id'])
        rec = self._model('mrp.production').create(vals)
        self._emit_business_event('mrp.production.created', {'record_id': rec.id}, user)
        return {'record_id': rec.id, 'model': 'mrp.production', 'status': 'created'}

    def _handle_calendar_event_create(self, args, user):
        Event = self._model('calendar.event')
        vals = {'name': args['name'], 'start': args['start'], 'stop': args.get('stop') or args['start']}
        for key in ('allday','description','location','user_id','partner_ids','start_date','stop_date'):
            if key in args and key in Event._fields:
                vals[key] = args[key]
        rec = Event.create(vals)
        self._emit_business_event('calendar.event.created', {'record_id': rec.id}, user)
        return {'record_id': rec.id, 'model': 'calendar.event', 'status': 'created'}

    def _handle_documents_create(self, args, user):
        Doc = self._model('documents.document')
        vals = {'name': args['name']}
        for key in ('folder_id','owner_id','partner_id','description','res_model','res_id','company_id'):
            if key in args and key in Doc._fields:
                vals[key] = args[key]
        if 'owner_id' in Doc._fields and 'owner_id' not in vals:
            vals['owner_id'] = user.id
        rec = Doc.create(vals)
        self._emit_business_event('document.created', {'record_id': rec.id, 'model': 'documents.document'}, user)
        return {'record_id': rec.id, 'model': 'documents.document', 'status': 'created'}

    def _handle_helpdesk_ticket_create(self, args, user):
        Ticket = self._model('helpdesk.ticket')
        vals = {'name': args.get('name') or 'AI ticket'}
        for key in ('description','partner_id','team_id','user_id','priority','tag_ids'):
            if key in args and key in Ticket._fields:
                vals[key] = args[key]
        rec = Ticket.create(vals)
        self._emit_business_event('helpdesk.ticket.created', {'record_id': rec.id}, user)
        return {'record_id': rec.id, 'model': 'helpdesk.ticket', 'status': 'created'}

    def _handle_pos_order_create(self, args, user):
        Order = self._model('pos.order')
        vals = {}
        for key in ('session_id','partner_id','pricelist_id','amount_total','note'):
            if key in args and key in Order._fields:
                vals[key] = args[key]
        if 'session_id' not in vals:
            raise UserError('session_id is required for POS order creation')
        rec = Order.create(vals)
        self._emit_business_event('pos.order.created', {'record_id': rec.id}, user)
        return {'record_id': rec.id, 'model': 'pos.order', 'status': 'created'}

    def _handle_pos_restaurant_table_status(self, args, user):
        """Read restaurant tables only through the user's native ACL scope."""
        Table = self._model('restaurant.table')
        domain = []
        if args.get('floor_id') and 'floor_id' in Table._fields:
            domain.append(('floor_id', '=', int(args['floor_id'])))
        try:
            limit = min(max(int(args.get('limit', 100)), 1), 100)
        except (TypeError, ValueError):
            limit = 100
        rows = Table.search(domain, limit=limit)
        result = []
        for table in rows:
            result.append({
                'record_id': table.id,
                'name': getattr(table, 'name', False) or getattr(table, 'table_number', False) or str(table.id),
                'floor_id': table.floor_id.id if 'floor_id' in table._fields and table.floor_id else False,
                'seats': getattr(table, 'seats', False) if 'seats' in table._fields else False,
            })
        return {'model': 'restaurant.table', 'tables': result, 'status': 'ok'}

    def _handle_pos_restaurant_order_note_update(self, args, user):
        Order = self._model('pos.order')
        if 'note' not in Order._fields:
            raise UserError('restaurant order notes are not available in this installation')
        order = Order.browse(int(args.get('order_id', 0))).exists()
        if not order:
            raise UserError('restaurant order not found')
        if 'session_id' in order._fields and order.session_id and order.session_id.state == 'closed':
            raise UserError('a closed restaurant order cannot be changed')
        order.write({'note': str(args.get('note') or '')[:2000]})
        self._emit_business_event('pos.restaurant.order_note.updated', {'record_id': order.id}, user)
        return {'record_id': order.id, 'model': 'pos.order', 'status': 'updated'}

    def _handle_account_move_post(self, args, user):
        Move = self._model('account.move')
        rec = Move.browse(int(args['move_id'])).exists()
        if not rec:
            raise UserError('invoice not found')
        rec.action_post()
        return {'record_id': rec.id, 'model': 'account.move', 'status': rec.state}


class AiUnifiedRegistry(models.AbstractModel):
    _name = 'ai.integration.unified.registry'
    _description = 'Capability Tool Adapter Unified Registry'

    @api.model
    def resolve(self, tool_name):
        return self.env['ai.integration.operation'].sudo().search([
            ('tool_name', '=', tool_name), ('active', '=', True)
        ], limit=1)

    @api.model
    def execution_contract(self, tool_name):
        """Return the single Capability→Tool→Risk contract used by the gate."""
        op = self.resolve(tool_name)
        if not op:
            raise AccessError('unregistered integration operation: %s' % tool_name)
        risk = self.env['ai.gateway.tool.risk'].sudo().search([('tool_name', '=', tool_name)], limit=1)
        cap = self.env['ai.control.capability'].sudo().search([('name', '=', op.capability_name), ('active', '=', True)], limit=1)
        if not risk or not cap:
            raise AccessError('incomplete execution contract: %s' % tool_name)
        if risk.capability_name != op.capability_name or int(risk.risk_level or 0) != int(op.risk_level or 0):
            raise AccessError('execution contract mismatch: %s' % tool_name)
        if cap.module_name != op.module_name:
            raise AccessError('capability/module mismatch: %s' % tool_name)
        return op, risk, cap

    @api.model
    def execute(self, tool_name, args=None):
        op = self.resolve(tool_name)
        if not op:
            raise AccessError('unregistered integration operation: %s' % tool_name)
        if 'ai.gateway.execution.gate' in self.env:
            self.env['ai.gateway.execution.gate'].authorize(tool_name, args=args or {}, context_label='adapter-direct')
        return self.env['ai.integration.adapter.service'].execute(op, args=args or {}, user=self.env.user)

    @api.model
    def manifest(self):
        rows = self.env['ai.integration.operation'].sudo().search([('active', '=', True)])
        return [{
            'tool': r.tool_name, 'module': r.module_name, 'capability': r.capability_name,
            'operation': r.operation, 'risk_level': r.risk_level, 'handler': r.handler_key,
        } for r in rows]
