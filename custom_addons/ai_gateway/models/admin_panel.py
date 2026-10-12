import secrets

from odoo import api, fields, models


class AiGatewayAdminPanelSession(models.Model):
    """Isolated admin-panel session.

    Deliberately SEPARATE from ai.gateway.session (employee workspace):
    different table, different cookie, different TTL. A user logged into
    the workspace gains nothing here and vice versa.
    """

    _name = "ai.gateway.admin.panel.session"
    _description = "Admin Panel Session (isolated from workspace auth)"
    _order = "id desc"

    token_hash = fields.Char(required=True, index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade")
    created_at = fields.Datetime(default=fields.Datetime.now, required=True)
    expires_at = fields.Datetime(required=True)
    revoked = fields.Boolean(default=False)

    TTL_HOURS = 8

    @api.model
    def _hash(self, token):
        import hashlib

        return hashlib.sha256((token or "").encode("utf-8")).hexdigest()

    @api.model
    def issue_for(self, user):
        """Only base.group_system users may ever hold an admin session."""
        if not user or not user.has_group("base.group_system"):
            return None
        token = secrets.token_urlsafe(48)
        self.sudo().create({
            "token_hash": self._hash(token),
            "user_id": user.id,
            "expires_at": fields.Datetime.now() + __import__("datetime").timedelta(hours=self.TTL_HOURS),
        })
        return token

    @api.model
    def resolve(self, token):
        """Return the admin user for a live token, else None."""
        if not token:
            return None
        now = fields.Datetime.now()
        rec = self.sudo().search([
            ("token_hash", "=", self._hash(token)),
            ("revoked", "=", False),
            ("expires_at", ">", now),
        ], limit=1)
        if not rec or not rec.user_id.has_group("base.group_system"):
            return None
        return rec.user_id

    def revoke(self):
        self.sudo().write({"revoked": True})


class AiGatewayAdminPanelOps(models.AbstractModel):
    """Admin-panel operations: AI engine wiring, module management,
    users, health, logs. All called sudo() from the controller AFTER the
    admin session has been resolved."""

    _name = "ai.gateway.admin.panel"
    _description = "Admin Panel Operations"

    # ---------------------------------------------------------- AI engine
    ENGINE_KEYS = {
        "provider": "admin_panel.engine.provider",
        "api_base": "admin_panel.engine.api_base",
        "chat_model": "admin_panel.engine.chat_model",
        "embedding_model": "admin_panel.engine.embedding_model",
        "api_key": "admin_panel.engine.api_key",
    }

    def engine_get(self):
        param = self.env["ir.config_parameter"].sudo()
        data = {k: param.get_param(p, "") for k, p in self.ENGINE_KEYS.items()}
        key = data.pop("api_key", "") or ""
        data["api_key_tail"] = ("..." + key[-4:]) if key else ""
        data["has_key"] = bool(key)
        return data

    def engine_set(self, provider=None, api_base=None, chat_model=None,
                   embedding_model=None, api_key=None):
        param = self.env["ir.config_parameter"].sudo()
        mapping = {
            "provider": provider, "api_base": api_base,
            "chat_model": chat_model, "embedding_model": embedding_model,
        }
        for k, v in mapping.items():
            if v is not None:
                param.set_param(self.ENGINE_KEYS[k], str(v).strip())
        if api_key:  # empty = keep existing
            param.set_param(self.ENGINE_KEYS["api_key"], str(api_key).strip())
        return self.engine_get()

    def engine_apply(self):
        """Push the engine settings into the live llm.provider/model rows so
        chat + embeddings immediately use them (no restart)."""
        cfg = self.engine_get()
        base = cfg.get("api_base") or ""
        chat_model = cfg.get("chat_model") or ""
        emb_model = cfg.get("embedding_model") or ""
        key = self.env["ir.config_parameter"].sudo().get_param(self.ENGINE_KEYS["api_key"], "")
        if not base:
            return {"applied": False, "error": "api_base is empty"}
        provider = self.env["llm.provider"].search([("api_base", "like", "127.0.0.1")], limit=1)
        if not provider:
            provider = self.env["llm.provider"].search([], limit=1)
        if not provider:
            provider = self.env["llm.provider"].create({"name": "Admin Panel Engine"})
        provider.write({"api_base": base, "active": True})
        if key:
            provider.api_key = key
        def _ensure_model(name, use):
            if not name:
                return None
            m = self.env["llm.model"].search([("name", "=", name), ("provider_id", "=", provider.id)], limit=1)
            if not m:
                m = self.env["llm.model"].create({"name": name, "provider_id": provider.id, "model_use": use})
            else:
                m.model_use = use
            return m
        cm = _ensure_model(chat_model, "chat")
        em = _ensure_model(emb_model, "embedding")
        # Rebind the Company Assistant and every provider-less thread.
        assistant = self.env["llm.assistant"].search([("name", "=", "Company Assistant")], limit=1)
        if assistant:
            assistant.provider_id = provider.id
            if cm:
                assistant.model_id = cm.id
        return {"applied": True, "provider": provider.name,
                "chat_model": cm and cm.name, "embedding_model": em and em.name}

    def engine_test(self, api_base=None, api_key=None, chat_model=None):
        """Live probe: one tiny chat completion (and embeddings if given)."""
        import json as _json

        import requests as _requests

        cfg = self.engine_get()
        base = (api_base or cfg.get("api_base") or "").rstrip("/")
        key = api_key or (self.env["ir.config_parameter"].sudo().get_param(self.ENGINE_KEYS["api_key"], "") or "")
        model = chat_model or cfg.get("chat_model") or ""
        if not base:
            return {"ok": False, "error": "Base URL is empty"}
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer %s" % key
        result = {"ok": False, "base": base, "chat_model": model}
        try:
            r = _requests.post(base + "/chat/completions", headers=headers, timeout=25, json={
                "model": model or "default",
                "messages": [{"role": "user", "content": "Reply with the single word: PONG"}],
                "max_tokens": 20,
            })
            result["chat_status"] = r.status_code
            if r.ok:
                result["chat_reply"] = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")[:120]
                result["ok"] = True
            else:
                result["error"] = r.text[:200]
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)[:200]
        return result

    # ----------------------------------------------------------- modules
    def modules_list(self):
        apps = self.env["ir.module.module"].sudo().search([], order="name")
        return [{"name": m.name, "short_desc": m.shortdesc or "",
                 "state": m.state, "version": (m.latest_version or "")[:12]}
                for m in apps]

    def modules_act(self, names, action):
        """action in install|upgrade|uninstall (uninstall allowed only for
        non-critical custom addons - never base/web/mail)."""
        PROTECTED = {"base", "web", "mail", "bus", "web_tour", "theme_common"}
        if action not in ("install", "upgrade", "uninstall"):
            return {"error": "unknown action"}
        mods = self.env["ir.module.module"].sudo().search([("name", "in", names)])
        done, errors = [], []
        for m in mods:
            try:
                if action == "uninstall" and (m.name in PROTECTED or m.state != "installed"):
                    errors.append({"name": m.name, "error": "protected or not installed"})
                    continue
                if action == "install" and m.state not in ("uninstalled",):
                    if m.state == "installed":
                        done.append(m.name)
                    continue
                getattr(m, "button_" + ("uninstall" if action == "uninstall" else action))()
                done.append(m.name)
            except Exception as exc:  # noqa: BLE001
                errors.append({"name": m.name, "error": str(exc)[:200]})
        return {"done": done, "errors": errors}

    # ------------------------------------------------------------- users
    def users_list(self):
        users = self.env["res.users"].sudo().search([("share", "=", False)], order="login")
        return [{"id": u.id, "login": u.login, "name": u.name,
                 "admin": u.has_group("base.group_system"),
                 "active": u.active} for u in users]

    def user_set_password(self, login, password):
        user = self.env["res.users"].sudo().search([("login", "=", login)], limit=1)
        if not user:
            return {"error": "user not found"}
        if len(password or "") < 4:
            return {"error": "password too short (min 4)"}
        user.password = password
        return {"ok": True, "login": user.login}

    # ------------------------------------------------------------ health
    def health(self):
        out = {"database": "unknown", "redis": "unknown", "ai_engine": "unknown"}
        try:
            self.env.cr.execute("SELECT 1")
            out["database"] = "up"
        except Exception:  # noqa: BLE001
            out["database"] = "down"
        param = self.env["ir.config_parameter"].sudo()
        base = (param.get_param(self.ENGINE_KEYS["api_base"], "") or "").rstrip("/")
        if base:
            try:
                import requests as _requests

                r = _requests.get(base + "/models", timeout=6)
                out["ai_engine"] = "up" if r.ok else "down (%s)" % r.status_code
            except Exception as exc:  # noqa: BLE001
                out["ai_engine"] = "down (%s)" % str(exc)[:60]
        else:
            out["ai_engine"] = "not configured"
        redis_url = param.get_param("ai_gateway.redis_url", "")
        try:
            import socket as _socket

            from urllib.parse import urlparse as _urlparse

            u = _urlparse(redis_url or "redis://127.0.0.1:16379/0")
            s = _socket.socket(); s.settimeout(1.5)
            s.connect((u.hostname or "127.0.0.1", u.port or 6379)); s.close()
            out["redis"] = "up"
        except Exception:  # noqa: BLE001
            out["redis"] = "down"
        counts = {}
        for model, label in (("res.users", "users"), ("llm.thread", "chat threads"),
                             ("ir.attachment", "files"), ("ai.gateway.audit.log", "audit events")):
            try:
                counts[label] = self.env[model].sudo().search_count([])
            except Exception:  # noqa: BLE001
                counts[label] = None
        out["counts"] = counts
        out["modules_installed"] = self.env["ir.module.module"].sudo().search_count([("state", "=", "installed")])
        return out

    # -------------------------------------------------------------- logs
    def logs_tail(self, limit=80):
        logs = self.env["ai.gateway.audit.log"].sudo().search([], order="id desc", limit=limit)
        return [{"id": l.id, "date": str(l.create_date), "user": l.user_id.name or "",
                 "action": l.action, "success": l.success,
                 "error": (l.error_message or "")[:120]} for l in logs]

    # --------------------------------------------------- users & departments
    def departments_list(self):
        try:
            recs = self.env["hr.department"].sudo().search([])
            return [{"id": d.id, "name": self._plain_name(d.name)} for d in recs]
        except Exception:  # noqa: BLE001
            return []

    def users_create(self, vals):
        name = (vals.get("name") or "").strip()
        login = (vals.get("login") or "").strip().lower()
        password = vals.get("password") or ""
        if not name or not login:
            return {"error": "name and login are required"}
        if len(password) < 4:
            return {"error": "password too short (min 4)"}
        Users = self.env["res.users"].sudo()
        if Users.search([("login", "=", login)], limit=1):
            return {"error": "login already exists"}
        try:
            user = Users.create({"name": name, "login": login, "password": password})
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}
        dept = vals.get("department_id")
        if dept:
            try:
                emp = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
                if emp:
                    emp.write({"department_id": int(dept)})
                else:
                    self.env["hr.employee"].sudo().create({
                        "name": name, "user_id": user.id, "department_id": int(dept)})
            except Exception:  # noqa: BLE001
                pass
        group_user = self.env.ref("base.group_user", raise_if_not_found=False)
        if group_user:
            user.write({"groups_id": [(4, group_user.id)]})
        return {"ok": True, "id": user.id, "login": user.login}

    # ---------------------------------------------------- module presets
    PRESETS = {
        "sales": ["sale_management", "crm", "contacts"],
        "accounting": ["account"],
        "inventory": ["stock", "stock_barcode"],
        "hr": ["hr", "hr_holidays", "hr_attendance"],
        "project": ["project", "hr_timesheet"],
        "website": ["website", "website_blog"],
    }

    def modules_presets(self):
        IrModule = self.env["ir.module.module"].sudo()
        out = []
        for key, names in self.PRESETS.items():
            states = []
            for n in names:
                m = IrModule.search([("name", "=", n)], limit=1)
                states.append({"name": n, "state": m.state if m else "missing"})
            out.append({"key": key, "modules": states,
                        "installed": all(x["state"] in ("installed", "to upgrade", "to install") for x in states)})
        return out

    def preset_apply(self, key):
        names = self.PRESETS.get(key)
        if not names:
            return {"error": "unknown preset"}
        IrModule = self.env["ir.module.module"].sudo()
        present = [n for n in names if IrModule.search([("name", "=", n)], limit=1)]
        if not present:
            return {"error": "none of the preset modules exist on this appliance"}
        return self.modules_act(present, "install")

    # ------------------------------------------------------ handover check
    def handover_checklist(self):
        h = self.health()
        eng = self.engine_get()
        branding = self.branding_get()
        non_admin_users = self.env["res.users"].sudo().search_count([
            ("share", "=", False), ("id", "!=", 2)])
        items = [
            {"key": "database", "label": "Database reachable",
             "ok": h.get("database") == "up"},
            {"key": "ai_engine", "label": "AI engine configured and reachable",
             "ok": h.get("ai_engine") == "up" and bool(eng.get("chat_model"))},
            {"key": "branding", "label": "Customer branding set",
             "ok": bool(branding.get("exists")) and bool(branding.get("brand_name"))},
            {"key": "users", "label": "Customer users created",
             "ok": non_admin_users > 0, "info": str(non_admin_users) + " non-admin user(s)"},
            {"key": "modules", "label": "Required modules installed",
             "ok": int(h.get("modules_installed") or 0) >= 80,
             "info": str(h.get("modules_installed")) + " installed"},
        ]
        return {"ready": all(i["ok"] for i in items), "items": items}

    # ------------------------------------------------- phase C: handover kit
    def cleanup_test_data(self, archive_logins=None):
        """Pre-delivery hygiene: purge every conversation (with its messages
        and uploaded files), archive the picked test users, and revoke ALL
        gateway sessions and API keys so no token from the vendor's testing
        survives into the customer's hands. The audit log is intentionally
        KEPT - it is append-only, hash-chained, and part of the delivery
        record."""
        out = {}
        threads = self.env["llm.thread"].sudo().search([])
        atts = self.env["ir.attachment"].sudo().search([("res_model", "=", "llm.thread")])
        msgs = self.env["mail.message"].sudo().search([
            ("model", "=", "llm.thread"), ("res_id", "in", threads.ids or [0])])
        out["attachments"] = len(atts)
        atts.unlink()
        out["messages"] = len(msgs)
        msgs.unlink()
        out["threads"] = len(threads)
        threads.unlink()
        archived = []
        for login in (archive_logins or []):
            u = self.env["res.users"].sudo().search([
                ("login", "=", login), ("id", "!=", 2)], limit=1)
            if u and u.active:
                u.write({"active": False})
                archived.append(login)
        out["users_archived"] = archived
        if "ai.gateway.session" in self.env:
            recs = self.env["ai.gateway.session"].sudo().search([("revoked_at", "=", False)])
            out["sessions_revoked"] = len(recs)
            for rec in recs:
                rec.revoke()
        if "ai.gateway.api.key" in self.env:
            recs = self.env["ai.gateway.api.key"].sudo().search([("active", "=", True)])
            out["api_keys_revoked"] = len(recs)
            for rec in recs:
                rec.revoke(reason="handover_cleanup")
        return out

    def admin_change_password(self, current, new):
        if len(new or "") < 6:
            return {"error": "new password too short (min 6)"}
        admin = self.env["res.users"].sudo().search([("login", "=", "admin")], limit=1)
        if not admin:
            return {"error": "admin user not found"}
        # verify the CURRENT password with the same recipe the panel login
        # uses (dedicated cursor as the target user) before replacing it.
        import odoo as _odoo

        registry = _odoo.registry(self.env.cr.dbname)
        with registry.cursor() as cr:
            env2 = _odoo.api.Environment(cr, admin.id, {})
            try:
                env2["res.users"].browse(admin.id)._check_credentials(
                    {"type": "password", "password": current}, {"interactive": True})
            except Exception:  # noqa: BLE001
                return {"error": "current password is wrong"}
        admin.write({"password": new})
        return {"ok": True}

    def backup_config(self):
        """Config-only export (JSON download). The engine API key is
        deliberately NOT included - re-enter it after a restore."""
        eng = dict(self.engine_get())
        eng.pop("api_key", None)
        eng.pop("api_key_tail", None)
        return {
            "exported_at": str(fields.Datetime.now()),
            "engine": eng,
            "branding": self.branding_get(),
            "presets": self.modules_presets(),
            "token_cap_monthly": self.token_cap_get(),
            "modules_installed": self.env["ir.module.module"].sudo().search_count([("state", "=", "installed")]),
            "note": "engine API key is not exported - re-enter it in the console after restore",
        }

    def backup_zip_bytes(self):
        """Full database+filestore backup as a zip (Odoo dump service).
        Returns None if the pg_dump binary is unavailable on this host."""
        import io as _io

        from odoo.service import db as db_service

        buf = _io.BytesIO()
        try:
            db_service.dump_db(self.env.cr.dbname, buf, backup_format="zip")
        except Exception:  # noqa: BLE001
            return None
        return buf.getvalue()

    def handover_certificate(self):
        """Snapshot the delivery state and record it in the append-only
        audit chain (who/when/what shipped)."""
        check = self.handover_checklist()
        eng = self.engine_get()
        branding = self.branding_get()
        cert = {
            "generated_at": str(fields.Datetime.now()),
            "ready": check["ready"],
            "checklist": check["items"],
            "engine": {"provider": eng.get("provider", ""),
                       "chat_model": eng.get("chat_model", ""),
                       "api_key_set": bool(eng.get("has_key"))},
            "branding": {"brand_name": branding.get("brand_name", ""),
                         "logo_uploaded": bool(branding.get("logo_uploaded"))},
            "active_users": self.env["res.users"].sudo().search_count([("active", "=", True), ("share", "=", False)]),
            "modules_installed": self.env["ir.module.module"].sudo().search_count([("state", "=", "installed")]),
            "token_cap_monthly": self.token_cap_get(),
        }
        self.env["ai.gateway.audit.log"].sudo().log(
            2, "rpc", "handover_certificate", payload=cert, success=check["ready"], context={})
        return cert

    # ------------------------------------------------------------- branding
    BRANDING_TEXT = ("brand_name", "legal_name", "tagline", "product_title",
                     "support_email", "support_url", "footer_text", "login_message")
    BRANDING_COLORS = ("primary_color", "secondary_color", "accent_color",
                       "danger_color", "warning_color")

    def branding_get(self):
        Branding = self.env["ai.customer.branding"].sudo()
        rec = Branding.get_for_company() or Branding.search([], limit=1)
        if not rec:
            return {"exists": False, "brand_name": ""}
        out = {"exists": True, "brand_name": rec.brand_name or "",
               "logo_uploaded": bool(rec.logo),
               "logo_mimetype": rec.logo_mimetype or "",
               "favicon_uploaded": bool(rec.favicon)}
        for f in self.BRANDING_TEXT + self.BRANDING_COLORS:
            out[f] = rec[f] or ""
        out["font_family"] = rec.font_family or "system"
        out["border_radius"] = rec.border_radius or "comfortable"
        return out

    def branding_save(self, vals):
        Branding = self.env["ai.customer.branding"].sudo()
        data = {}
        for f in self.BRANDING_TEXT:
            if f in vals:
                val = (vals.get(f) or "").strip()
                if val:
                    data[f] = val
        for f in self.BRANDING_COLORS:
            if vals.get(f):
                data[f] = vals[f]
        for f in ("font_family", "border_radius"):
            if vals.get(f):
                data[f] = vals[f]
        if vals.get("logo_b64"):
            import base64 as _b64

            try:
                payload = vals["logo_b64"].split(",")[-1]
                data["logo"] = _b64.b64decode(payload)
            except Exception:  # noqa: BLE001
                return {"error": "logo file could not be decoded"}
            data["logo_filename"] = vals.get("logo_filename") or "logo.png"
            data["logo_mimetype"] = vals.get("logo_mimetype") or "image/png"
        if vals.get("favicon_b64"):
            import base64 as _b64

            try:
                data["favicon"] = _b64.b64decode(vals["favicon_b64"].split(",")[-1])
            except Exception:  # noqa: BLE001
                return {"error": "favicon file could not be decoded"}
            data["favicon_filename"] = vals.get("favicon_filename") or "favicon.png"
            data["favicon_mimetype"] = vals.get("favicon_mimetype") or "image/png"
        try:
            rec = Branding.get_for_company() or Branding.search([], limit=1)
            if rec:
                rec.write(data)
            else:
                data.setdefault("brand_name", self.env.company.name or "Company AI")
                data["company_id"] = self.env.company.id
                rec = Branding.create(data)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}
        return {"ok": True, "brand_name": rec.brand_name}

    # ------------------------------------------------------------ token cap
    CAP_PARAM = "admin_panel.token_cap_monthly"

    def token_cap_get(self):
        return int(self.env["ir.config_parameter"].sudo().get_param(self.CAP_PARAM, "0") or 0)

    def token_cap_set(self, cap):
        try:
            cap = max(0, int(cap or 0))
        except (TypeError, ValueError):
            return {"error": "cap must be a number (0 = unlimited)"}
        self.env["ir.config_parameter"].sudo().set_param(self.CAP_PARAM, str(cap))
        return {"ok": True, "cap": cap}

    # --------------------------------------------------------- token usage
    @staticmethod
    def _plain_name(value):
        """Translatable columns come back as {'en_US': ...} JSONB maps in
        this Odoo build - flatten to the plain display string."""
        if isinstance(value, dict):
            value = value.get("en_US") or next(iter(value.values()), "")
        return str(value or "")

    def token_usage(self, days=30):
        """Real consumption recorded by the gateway: chat turns and token
        footprint per employee and per department, plus a daily series.

        token_count is the gateway's documented estimate (~4 chars/token);
        the label travels with the payload so the UI never presents it as
        provider billing data."""
        try:
            days = max(1, min(int(days or 30), 365))
        except (TypeError, ValueError):
            days = 30
        self.env.cr.execute(
            """
            SELECT ag.user_id, u.login, p.name,
                   count(*) AS turns,
                   coalesce(sum(ag.token_count), 0) AS tokens,
                   max(ag.create_date) AS last_at,
                   d.name AS department
            FROM ai_gateway_audit_log ag
            JOIN res_users u ON u.id = ag.user_id
            JOIN res_partner p ON p.id = u.partner_id
            LEFT JOIN hr_employee e ON e.user_id = u.id
            LEFT JOIN hr_department d ON d.id = e.department_id
            WHERE ag.create_date >= now() - (interval '1 day' * %s)
              AND ag.source = 'chat'
            GROUP BY ag.user_id, u.login, p.name, d.name
            ORDER BY 5 DESC
            """,
            (days,),
        )
        users = [
            {"user_id": r[0], "login": r[1], "name": self._plain_name(r[2]),
             "turns": r[3], "tokens": r[4], "last": str(r[5] or ""),
             "department": self._plain_name(r[6])}
            for r in self.env.cr.fetchall()
        ]
        self.env.cr.execute(
            """
            SELECT date_trunc('day', create_date)::date AS day,
                   coalesce(sum(token_count), 0) AS tokens,
                   count(*) AS turns
            FROM ai_gateway_audit_log
            WHERE create_date >= now() - (interval '1 day' * %s)
              AND source = 'chat'
            GROUP BY 1 ORDER BY 1
            """,
            (days,),
        )
        daily = [{"day": str(r[0]), "tokens": r[1], "turns": r[2]}
                 for r in self.env.cr.fetchall()]
        users.sort(key=lambda row: -int(row["tokens"] or 0))
        dept_map = {}
        for row in users:
            key = str(row["department"] or "Without department")
            ent = dept_map.setdefault(key, {"department": key, "employees": 0,
                                            "turns": 0, "tokens": 0})
            ent["employees"] += 1
            ent["turns"] += int(row["turns"] or 0)
            ent["tokens"] += int(row["tokens"] or 0)
        self.env.cr.execute(
            """
            SELECT coalesce(sum(token_count), 0) FROM ai_gateway_audit_log
            WHERE source = 'chat'
              AND create_date >= date_trunc('month', now())
            """)
        month_tokens = int(self.env.cr.fetchone()[0] or 0)
        return {
            "days": days,
            "label": "estimated tokens (chars/4) recorded by the gateway",
            "cap_monthly": self.token_cap_get(),
            "month_tokens": month_tokens,
            "total_tokens": sum(u["tokens"] for u in users),
            "total_turns": sum(u["turns"] for u in users),
            "users": users,
            "departments": sorted(dept_map.values(), key=lambda d: -d["tokens"]),
            "daily": daily,
        }
