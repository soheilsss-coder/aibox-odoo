import React, { useEffect, useRef, useState } from "react";
import { getTelegramStatus, generateTelegramCode, unlinkTelegram, ApiError } from "../api/client.js";
import { Alert, Badge, Button, Card, EmptyState, Icon, IconButton, Modal, Spinner } from "../components";

// Telegram linking — a self-serve door onto the backend's existing wizard
// flow: one-time 8-char / 10-minute code, /link CODE to the bot, instant
// status flip via background polling.
const POLL_MS = 3000;
const fmtDate = (v) => (v ? new Date(v.replace(" ", "T") + "Z").toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" }) : "—");

export default function IntegrationsPage() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [linkInfo, setLinkInfo] = useState(null); // { code, bot_username, expires_at }
  const [generating, setGenerating] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [now, setNow] = useState(Date.now());
  const pollRef = useRef(null);
  const tickRef = useRef(null);

  function refresh() {
    return getTelegramStatus()
      .then((data) => { setStatus(data); return data; })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load."));
  }

  useEffect(() => {
    refresh();
    return () => { clearInterval(pollRef.current); clearInterval(tickRef.current); };
  }, []);

  // While a code is on screen and the user is still unlinked, poll so the
  // page flips to "Connected" by itself the moment they send /link CODE.
  useEffect(() => {
    if (!linkInfo) return undefined;
    pollRef.current = setInterval(async () => {
      const data = await refresh();
      if (data && data.linked) { setLinkInfo(null); clearInterval(pollRef.current); }
    }, POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [linkInfo]);

  // 1s ticker for the countdown display.
  useEffect(() => {
    if (!linkInfo) return undefined;
    tickRef.current = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tickRef.current);
  }, [linkInfo]);

  async function handleGenerate() {
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
      setError(err instanceof ApiError ? err.message : "Could not generate a code.");
    } finally {
      setGenerating(false);
    }
  }

  async function handleUnlink() {
    setUnlinking(true);
    setError("");
    try {
      await unlinkTelegram();
      setConfirmOpen(false);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not unlink.");
    } finally {
      setUnlinking(false);
    }
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(`/link ${linkInfo.code}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch { /* clipboard may be blocked */ }
  }

  if (!status && !error) return <Spinner />;
  if (status && !status.available) {
    return (
      <>
        <header className="page-head"><div><div className="eyebrow">Connections</div><h1>Integrations</h1></div></header>
        <Card><EmptyState icon="plug" title="Telegram not installed" text="The Telegram bridge is not enabled on this system — ask an admin to enable the ai_telegram_bridge module." /></Card>
      </>
    );
  }

  const remainingMs = linkInfo ? linkInfo.expires_at - now : 0;
  const expired = linkInfo && remainingMs <= 0;
  const mm = Math.max(0, Math.floor(remainingMs / 60000));
  const ss = Math.max(0, Math.floor((remainingMs % 60000) / 1000));

  return (
    <>
      <header className="page-head">
        <div>
          <div className="eyebrow">Connections</div>
          <h1>Integrations</h1>
          <p>Connect your assistant to the channels you already use.</p>
        </div>
      </header>

      <Alert onDismiss={() => setError("")}>{error}</Alert>

      {status && (
        <Card
          title={
            <span className="h-stack" style={{ gap: 10 }}>
              <span className="icon-tile grad"><Icon name="message" size={18} /></span> Telegram
            </span>
          }
          actions={
            <Badge tone={status.linked ? "ok" : "neutral"} dot>{status.linked ? "Connected" : "Not connected"}</Badge>
          }
        >
          {status.linked && (
            <div className="v-stack" style={{ gap: 14 }}>
              <div className="h-stack spread wrap">
                <div>
                  <div className="small muted">Linked on</div>
                  <div className="strong">{fmtDate(status.linked_date)}</div>
                </div>
                <div>
                  <div className="small muted">Last message</div>
                  <div className="strong">{fmtDate(status.last_message_date)}</div>
                </div>
                <Button variant="danger" size="sm" icon="unlink" onClick={() => setConfirmOpen(true)}>Disconnect</Button>
              </div>
              <p className="muted small">Messages you send the bot are answered by your assistant with your own permissions.</p>
            </div>
          )}

          {!status.linked && !linkInfo && (
            <div className="h-stack spread wrap">
              <p className="muted">Chat with your assistant from Telegram — same identity, same permissions.</p>
              <Button variant="primary" icon="link" onClick={handleGenerate} loading={generating}>Connect Telegram</Button>
            </div>
          )}

          {!status.linked && linkInfo && (
            <div className="v-stack" style={{ gap: 14 }}>
              {expired ? (
                <>
                  <Alert tone="warn">This code expired. Generate a new one.</Alert>
                  <div><Button variant="primary" icon="refresh" onClick={handleGenerate} loading={generating}>New code</Button></div>
                </>
              ) : (
                <>
                  <p className="muted small">
                    In Telegram, open <strong dir="ltr">@{linkInfo.bot_username || "your-company-bot"}</strong> and send:
                  </p>
                  <div className="code-line spread">
                    <span className="kbd">/link {linkInfo.code}</span>
                    <span className="h-stack">
                      <Badge tone="warn"><Icon name="clock" size={12} /> {mm}:{String(ss).padStart(2, "0")}</Badge>
                      <IconButton icon="copy" label="Copy command" onClick={handleCopy} />
                    </span>
                  </div>
                  {copied && <Alert tone="ok">Copied to clipboard.</Alert>}
                  <p className="faint xsmall">This page updates automatically once the bot confirms the link.</p>
                </>
              )}
            </div>
          )}
        </Card>
      )}

      <Modal
        open={confirmOpen}
        title="Disconnect Telegram?"
        onClose={() => setConfirmOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>Keep connected</Button>
            <Button variant="danger" onClick={handleUnlink} loading={unlinking}>Disconnect</Button>
          </>
        }
      >
        <p className="muted">You will stop receiving assistant replies in Telegram. You can link again any time with a new code.</p>
      </Modal>
    </>
  );
}
