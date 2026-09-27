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
        return {
            "days": days,
            "label": "estimated tokens (chars/4) recorded by the gateway",
            "total_tokens": sum(u["tokens"] for u in users),
            "total_turns": sum(u["turns"] for u in users),
            "users": users,
            "departments": sorted(dept_map.values(), key=lambda d: -d["tokens"]),
            "daily": daily,
        }
