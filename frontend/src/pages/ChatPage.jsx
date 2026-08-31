import React, { useRef, useState } from "react";
import { streamChat, analyzeFile, ApiError } from "../api/client.js";
import { Card, Button, Alert, EmptyState, Spinner } from "../components";

export default function ChatPage({ user }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [threadId, setThreadId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState(null);
  const [recording, setRecording] = useState(false);
  const fileRef = useRef(null);
  const abortRef = useRef(null);

  const closeAssistantBubble = () => {
    setThinking(false);
    setMessages((m) => [...m, { role: "assistant", text: "" }]);
  };

  async function handleSend(e) {
    if (e && e.preventDefault) e.preventDefault();
    const text = input;
    if ((!text.trim() && !file) || busy) return;
    setInput("");
    setError("");
    setMessages((m) => [...m, { role: "user", text: text.trim() || "[فایل]" }]);
    setBusy(true);
    abortRef.current = new AbortController();
    try {
      let effective = text.trim();
      if (file) {
        const b64 = await new Promise((resolve, reject) => {
          const fr = new FileReader();
          fr.onload = () => resolve(String(fr.result).split(",")[1]);
          fr.onerror = reject;
          fr.readAsDataURL(file);
        });
        const analysis = await analyzeFile({
          filename: file.name,
          data_base64: b64,
          question: text.trim() || "این فایل را تحلیل کن",
        });
        effective = `فایل پیوست ${file.name} را در نظر بگیر. تحلیل استخراج‌شده:\n${analysis.analysis}\n\nدرخواست کاربر: ${text.trim()}`;
        // Splice the real prompt into the already-rendered user bubble.
        setMessages((m) => m.map((msg, i) => i === m.length - 1 ? { ...msg, text: effective } : msg));
      }
      closeAssistantBubble();
      await streamChat(
        { message: effective, thread_id: threadId },
        {
          signal: abortRef.current.signal,
          onThinking: () => setThinking(true),
          onDelta: ({ text }) => setMessages((m) => {
            const next = [...m];
            next[next.length - 1] = { ...next[next.length - 1], text: (next[next.length - 1].text || "") + (text || "") };
            return next;
          }),
          onDone: ({ thread_id }) => {
            setThinking(false);
            setThreadId(thread_id);
            setFile(null);
          },
          onError: (parsed) => {
            setThinking(false);
            setMessages((m) => m.filter((msg) => msg.role !== "assistant" || msg.text !== ""));
            throw new ApiError(parsed.error || "ارسال پیام ناموفق بود", 0);
          },
        },
      );
    } catch (err) {
      setThinking(false);
      setMessages((m) => m.filter((msg) => msg !== null && !(msg.role === "assistant" && msg.text === "")));
      if (err?.name !== "AbortError") setError(err instanceof ApiError ? err.message : "ارسال پیام ناموفق بود");
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  const voice = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { alert("تشخیص صدا در این مرورگر در دسترس نیست."); return; }
    const rec = new SR();
    rec.lang = "fa-IR";
    rec.onstart = () => setRecording(true);
    rec.onend = () => setRecording(false);
    rec.onresult = (ev) => setInput((v) => `${v} ${ev.results[0][0].transcript}`.trim());
    rec.start();
  };

  return (
    <div style={{ maxWidth: 820, margin: "0 auto" }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">AI WORKSPACE</div>
          <h1>گفتگو با سازمان</h1>
          <p>پاسخ به‌صورت تدریجی (streaming) دریافت می‌شود؛ فایل و صدا هم می‌توانید ارسال کنید.</p>
        </div>
      </div>

      {error && <Alert>{error}</Alert>}

      <Card style={{ minHeight: 320 }}>
        {messages.length === 0 && (
          <EmptyState text="هر سوالی درباره مرخصی، اسناد یا کارها بپرسید." />
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 12, textAlign: m.role === "user" ? "left" : "right" }}>
            <div className="muted" style={{ fontSize: 12 }}>
              {m.role === "user" ? "شما" : "دستیار"}
            </div>
            <div style={{ whiteSpace: "pre-wrap" }}>{m.text}</div>
          </div>
        ))}
        {thinking && (
          <div style={{ textAlign: "right", marginBottom: 12 }}>
            <div className="muted" style={{ fontSize: 12 }}>دستیار</div>
            <Spinner label="در حال پردازش..." />
          </div>
        )}
      </Card>

      <Card>
        <form onSubmit={handleSend}>
          {file && (
            <div className="muted" style={{ marginBottom: 8 }}>
              فایل پیوست: {file.name}
              <button type="button" className="ghost-btn" style={{ marginInlineStart: 8 }} onClick={() => setFile(null)}>حذف</button>
            </div>
          )}
          <TextArea
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="پیام خود را بنویسید..."
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
          />
          <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
            <input
              ref={fileRef}
              type="file"
              hidden
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <Button type="button" variant="ghost" onClick={() => fileRef.current?.click()}>فایل</Button>
            <Button type="button" variant="ghost" onClick={voice}>{recording ? "در حال شنیدن..." : "صدا"}</Button>
            <div style={{ flex: 1 }} />
            {busy && <Button type="button" variant="danger" onClick={() => abortRef.current?.abort()}>توقف</Button>}
            <Button type="submit" disabled={busy} loading={busy}>ارسال</Button>
          </div>
        </form>
      </Card>
    </div>
  );
}