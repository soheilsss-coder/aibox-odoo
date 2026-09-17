import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { streamChat, analyzeFile, ApiError } from "../api/client.js";
import { Alert, Icon, IconButton } from "../components";
import { createThread, getThread, addMessage, setServerId, useThreads } from "../hooks/useThreads.js";

const SUGGESTIONS = [
  { icon: "clock", text: "Request time off for next week" },
  { icon: "tasks", text: "Create a follow-up task for the board demo" },
  { icon: "search", text: "Find the fall pricing guide in our documents" },
  { icon: "users", text: "Who is in the Sales department?" },
];

export default function ChatPage({ user, chatsOpen, onOpenChats }) {
  const { id: routeThreadId } = useParams();
  const navigate = useNavigate();
  useThreads(); // re-render when the store changes

  const thread = routeThreadId ? getThread(routeThreadId) : null;
  const messages = thread?.messages || [];

  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamBuf, setStreamBuf] = useState("");
  const [file, setFile] = useState(null);
  const [recording, setRecording] = useState(false);
  const [lastPrompt, setLastPrompt] = useState(null);

  const fileRef = useRef(null);
  const scrollRef = useRef(null);
  const taRef = useRef(null);
  const recRef = useRef(null);
  // The stream writes into this target thread even if the user switches
  // chats mid-stream; the buffer mirrors streamBuf so onDone can commit it.
  const targetRef = useRef({ threadId: null, buf: "" });

  const empty = messages.length === 0 && !streamBuf;

  // Switching chats: stop showing the previous stream buffer (it keeps
  // streaming into its own thread in the background and is persisted).
  useEffect(() => { setStreamBuf(""); setError(""); setFile(null); }, [routeThreadId]);

  // Auto-scroll to the latest token.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, streamBuf, thinking, routeThreadId]);

  // Auto-resize the composer textarea.
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 152) + "px";
  }, [input]);

  // Focus the composer on mount / after sending.
  useEffect(() => { if (!busy) taRef.current?.focus(); }, [busy, empty, routeThreadId]);

  async function send(rawText) {
    const text = (rawText ?? input).trim();
    if ((!text && !file) || busy) return;
    setInput("");
    setError("");

    // First message of a fresh chat: create the thread and move the URL to
    // /chat/<id> so the sidebar entry and the shareable location appear.
    let activeId = routeThreadId;
    if (!activeId || !getThread(activeId)) {
      const t = createThread();
      activeId = t.id;
      navigate(`/chat/${t.id}`, { replace: true });
    }
    targetRef.current = { threadId: activeId, buf: "" };

    addMessage(activeId, { role: "user", text: text || `Attached: ${file.name}` });
    setBusy(true);
    try {
      let effective = text;
      if (file) {
        const current = file;
        setFile(null);
        setAnalyzing(true);
        const b64 = await new Promise((resolve, reject) => {
          const fr = new FileReader();
          fr.onload = () => resolve(String(fr.result).split(",")[1]);
          fr.onerror = reject;
          fr.readAsDataURL(current);
        });
        const analysis = await analyzeFile({
          filename: current.name,
          data_base64: b64,
          question: text || "Analyze this file",
        }).finally(() => setAnalyzing(false));
        effective = `Consider the attached file ${current.name}. Extracted analysis:\n${analysis.analysis}\n\nUser request: ${text || "Analyze it"}`;
      }
      setLastPrompt(effective);
      setThinking(true);
      setStreaming(true);
      const serverId = getThread(activeId)?.serverId || null;
      await streamChat(
        { message: effective, thread_id: serverId },
        {
          onThinking: () => setThinking(true),
          onDelta: ({ text: delta }) => {
            setThinking(false);
            targetRef.current.buf += delta || "";
            if (targetRef.current.threadId === routeThreadId) setStreamBuf(targetRef.current.buf);
          },
          onDone: ({ thread_id }) => {
            setThinking(false);
            setStreaming(false);
            const tgt = targetRef.current;
            if (tgt.threadId && tgt.buf) addMessage(tgt.threadId, { role: "assistant", text: tgt.buf });
            if (tgt.threadId && thread_id) setServerId(tgt.threadId, thread_id);
            targetRef.current = { threadId: null, buf: "" };
            setStreamBuf("");
          },
          onError: (parsed) => {
            setThinking(false);
            setStreaming(false);
            targetRef.current = { threadId: null, buf: "" };
            setStreamBuf("");
            setError(parsed.error || "Failed to send the message.");
          },
        }
      );
    } catch (err) {
      setThinking(false);
      setStreaming(false);
      targetRef.current = { threadId: null, buf: "" };
      setStreamBuf("");
      setError(err instanceof ApiError ? err.message : "Failed to send the message.");
    } finally {
      setBusy(false);
      setAnalyzing(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function toggleVoice() {
    if (recording) {
      recRef.current?.stop();
      setRecording(false);
      return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { setError("Voice input is not available in this browser."); return; }
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.onresult = (e) => {
      const transcript = Array.from(e.results).map((r) => r[0].transcript).join(" ");
      setInput((v) => (v ? v + " " : "") + transcript);
    };
    rec.onerror = () => setRecording(false);
    rec.onend = () => setRecording(false);
    recRef.current = rec;
    setRecording(true);
    rec.start();
  }

  const firstName = (user.name || "there").split(" ")[0];
  const view = streamBuf
    ? [...messages, { role: "assistant", text: streamBuf }]
    : messages;

  return (
    <div className="chat-page">
      {!chatsOpen && (
        <button className="peek-chats" onClick={onOpenChats} aria-label="Show chats panel">
          <Icon name="message" size={15} />
          <span>Chats</span>
        </button>
      )}
      <div className="chat-scroll" ref={scrollRef}>
        {empty ? (
          <div className="hero">
            <div className="hero-orb orb-glow"><span className="orb" /></div>
            <h1>Hello, {firstName}</h1>
            <p>Your AI workspace is ready. Ask anything — it checks your role, permissions and workflow before acting.</p>
            <div className="suggest-grid">
              {SUGGESTIONS.map((s) => (
                <button key={s.text} className="suggest" onClick={() => send(s.text)}>
                  <Icon name={s.icon} size={17} />
                  <span>{s.text}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          view.map((msg, i) =>
            msg.role === "user" ? (
              <div className="msg user" key={i}>
                <div className="msg-text">{msg.text}</div>
              </div>
            ) : (
              <div className="msg assistant" key={i}>
                <span className="orb" />
                <div className="msg-body">
                  <div className="msg-role">Nova</div>
                  <div className="msg-text">
                    {msg.text}
                    {msg.text === "" && thinking && (
                      <span className="thinking"><i /><i /><i /></span>
                    )}
                    {streamBuf && i === view.length - 1 && <span className="caret" />}
                  </div>
                </div>
              </div>
            )
          )
        )}
        {analyzing && (
          <div className="tool-note"><span className="bgd-dot" /> Analyzing your file…</div>
        )}
      </div>

      <div className="composer-zone">
        <Alert onDismiss={() => setError("")}>
          {error}
          {error && lastPrompt && !busy ? (
            <button className="alert-close" style={{ textDecoration: "underline", opacity: 1 }} onClick={() => send(lastPrompt)}>
              Retry
            </button>
          ) : null}
        </Alert>

        {file && (
          <div className="attach-row">
            <span className="attach-chip">
              <Icon name="paperclip" size={14} />
              {file.name}
              <button onClick={() => setFile(null)} aria-label="Remove file"><Icon name="x" size={13} /></button>
            </span>
          </div>
        )}

        <form
          className="composer"
          onSubmit={(e) => { e.preventDefault(); send(); }}
        >
          <IconButton icon="paperclip" label="Attach a file" onClick={() => fileRef.current?.click()} />
          <input
            ref={fileRef}
            type="file"
            hidden
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
          <textarea
            ref={taRef}
            rows={1}
            placeholder={empty ? "Ask anything…" : "Reply to Nova…"}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            aria-label="Message Nova"
          />
          <IconButton
            icon="mic"
            label={recording ? "Stop recording" : "Voice input"}
            className={recording ? "recording btn-mic" : "btn-mic"}
            onClick={toggleVoice}
          />
          <button type="submit" className="btn-send" disabled={(!input.trim() && !file) || busy} aria-label="Send message">
            <Icon name="send" size={17} />
          </button>
        </form>
        <div className="composer-hint">Enter to send · Shift + Enter for a new line · Nova can make mistakes, verify important actions</div>
      </div>
    </div>
  );
}
