import json
import logging
import os
import socket
import hashlib

from psycopg2 import sql
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AiModuleEventMapping(models.Model):
    """Per-model lifecycle mapping used by universal and reviewed adapters."""

    _name = "ai.integration.event.mapping"
    _description = "Universal Module Event Mapping"
    _order = "module_name, model_name, operation"

    module_name = fields.Char(required=True, index=True)
    model_name = fields.Char(required=True, index=True)
    operation = fields.Selection([
        ("insert", "Create"), ("update", "Update"), ("delete", "Delete"),
    ], required=True)
    event_type = fields.Char(required=True, index=True)
    adapter_id = fields.Many2one("ai.integration.adapter", ondelete="set null", index=True)
    source = fields.Selection([
        ("discovered", "Automatically discovered"),
        ("reviewed", "Source-reviewed mapping"),
    ], default="discovered", required=True)
    active = fields.Boolean(default=True)
    description = fields.Text()

    _sql_constraints = [(
        "module_model_operation_unique",
        "unique(module_name, model_name, operation)",
        "Each module model lifecycle must have one event mapping.",
    )]


class AiModuleChangeOutbox(models.Model):
    """Durable metadata-only change outbox for automatically integrated modules.

    PostgreSQL triggers write only model/id/company/actor/operation metadata;
    they never copy business field values or secrets. A worker later turns the
    row into the normal control-plane event, where the existing audit and AI
    subscribers apply. This gives every newly installed module an event and
    audit path without monkey-patching the ORM or trusting model-generated
    callbacks.
    """

    _name = "ai.integration.change.outbox"
    _description = "Universal Module Change Outbox"
    _order = "id"

    model_name = fields.Char(required=True, index=True)
    model_table = fields.Char(required=True, index=True)
    record_id = fields.Integer(required=True, index=True)
    operation = fields.Selection([
        ("INSERT", "Create"), ("UPDATE", "Update"), ("DELETE", "Delete"),
    ], required=True, index=True)
    company_id = fields.Many2one("res.company", index=True, ondelete="set null")
    actor_id = fields.Many2one("res.users", index=True, ondelete="set null")
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    payload_json = fields.Text(required=True, default="{}")
    state = fields.Selection([
        ("queued", "Queued"), ("processing", "Processing"),
        ("published", "Published"), ("retry", "Retry"), ("dead_letter", "Dead letter"),
    ], required=True, default="queued", index=True)
    attempts = fields.Integer(default=0, index=True)
    next_attempt_at = fields.Datetime(default=fields.Datetime.now, index=True)
    locked_at = fields.Datetime(index=True)
    locked_by = fields.Char(index=True)
    event_id = fields.Many2one("ai.control.event", index=True, ondelete="set null")
    error = fields.Text()

    @api.model
    def _claim(self, limit):
        now = fields.Datetime.now()
        worker = "%s:%s" % (socket.gethostname(), os.getpid())
        self.env.cr.execute(
            """
            SELECT id FROM ai_integration_change_outbox
             WHERE state IN ('queued', 'retry')
               AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
             ORDER BY id
             FOR UPDATE SKIP LOCKED
             LIMIT %s
            """,
            (now, limit),
        )
        ids = [row[0] for row in self.env.cr.fetchall()]
        if ids:
            self.env.cr.execute(
                """
                UPDATE ai_integration_change_outbox
                   SET state='processing', attempts=attempts+1,
                       locked_at=%s, locked_by=%s
                 WHERE id = ANY(%s)
                """,
                (now, worker, ids),
            )
        return self.sudo().browse(ids)

    @api.model
    def process_pending(self, limit=200):
        """Publish claimed rows to the standard durable event outbox."""
        rows = self._claim(max(1, min(int(limit or 200), 1000)))
        for row in rows:
            try:
                payload = json.loads(row.payload_json or "{}")
                actor = self.env["res.users"].sudo().browse(row.actor_id.id).exists() if row.actor_id else False
                mapping = self.env["ai.integration.event.mapping"].sudo().search([
                    ("model_name", "=", row.model_name),
                    ("operation", "=", row.operation.lower()),
                    ("active", "=", True),
                ], order="source desc,id", limit=1)
                event_type = mapping.event_type if mapping else "module.record.%s" % row.operation.lower()
                event = self.env["ai.control.event"].sudo().publish(
                    event_type,
                    aggregate=None,
                    payload={
                        "module": row.model_name.split(".", 1)[0],
                        "model": row.model_name,
                        "record_id": row.record_id,
                        "operation": row.operation.lower(),
                        "company_id": row.company_id.id if row.company_id else payload.get("company_id"),
                        "actor_id": row.actor_id.id if row.actor_id else payload.get("actor_id"),
                        "source": "universal_module_change_outbox",
                    },
                    user=actor or self.env.user,
                    correlation_id="module-change:%s" % row.id,
                )
                row.write({
                    "state": "published", "event_id": event.id,
                    "locked_at": False, "locked_by": False, "error": False,
                })
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Universal module event %s failed", row.id)
                if row.attempts >= 12:
                    row.write({
                        "state": "dead_letter", "locked_at": False,
                        "locked_by": False, "error": str(exc)[:2000],
                    })
                else:
                    delay = min(3600, 5 * (2 ** max(0, row.attempts - 1)))
                    row.write({
                        "state": "retry", "next_attempt_at": fields.Datetime.add(fields.Datetime.now(), seconds=delay),
                        "locked_at": False, "locked_by": False, "error": str(exc)[:2000],
                    })
        return len(rows)

    @api.model
    def cron_cleanup(self, days=30):
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=max(1, int(days or 30)))
        self.sudo().search([
            ("state", "in", ("published", "dead_letter")),
            ("occurred_at", "<", cutoff),
        ], limit=5000).unlink()
        return True


