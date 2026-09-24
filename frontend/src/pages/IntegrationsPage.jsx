import React, { useEffect, useRef, useState } from "react";
import {
  getTelegramStatus, generateTelegramCode, unlinkTelegram, ApiError,
} from "../api/client.js";
import { Card, Button, Badge, Alert, EmptyState, Spinner, Modal } from "../components";

// Integrations page - closes the exact gap roadmap #60 (Telegram
// Bridge) left open on purpose: linking a Telegram chat used to be
// possible ONLY through an Odoo backend wizard ("AI Telegram" >
// "Generate Link Code"). This page is a second door onto the SAME
// flow (/api/integrations/telegram*, semantic_api.py), so an employee
// who lives entirely in this portal never has to open the Odoo
// backend just to connect their Telegram. Nothing about the linking
// rules themselves changed - same 8-character/10-minute code, same
// proof-of-identity requirement, same webhook secret check server-side.
//
// More integrations (WhatsApp, Slack, ...) would each get their own
// Card on this same page later - this file is written as "one
// Telegram card" rather than a single hardcoded layout, but a real
// second integration isn't built here (roadmap #60 only covers
// Telegram; don't imply otherwise in the UI).

const POLL_MS = 3000;
const fmtDate = (v) => (v ? new Date(v.replace(" ", "T") + "Z").toLocaleString("fa-IR") : "—");

export default function IntegrationsPage() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [linkInfo, setLinkInfo] = useState(null); // { code, bot_username, expires_at }
  const [generating, setGenerating] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [now, setNow] = useState(Date.now());
  const pollRef = useRef(null);
  const tickRef = useRef(null);

  function refresh() {
    return getTelegramStatus()
      .then((data) => {
        setStatus(data);
        return data;
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "خطا در بارگذاری"));
  }

  useEffect(() => {
    refresh();
    return () => {
      clearInterval(pollRef.current);
      clearInterval(tickRef.current);
    };
  }, []);

  // While a code is being shown and the user hasn't linked yet, poll
  // status in the background so the moment they send /link CODE on
  // Telegram, this page flips to "متصل" on its own - no manual
  // refresh needed, and no page reload required either.
  useEffect(() => {
    if (!linkInfo) return undefined;
    pollRef.current = setInterval(async () => {
      const data = await refresh();
      if (data && data.linked) {
        setLinkInfo(null);
        clearInterval(pollRef.current);
      }
    }, POLL_MS);
    tickRef.current = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearInterval(pollRef.current);
      clearInterval(tickRef.current);
    };
  }, [linkInfo]);

  async function handleGenerateCode() {
    setGenerating(true);
    setError("");
    try {
      const data = await generateTelegramCode();
      setLinkInfo({
        code: data.code,
        bot_username: data.bot_username,
        expires_at: Date.now() + data.expires_in_minutes * 60 * 1000,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "دریافت کد ناموفق بود");
    } finally {
      setGenerating(false);
    }
  }

  async function handleUnlink() {
    setUnlinking(true);
    setError("");
    try {
      const data = await unlinkTelegram();
      setStatus(data);
      setConfirmOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "قطع اتصال ناموفق بود");
    } finally {
      setUnlinking(false);
    }
  }

  if (!status) {
    return (
      <div>
        <h2>یکپارچه‌سازی‌ها</h2>
        <Alert>{error}</Alert>
        <Spinner />
      </div>
    );
  }

  if (!status.available) {
    return (
      <div>
        <h2>یکپارچه‌سازی‌ها</h2>
        <Card title="تلگرام">
          <EmptyState text="یکپارچه‌سازی تلگرام روی این سیستم نصب نشده - از ادمین بخواه ماژول ai_telegram_bridge را فعال کند." />
        </Card>
      </div>
    );
  }

  const remainingMs = linkInfo ? linkInfo.expires_at - now : 0;
  const remainingLabel = remainingMs > 0
    ? `${Math.floor(remainingMs / 60000)}:${String(Math.floor((remainingMs % 60000) / 1000)).padStart(2, "0")}`
    : null;
  const codeExpired = linkInfo && remainingMs <= 0;

  return (
    <div>
      <h2>یکپارچه‌سازی‌ها</h2>
      <Alert>{error}</Alert>

      <Card
        title="تلگرام"
        actions={<Badge tone={status.linked ? "success" : "neutral"}>{status.linked ? "متصل" : "متصل نیست"}</Badge>}
      >
        <p className="muted">
          پیام‌هات از تلگرام به دستیار سازمانی برسه و جواب بگیری - دقیقاً با همون سطح دسترسی
          حساب کاربری خودت، بدون نیاز به باز کردن بک‌اند اودو.
        </p>

        {status.linked && (
          <>
            <div style={{ display: "flex", gap: 24, margin: "12px 0" }}>
              <div>
                <div className="muted">تاریخ اتصال</div>
                <strong>{fmtDate(status.linked_date)}</strong>
              </div>
              <div>
                <div className="muted">آخرین پیام</div>
                <strong>{fmtDate(status.last_message_date)}</strong>
              </div>
            </div>
            <Button variant="danger" onClick={() => setConfirmOpen(true)}>قطع اتصال</Button>
          </>
        )}

        {!status.linked && !linkInfo && (
          <Button onClick={handleGenerateCode} loading={generating}>دریافت کد اتصال</Button>
        )}

        {!status.linked && linkInfo && (
          <div>
            <p>
              {linkInfo.bot_username ? (
                <>در تلگرام به ربات <strong dir="ltr">@{linkInfo.bot_username}</strong> برو و این پیام را بفرست:</>
              ) : (
                "به ربات تلگرام شرکت پیام زیر را بفرست:"
              )}
            </p>
            <p><span className="ds-code">/link {linkInfo.code}</span></p>
            {!codeExpired ? (
              <p className="muted">این کد تا {remainingLabel} دیگر معتبر است - این صفحه به‌محض اتصال خودش به‌روز می‌شود.</p>
            ) : (
              <Alert tone="danger">کد منقضی شد - یک کد جدید بگیر.</Alert>
            )}
            <Button
              variant="ghost" onClick={handleGenerateCode} loading={generating}
              disabled={!codeExpired}
            >
              کد جدید
            </Button>
          </div>
        )}
      </Card>

      <Modal
        open={confirmOpen}
        title="قطع اتصال تلگرام"
        onClose={() => setConfirmOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>انصراف</Button>
            <Button variant="danger" onClick={handleUnlink} loading={unlinking}>قطع اتصال</Button>
          </>
        }
      >
        <p>اتصال تلگرام قطع می‌شود و دیگر پیام‌هایی که از آن چت می‌فرستی پردازش نمی‌شوند. هر وقت خواستی می‌توانی دوباره وصل شوی.</p>
      </Modal>
    </div>
  );
}
