import json

from odoo import api, fields, models


class AiGatewayIdempotency(models.Model):
    """Stops the same write action from happening twice - e.g. if a
    network retry sends 'approve leave 42' a second time, the second
    call returns the SAME result as the first instead of running the
    action again. Callers (tools) pass an idempotency_key; if that key
    was already used by this user, the cached result is returned
    unchanged and the real action is never re-executed."""

    _name = "ai.gateway.idempotency"
    _description = "AI Gateway Idempotency Keys"

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    key = fields.Char(required=True, index=True)
    tool_name = fields.Char(required=True)
    result_json = fields.Text()
    status = fields.Selection([('in_progress','In Progress'),('completed','Completed')], default='in_progress', required=True, index=True)
    create_date = fields.Datetime(readonly=True)

    _sql_constraints = [
        ("user_key_unique", "unique(user_id, key)",
         "This idempotency key was already used by this user."),
    ]


    @api.model
    def claim(self, user_id, key, tool_name):
        """Atomically claim an idempotency key before business execution.

        PostgreSQL uniqueness is the serialization point. The loser of a
        concurrent race reads the already-created row and never executes the
        business action a second time.
        """
        if not key:
            return None, True
        table = self._table
        with self.env.cr.savepoint():
            self.env.cr.execute(
                f"INSERT INTO {table} (user_id, key, tool_name, status, create_date) "
                f"VALUES (%s, %s, %s, 'in_progress', NOW()) "
                f"ON CONFLICT (user_id, key) DO NOTHING RETURNING id",
                (user_id, key, tool_name),
            )
            row = self.env.cr.fetchone()
        if row:
            return self.browse(row[0]).sudo(), True
        rec = self.sudo().search([('user_id','=',user_id),('key','=',key)], limit=1)
        if rec and rec.status == 'failed':
            rec.write({'status': 'in_progress', 'result_json': False, 'tool_name': tool_name})
            return rec, True
        return rec, False

    def complete(self, result):
        self.ensure_one()
        self.sudo().write({'status':'completed','result_json':json.dumps(result, ensure_ascii=False, default=str)[:5000]})
        return result

    def fail(self, error):
        self.ensure_one()
        self.sudo().write({'status':'failed','result_json':json.dumps({'error': str(error)}, ensure_ascii=False, default=str)[:5000]})
        return False

    @api.model
    def get_cached(self, user_id, key):
        if not key:
            return None
        rec = self.sudo().search([("user_id", "=", user_id), ("key", "=", key)], limit=1)
        if not rec:
            return None
        try:
            return json.loads(rec.result_json)
        except Exception:  # noqa: BLE001
            return None

    @api.model
    def store(self, user_id, key, tool_name, result):
        if not key:
            return
        try:
            self.sudo().create({
                "user_id": user_id, "key": key, "tool_name": tool_name,
                "result_json": json.dumps(result, ensure_ascii=False, default=str)[:5000],
            })
        except Exception:  # noqa: BLE001
            # A race (two near-simultaneous calls with the same key) can
            # hit the unique constraint - that's fine, it just means the
            # other call already cached it; never let this break the
            # actual business action that already succeeded.
            pass
