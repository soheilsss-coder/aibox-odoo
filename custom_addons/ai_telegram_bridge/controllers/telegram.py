"""
Telegram <-> Company Assistant bridge (built after researching
OdooPilot - github.com/arunrajiah/odoopilot - a real, well-built
open-source Odoo+Telegram/WhatsApp agent addon). Deliberately NOT
installing that addon as-is: it ships its own LLM choice and its own
write-confirmation/permission model, a second security surface
parallel to this project's own Risk Engine (#20) / Approval Object
(#21) / Context Firewall (#28) / gateway allowlist
(ai.gateway.model.policy) - the exact same concern already raised
about Buzz's own buzz-dev-mcp (roadmap #59).

This controller takes the other approach instead, matching the Buzz
bridge's own design exactly: it is a thin relay. Every Telegram message
becomes one direct call to the gateway's module-level `_run_chat()`
business logic, executed under the linked employee's OWN Odoo identity
(`link.user_id`) - the exact same code path as `/api/chat`, but
in-process: no HTTP loopback, no API-key round-trip. So a message from
Telegram gets exactly the same Risk Engine checks, Approval Object
gate, gateway allowlist, and audit log entry as a message typed into
the React frontend. This controller adds no privilege of its own and
bypasses nothing - it is a new DOOR into the same house, not a second
house.

WHAT THIS DOES NOT DO (be aware before piloting):
- No inline Approve/Refuse buttons for roadmap #21 Approval Objects,
  unlike OdooPilot's own UI for that. An action that needs someone
  else's approval still just tells the requester so in chat, same as
  today - the approver checks it through their own channel (web or
  their own linked Telegram chat). Real inline-button approval is a
  reasonable follow-up, not built here.
- No voice message transcription (OdooPilot has this via Whisper).
- Synchronous only, same limitation already documented for /api/chat
  itself - a slow multi-tool-call turn can take a while; Telegram does
  not need the webhook's own HTTP response to carry the reply (we push
  it separately via sendMessage), so this mostly self-corrects, but a
  VERY slow turn could still outlast Telegram's own webhook retry
  window. Not solved with a background job/queue here - same
  minimalism trade-off the rest of this project already makes
  (roadmap's "Known unresolved items" section).
"""
import json
import logging
import os
import time
import tempfile
import mimetypes
from collections import defaultdict, deque

import requests

from odoo import http
from odoo.http import request

from odoo.addons.ai_gateway.controllers.gateway import _run_chat

_logger = logging.getLogger(__name__)

# Same in-memory, single-process trade-off already documented for the
# gateway's own _check_rate_limit/_auth_fail_blocked (ai_gateway/
# controllers/gateway.py) - resets on an Odoo restart, fine for one
# delivery, revisit only if this ever runs behind multiple worker
# processes with no shared state.
_RATE_LIMIT_PER_MIN = int(os.environ.get("AI_TELEGRAM_RATE_LIMIT", "20"))
_chat_request_log = defaultdict(deque)

# Cap on how much media we are willing to pull from Telegram before
# processing it. Beyond this the relay refuses with a generic
# user-facing message rather than exhausting memory/bandwidth on an
# oversized upload.
_MAX_FILE_BYTES = int(os.environ.get("AI_TELEGRAM_MAX_FILE_MB", "25")) * 1024 * 1024

# Telegram redelivers an update if it doesn't get a fast-enough 200 -
# this dedups on update_id so a redelivered update never gets processed
# (and answered) twice. Capped size, not a database table: an infra
# dedup cache, not business data - same reasoning as the rate limiter.
_SEEN_UPDATES_MAX = 5000
_seen_update_ids = deque(maxlen=_SEEN_UPDATES_MAX)
_seen_update_ids_set = set()

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _rate_limited(chat_id):
    now = time.time()
    log = _chat_request_log[chat_id]
    while log and now - log[0] > 60:
        log.popleft()
    if len(log) >= _RATE_LIMIT_PER_MIN:
        return True
    log.append(now)
    return False


def _already_seen(update_id):
    if update_id in _seen_update_ids_set:
        return True
    if len(_seen_update_ids) == _SEEN_UPDATES_MAX:
        _seen_update_ids_set.discard(_seen_update_ids[0])
    _seen_update_ids.append(update_id)
    _seen_update_ids_set.add(update_id)
    return False


def _config(env, key, default=None):
    return env["ir.config_parameter"].sudo().get_param(f"ai_telegram_bridge.{key}", default)


def _bot_token(env):
    return _config(env, "bot_token")


