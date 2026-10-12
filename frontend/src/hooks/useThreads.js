// =============================================================================
// Chat thread store — ChatGPT-style conversation history.
//
// Each thread is its own conversation with its own message history, persisted
// to localStorage so chats survive reloads and new browser sessions (the
// "memory" users expect). The gateway keeps server-side context per
// thread_id; since no public /api endpoint lists threads, the readable
// history lives here client-side while `serverId` keeps the backend thread
// linked.
// =============================================================================
import { useSyncExternalStore } from "react";

const KEY = "aibox.threads";

let cache = null;
let cacheVersion = 0;
const listeners = new Set();

function load() {
  if (cache) return cache;
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "[]");
    cache = Array.isArray(raw) ? raw : [];
  } catch {
    cache = [];
  }
  return cache;
}

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(cache)); } catch { /* storage full/blocked */ }
  cacheVersion += 1;
  listeners.forEach((l) => l());
}

export function createThread() {
  const t = {
    id: `t-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    title: "",
    serverId: null,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messages: [],
  };
  load().unshift(t);
  save();
  return t;
}

export function getThread(id) {
  return load().find((t) => t.id === id) || null;
}

export function addMessage(threadId, msg) {
  const t = getThread(threadId);
  if (!t) return;
  t.messages.push({ role: msg.role, text: msg.text, at: Date.now() });
  t.updatedAt = Date.now();
  if (!t.title && msg.role === "user") t.title = String(msg.text || "").trim().slice(0, 60) || "New chat";
  const arr = load();
  arr.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  save();
}

export function setServerId(threadId, serverId) {
  const t = getThread(threadId);
  if (!t || !serverId || t.serverId === serverId) return;
  t.serverId = serverId;
  save();
}

export function removeThread(threadId) {
  cache = load().filter((t) => t.id !== threadId);
  save();
}

export function useThreads() {
  useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => listeners.delete(cb); },
    () => cacheVersion
  );
  return load();
}

// "Today" / "Yesterday" / "Sep 14" — rows in the sidebar.
export function relDate(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  const now = new Date();
  const startOfDay = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86400000);
  if (days <= 0) return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