class AiUniversalChangeTrigger(models.AbstractModel):
    """Installs idempotent metadata triggers for models of installed modules."""

    _name = "ai.integration.change.trigger"
    _description = "Universal Module Change Trigger Manager"

    @api.model
    def _is_business_model(self, module_record):
        modules = {
            item.strip() for item in (module_record.modules or "").split(",") if item.strip()
        }
        # Platform modules still receive the same read/capability baseline and
        # their model tables are event-covered. Only this integration's own
        # tables are excluded to prevent the outbox from observing itself.
        return any(not item.startswith("ai_") for item in modules)

    @api.model
    def ensure_triggers(self):
        """Install triggers for all current non-platform module model tables.

        Trigger/table identifiers come from the live registry and are quoted
        with psycopg2.sql. The function body stores metadata only, so the
        database cannot accidentally persist arbitrary sensitive fields.
        """
        self.env.cr.execute(
            """
            CREATE OR REPLACE FUNCTION ai_integration_capture_change()
            RETURNS trigger AS $fn$
            DECLARE
                item jsonb;
                rid integer;
                cid integer;
                uid integer;
            BEGIN
                item := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
                rid := NULLIF(item->>'id', '')::integer;
                cid := NULLIF(item->>'company_id', '')::integer;
                uid := COALESCE(NULLIF(item->>'write_uid', '')::integer,
                                NULLIF(item->>'create_uid', '')::integer);
                INSERT INTO ai_integration_change_outbox
                    (model_name, model_table, record_id, operation, company_id,
                     actor_id, occurred_at, payload_json, state, attempts,
                     next_attempt_at)
                VALUES
                    (TG_ARGV[0], TG_RELNAME, COALESCE(rid, 0), TG_OP, cid, uid,
                     clock_timestamp(), jsonb_build_object(
                         'company_id', cid, 'actor_id', uid, 'record_id', rid,
                         'operation', lower(TG_OP)
                     )::text, 'queued', 0, clock_timestamp());
                RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END;
            $fn$ LANGUAGE plpgsql;
            """
        )
        model_meta = self.env["ir.model"].sudo().search([("model", "!=", False)])
        installed_names = set(self.env["ir.module.module"].sudo().search([
            ("state", "=", "installed")
        ]).mapped("name"))
        created = 0
        for meta in model_meta:
            if not self._is_business_model(meta):
                continue
            model_name = meta.model
            if model_name not in self.env:
                continue
            Model = self.env[model_name]
            table = getattr(Model, "_table", "")
            if not getattr(Model, "_auto", False) or getattr(Model, "_transient", False):
                continue
            if (
                not table or not isinstance(table, str)
                or not table.replace("_", "").isalnum()
                or table.startswith(("ai_", "ir_", "bus_"))
            ):
                continue
            # Do not attach a model's trigger if its owning module disappeared
            # during a partially completed registry update.
            owners = {item.strip() for item in (meta.modules or "").split(",") if item.strip()}
            if not owners.intersection(installed_names):
                continue
            trigger = "ai_chg_%s" % hashlib.sha1(table.encode()).hexdigest()[:24]
            try:
                # A third-party module can leave stale ir.model metadata while
                # its table is being upgraded. Isolate that table so one bad
                # optional model cannot abort onboarding for every module.
                with self.env.cr.savepoint():
                    self.env.cr.execute(
                        "SELECT 1 FROM pg_trigger WHERE tgname=%s AND NOT tgisinternal",
                        (trigger,),
                    )
                    if self.env.cr.fetchone():
                        continue
                    statement = sql.SQL(
                        "CREATE TRIGGER {trigger} AFTER INSERT OR UPDATE OR DELETE ON {table} "
                        "FOR EACH ROW EXECUTE FUNCTION ai_integration_capture_change({model})"
                    ).format(
                        trigger=sql.Identifier(trigger),
                        table=sql.Identifier(table),
                        model=sql.Literal(model_name),
                    )
                    self.env.cr.execute(statement)
                    created += 1
            except Exception:  # noqa: BLE001
                _logger.exception("Could not install universal change trigger for %s", model_name)
        return {"triggers_created": created}
        return {"triggers_created": created}