def _telegram_api(env, method, payload=None, timeout=30):
    token = _bot_token(env)
    if not token:
        raise RuntimeError("Telegram bot token is not configured")
    resp = requests.post(
        TELEGRAM_API.format(token=token, method=method),
        json=payload or {}, timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or f"Telegram API {method} failed")
    return data.get("result")


def _download_telegram_file(env, file_id):
    meta = _telegram_api(env, "getFile", {"file_id": file_id})
    path = meta.get("file_path")
    if not path:
        raise RuntimeError("Telegram did not return a file path")
    token = _bot_token(env)
    url = f"https://api.telegram.org/file/bot{token}/{path}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    if len(resp.content) > _MAX_FILE_BYTES:
        raise RuntimeError(f"file exceeds the {_MAX_FILE_BYTES // (1024 * 1024)} MB download limit")
    return path, resp.content


_WHISPER_MODEL = None

def _transcribe_voice(content, suffix, model_name="small"):
    global _WHISPER_MODEL
    with tempfile.NamedTemporaryFile(suffix=suffix or ".ogg", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        if _WHISPER_MODEL is None:
            from faster_whisper import WhisperModel
            device = os.environ.get("AI_TELEGRAM_WHISPER_DEVICE", "auto")
            compute = os.environ.get("AI_TELEGRAM_WHISPER_COMPUTE_TYPE", "int8_float16")
            if device == "auto":
                try:
                    import torch
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except Exception:
                    device = "cpu"
            if device == "cpu" and compute == "int8_float16":
                compute = "int8"
            _WHISPER_MODEL = WhisperModel(model_name, device=device, compute_type=compute)
        segments, _ = _WHISPER_MODEL.transcribe(tmp_path, beam_size=5)
        return " ".join(seg.text.strip() for seg in segments).strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _create_user_attachment(env, user, thread_id, filename, content, mimetype=None):
    vals = {
        "name": filename or "telegram-file",
        "datas": __import__("base64").b64encode(content),
        "res_model": "llm.thread",
        "res_id": thread_id,
        "mimetype": mimetype or mimetypes.guess_type(filename or "")[0] or "application/octet-stream",
    }
    # Use the real employee's user context so create_uid is the actual owner;
    # the gateway later rejects attachment IDs that do not belong to that user.
    return env["ir.attachment"].with_user(user.id).create(vals)


def _send_telegram_message(env, chat_id, text):
    token = _bot_token(env)
    if not token:
        _logger.error("ai_telegram_bridge: no bot_token configured, cannot reply to chat %s", chat_id)
        return
    # Telegram's hard limit is 4096 chars per message - split long
    # replies instead of silently truncating them.
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [""]
    for chunk in chunks:
        try:
            requests.post(
                TELEGRAM_API.format(token=token, method="sendMessage"),
                json={"chat_id": chat_id, "text": chunk},
                timeout=15,
            )
        except requests.RequestException:
            _logger.exception("ai_telegram_bridge: failed to send reply to chat %s", chat_id)


class AiTelegramBridgeController(http.Controller):

    # type="http", NOT type="json": Telegram POSTs plain JSON (its own
    # Bot API update object), not Odoo's JSON-RPC envelope
    # ({"jsonrpc": "2.0", "method": "call", "params": {...}}) that
    # type="json" routes expect to receive - using type="json" here
    # would make Odoo's own dispatcher choke on every real Telegram
# The reply is produced by the shared _run_chat() business logic
        # (the same code path as /api/chat) and pushed back to Telegram
        # via sendMessage, so no JSON-RPC envelope is involved anywhere
        # in this controller.
    @http.route("/telegram/webhook", type="http", auth="none", csrf=False, methods=["POST"])
    def webhook(self, **params):
        env = request.env(su=True)  # no logged-in session yet - see telegram_link.find_by_chat_id docstring

        expected_secret = _config(env, "webhook_secret")
        got_secret = request.httprequest.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not expected_secret or got_secret != expected_secret:
            _logger.warning("ai_telegram_bridge: webhook call with missing/wrong secret token")
            return self._ok()  # always 200 to Telegram either way; just don't process it

        try:
            update = json.loads(request.httprequest.data or b"{}")
        except ValueError:
            return self._ok()

        update_id = update.get("update_id")
        if update_id is not None and _already_seen(update_id):
            return self._ok()

        message = update.get("message") or update.get("edited_message")
        if not message:
            return self._ok()

        chat_id = str(message["chat"]["id"])
        text = (message.get("text") or message.get("caption") or "").strip()
        attachment_payload = None
        voice_payload = None
        if message.get("document"):
            doc = message["document"]
            attachment_payload = (doc.get("file_id"), doc.get("file_name") or "telegram-document", doc.get("mime_type"))
        elif message.get("photo"):
            photo = message["photo"][-1]
            attachment_payload = (photo.get("file_id"), "telegram-photo.jpg", "image/jpeg")
        elif message.get("voice"):
            voice = message["voice"]
            voice_payload = (voice.get("file_id"), ".ogg")
        elif message.get("audio"):
            audio = message["audio"]
            voice_payload = (audio.get("file_id"), os.path.splitext(audio.get("file_name") or "telegram-audio.ogg")[1] or ".ogg")
        elif message.get("video") or message.get("video_note"):
            # Video analysis is intentionally not silently attempted. Store it
            # as an attachment so the same file-reader/vision pipeline can be
            # extended later, but tell the user that current extraction is
            # limited to supported document/image formats.
            video = message.get("video") or message.get("video_note")
            attachment_payload = (video.get("file_id"), "telegram-video.mp4", "video/mp4")

        if not text and not attachment_payload and not voice_payload:
            return self._ok()

        if _rate_limited(chat_id):
            _send_telegram_message(env, chat_id, "درخواست‌های زیادی در یک دقیقه - کمی صبر کن.")
            return self._ok()

        link = env["ai.gateway.telegram.link"].find_by_chat_id(chat_id)

        if not link:
            if text.startswith("/link "):
                code = text[len("/link "):].strip()
                user = env["ai.gateway.telegram.link.code"].consume(code)
                if not user:
                    _send_telegram_message(env, chat_id, "کد نامعتبر یا منقضی‌شده - یک کد جدید از داخل اودو بگیر.")
                    return self._ok()
                # Upsert, never blind-create: the user_id column is unique
                # (roadmap #19, one identity one chat), so after a
                # self-service unlink the row already exists (inactive) and
                # a create would violate the constraint and force an admin
                # to fix it manually. Re-pointing the SAME user's row at the
                # new chat keeps unlink -> relink fully self-service.
                existing = env["ai.gateway.telegram.link"].sudo().search(
                    [("user_id", "=", user.id)], limit=1)
                if existing:
                    existing.sudo().write({"chat_id": chat_id, "active": True})
                else:
                    env["ai.gateway.telegram.link"].sudo().create({
                        "user_id": user.id, "chat_id": chat_id,
                    })
                _send_telegram_message(
                    env, chat_id,
                    f"وصل شد - از این به بعد پیام‌هات اینجا به‌عنوان {user.name} پردازش می‌شن.",
                )
            else:
                _send_telegram_message(
                    env, chat_id,
                    "این چت هنوز به یک کاربر اودو وصل نیست. از داخل اودو یک کد بگیر "
                    "(My Account > Generate Telegram Link Code) و همینجا بفرست:\n/link CODE",
                )
            return self._ok()

        attachment_ids = []
        try:
            if voice_payload:
                file_id, suffix = voice_payload
                path, content = _download_telegram_file(env, file_id)
                transcript = _transcribe_voice(
                    content, suffix,
                    model_name=_config(env, "whisper_model", "small"),
                )
                if not transcript:
                    _send_telegram_message(env, chat_id, "صدای ارسالی قابل تشخیص نبود.")
                    return self._ok()
                text = (text + "\n" if text else "") + transcript
            if attachment_payload:
                file_id, filename, mimetype = attachment_payload
                _, content = _download_telegram_file(env, file_id)
                # Create the attachment in the actual employee's security
                # context. The gateway will verify ownership again.
                attachment = _create_user_attachment(
                    env, link.user_id, link.thread_id or False, filename, content, mimetype
                )
                attachment_ids.append(attachment.id)
                if not text:
                    text = "فایل ضمیمه را بررسی و محتوای مرتبط با درخواست من را تحلیل کن."
        except Exception as exc:  # noqa: BLE001
            _logger.exception("ai_telegram_bridge: media processing failed")
            _send_telegram_message(
                env, chat_id,
                "خطایی در دریافت یا تحلیل فایل/صدا رخ داد؛ لطفاً بعداً دوباره تلاش کنید.",
            )
            return self._ok()

        result = _run_chat(
            link.user_id, text, thread_id=link.thread_id or None, attachment_ids=attachment_ids
        )

        if result.get("error"):
            _send_telegram_message(env, chat_id, f"خطا: {result['error']}")
            return self._ok()

        link.touch(thread_id=result.get("thread_id"))
        _send_telegram_message(env, chat_id, result.get("reply") or "(پاسخ خالی)")
        return self._ok()

    @staticmethod
    def _ok():
        return request.make_response(
            json.dumps({"ok": True}),
            headers=[("Content-Type", "application/json; charset=utf-8")],
        )
