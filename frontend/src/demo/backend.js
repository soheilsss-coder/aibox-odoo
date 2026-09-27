// =============================================================================
// Browser demo backend — lets the static GitHub Pages build behave EXACTLY
// like it does behind the real Odoo gateway / the dev mock server.
//
// Only bundled when VITE_DEMO_MODE=1 (see src/api/client.js). It answers
// /api/* calls through the shared mock-core router and returns real
// `Response` objects, so every component / the SSE parser behaves the same
// as in production. State lives in memory for the session (per tab); small
// artificial delays keep spinners and streaming believable.
// =============================================================================
import { createMockState, handleApi, chatStreamChunks, authenticate } from "./mock-core.mjs";

// --- demo persistence (per tab) -------------------------------------------
// The engine lives in JS memory, so a full reload would lose both the demo
// session and anything the user created (tasks, documents, grants...).
// We persist the mutable collections + re-accept the stored api key, making
// reloads feel exactly like a real backend. Same storage the client itself
// uses ("aibox.apiKey"), demoscoped to this tab's sessionStorage.
const PERSIST_KEY = "aibox.demoState";
let seed = null;
try { seed = JSON.parse(sessionStorage.getItem(PERSIST_KEY) || "null"); } catch { /* fall back to defaults */ }
const state = createMockState(seed);
try {
  const stored = sessionStorage.getItem("aibox.apiKey");
  if (stored) {
    const sid = `restored-${stored.slice(0, 12)}`;
    state.sessions.set(sid, { login: state.user.login });
    state.apiKeys.set(stored, sid);
  }
} catch { /* storage can be blocked in iframes */ }
function persist() {
  try {
    sessionStorage.setItem(PERSIST_KEY, JSON.stringify({
      departments: state.departments, agents: state.agents, tasks: state.tasks,
      approvals: state.approvals, notifications: state.notifications, leaves: state.leaves,
      documents: state.documents, grants: state.grants, roles: state.roles, users: state.users,
      branding: state.branding, telegram: state.telegram, nextId: state.nextId,
    }));
  } catch { /* non-fatal: fresh defaults next reload */ }
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const latency = () => 160 + Math.random() * 180;

function toResponse(res) {
  return new Response(JSON.stringify(res.json), {
    status: res.status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

function parsePath(path) {
  const [pathname, qs = ""] = String(path).split("?");
  const query = {};
  new URLSearchParams(qs).forEach((v, k) => { query[k] = v; });
  return { pathname, query };
}

export async function demoRequest(path, { method = "GET", body, apiKey = "" } = {}) {
  await wait(latency());
  const { pathname, query } = parsePath(path);
  const res = handleApi(state, { method, path: pathname, query, body: body || {}, auth: { apiKey } });
  persist();
  return toResponse(res);
}

export async function demoStream(payload, apiKey = "") {
  await wait(latency());
  // Same gate as the server: no session, no stream.
  if (!authenticate(state, { apiKey })) {
    return new Response(JSON.stringify({ error: "Your session is not valid. Please sign in." }), {
      status: 401,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  }
  const chunks = chatStreamChunks(payload.message, payload.thread_id);
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      let i = 0;
      const push = () => {
        if (i >= chunks.length) { controller.close(); return; }
        const [event, data] = chunks[i];
        controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
        i += 1;
        const next = event === "thinking" ? 90 : 34 + Math.random() * 26;
        setTimeout(push, next);
      };
      setTimeout(push, 60);
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream; charset=utf-8" },
  });
}
