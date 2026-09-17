import React, { useEffect, useMemo, useState } from "react";
import {
  ApiError, getBuzzChannels, getBuzzMessages, optInBuzzChannel, optOutBuzzChannel, postBuzzMessage,
} from "../api/client.js";
import { Alert, Button, Card, EmptyState, Input, Spinner, TextArea } from "../components";

export default function BuzzPage({ user }) {
  const [channels, setChannels] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [trigger, setTrigger] = useState("@buzz");
  const [agentName, setAgentName] = useState("Buzz");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const selected = useMemo(
    () => channels.find((channel) => channel.id === selectedId) || null,
    [channels, selectedId],
  );

  async function loadChannels() {
    try {
      const data = await getBuzzChannels();
      const next = data.channels || [];
      setChannels(next);
      if (!selectedId && next.length) setSelectedId(next[0].id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "خطا در بارگذاری کانال‌های Buzz");
    } finally {
      setLoading(false);
    }
  }

  async function loadMessages(channelId = selectedId) {
    if (!channelId) return;
    try {
      const data = await getBuzzMessages(channelId);
      setMessages(data.messages || []);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "خطا در بارگذاری پیام‌های گروه");
    }
  }

  useEffect(() => { loadChannels(); }, []);

  useEffect(() => {
    if (!selected) return undefined;
    setTrigger(selected.trigger || "@buzz");
    setAgentName(selected.agent || "Buzz");
    loadMessages(selected.id);
    const timer = window.setInterval(() => loadMessages(selected.id), 3000);
    return () => window.clearInterval(timer);
  }, [selectedId]);

  async function configureChannel(event) {
    event.preventDefault();
    if (!selected) return;
    setBusy("configure");
    setError("");
    try {
      await optInBuzzChannel(selected.id, trigger, agentName);
      await loadChannels();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "فعال‌سازی Buzz ناموفق بود");
    } finally {
      setBusy("");
    }
  }

  async function disableChannel() {
    if (!selected) return;
    setBusy("disable");
    setError("");
    try {
      await optOutBuzzChannel(selected.id);
      await loadChannels();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "غیرفعال‌سازی Buzz ناموفق بود");
    } finally {
      setBusy("");
    }
  }

  async function send(event) {
    event.preventDefault();
    const body = draft.trim();
    if (!body || !selected) return;
    setBusy("send");
    setError("");
    try {
      await postBuzzMessage(selected.id, body);
      setDraft("");
      await loadMessages(selected.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ارسال پیام ناموفق بود");
    } finally {
      setBusy("");
    }
  }

  return <div className="buzz-page">
    <header className="page-head">
      <div>
        <div className="eyebrow">GROUP COLLABORATION</div>
        <h1> Buzz</h1>
        <p>همان کانال گروهی سازمان؛ Buzz به‌عنوان عضو کانال حضور دارد و فقط با mention پاسخ می‌دهد.</p>
      </div>
      <span className="pill pill-success">ACL + Gateway protected</span>
    </header>
    {error && <Alert tone="danger">{error}</Alert>}
    {loading ? <Spinner label="در حال بارگذاری کانال‌ها…" /> : !channels.length ? (
      <Card><EmptyState text="کانال گروهی پیدا نشد — ابتدا یک کانال گروهی در Discuss بسازید و این صفحه را دوباره باز کنید." /></Card>
    ) : <div className="buzz-layout">
      <Card className="buzz-channel-list">
        <div className="buzz-card-title"><strong>گروه‌ها</strong><span>{channels.length}</span></div>
        {channels.map((channel) => <button
          type="button"
          key={channel.id}
          className={`buzz-channel-item ${channel.id === selectedId ? "active" : ""}`}
          onClick={() => setSelectedId(channel.id)}
        >
          <strong>{channel.name}</strong>
          <small>{channel.member_count || 0} عضو · {channel.opted_in ? `${channel.agent || "Buzz"} فعال` : "فعال نشده"}</small>
        </button>)}
      </Card>
      {selected && <Card className="buzz-conversation">
        <div className="buzz-card-title">
          <div><strong>{selected.name}</strong><small>{selected.opted_in ? `Agent: ${selected.agent || "Buzz"}` : "Agent هنوز فعال نشده"}</small></div>
          {selected.opted_in && <span className="pill pill-success">@{(selected.trigger || "@buzz").replace(/^@/, "")}</span>}
        </div>
        <div className="buzz-message-list">
          {!messages.length && <EmptyState text="هنوز پیامی نیست — اولین پیام گروه را ارسال کنید." />}
          {messages.map((message) => <div className={`buzz-message ${message.type === "agent" ? "agent" : ""}`} key={message.id}>
            <div className="buzz-message-meta"><strong>{message.author || "عضو گروه"}</strong><small>{message.created_at}</small></div>
            <div>{message.body}</div>
          </div>)}
        </div>
        <form className="buzz-composer" onSubmit={send}>
          <TextArea rows={2} value={draft} onChange={(event) => setDraft(event.target.value)} disabled={busy === "send"} placeholder={selected.opted_in ? `برای پاسخ گرفتن ${selected.trigger || "@buzz"} را بنویسید…` : "پیام گروه…"} />
          <div className="buzz-composer-actions"><span className="muted">ارسال به‌عنوان {user?.name || "کاربر"}</span><Button type="submit" loading={busy === "send"} disabled={!draft.trim() || busy === "send"}>ارسال</Button></div>
        </form>
      </Card>}
      {selected && <Card className="buzz-settings">
        <div className="buzz-card-title"><strong>Agent داخل گروه</strong><span className={`pill pill-${selected.opted_in ? "success" : "neutral"}`}>{selected.opted_in ? "فعال" : "خاموش"}</span></div>
        <form onSubmit={configureChannel}>
          <Input label="Trigger / mention" value={trigger} onChange={(event) => setTrigger(event.target.value)} placeholder="@buzz" />
          <Input label="نام Agent" value={agentName} onChange={(event) => setAgentName(event.target.value)} placeholder="Buzz" />
          <Button type="submit" loading={busy === "configure"}>{selected.opted_in ? "ذخیره تنظیمات" : "افزودن Buzz به گروه"}</Button>
          {selected.opted_in && <Button type="button" variant="danger" loading={busy === "disable"} onClick={disableChannel}>خارج کردن Agent</Button>}
        </form>
        <p className="muted">Agent فقط پیام‌هایی را می‌خواند که در همین کانال opt-in شده‌اند و trigger داشته باشند. اجرای ابزارها با دسترسی فرستنده انجام می‌شود، نه با دسترسی مدیر.</p>
      </Card>}
    </div>}
  </div>;
}
