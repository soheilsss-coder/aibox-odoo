let apiKey = "";
let csrfToken = "";
try {
  apiKey = sessionStorage.getItem("aibox.apiKey") || "";
  csrfToken = sessionStorage.getItem("aibox.csrf") || "";
} catch { /* storage can be blocked in iframes */ }

// Static-demo mode (GitHub Pages build): VITE_DEMO_MODE=1 routes every
// /api/* call through the in-browser mock engine (src/demo/backend.js)
// instead of the network, so the exact production UI runs fully offline.
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "1";
// Hybrid deployment: the UI can be hosted anywhere (e.g. GitHub Pages) while
// the real Odoo gateway lives elsewhere (e.g. Render). Set VITE_API_URL at
// build time to the backend origin; requests then go cross-origin with the
// stateless X-API-Key header path the gateway natively supports.
const API_BASE = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");
let demoBackendPromise = null;
const demoBackend = () => (demoBackendPromise ??= import("../demo/backend.js"));

export function getApiKey() { return apiKey; }
export function setApiKey(key) {
  apiKey = key || "";
  try {
    if (key) sessionStorage.setItem("aibox.apiKey", key);
    else sessionStorage.removeItem("aibox.apiKey");
  } catch { /* fall back to in-memory only */ }
}
function setCsrfToken(token) {
  csrfToken = token || "";
  try {
    if (token) sessionStorage.setItem("aibox.csrf", token);
    else sessionStorage.removeItem("aibox.csrf");
  } catch { /* fall back to in-memory only */ }
}
export function clearApiKey() { setApiKey(""); setCsrfToken(""); }

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function request(path, { method = "GET", body, jsonRpc = false } = {}) {
  const headers = {};
  // Cookie session is the primary auth path (same as production). The
  // X-API-Key header - also natively accepted by ai_gateway's
  // _authenticate() - is what keeps the session alive when the app is
  // shown inside a third-party context (preview iframes) where browsers
  // silently drop the ai_session cookie despite credentials: "include".
  if (apiKey) headers["X-API-Key"] = apiKey;
  // Production cookie sessions (ai_session) require a double-submit CSRF
  // token on every mutating request; /api/login returns it in the JSON body
  // (it also lands in the readable ai_csrf cookie). API-key clients are
  // exempt server-side, and the demo engine ignores headers entirely.
  if (csrfToken && String(method).toUpperCase() !== "GET") headers["X-CSRF-Token"] = csrfToken;
  let fetchBody;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    fetchBody = JSON.stringify(body);
  }
  const resp = DEMO_MODE
    ? await (await demoBackend()).demoRequest(path, { method, body, apiKey })
    : await fetch(API_BASE + path, { method, headers, body: fetchBody, credentials: "include" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data.error) throw new ApiError(data.error || `request failed (${resp.status})`, resp.status);
  return data;
}

export async function login(loginId, password) {
  const data = await request("/api/login", { method: "POST", body: { login: loginId, password } });
  // Backends that hand back a key (or the dev mock) enable the header
  // fallback; cookie-only backends simply don't send one and nothing
  // changes compared to before. The production gateway additionally
  // returns a session-bound csrf_token every cookie-mode POST needs.
  if (data.api_key) setApiKey(data.api_key);
  if (data.csrf_token) setCsrfToken(data.csrf_token);
  return data;
}
export const getMe = () => request("/api/me");
export function logout() {
  clearApiKey();
  return request("/api/logout", { method: "POST" });
}
export const getMyCapabilities = () => request("/api/me/capabilities");
export const getWorkspace = () => request("/api/workspace");
export const getDepartments = () => request("/api/departments");
export const getAgents = () => request("/api/agents");
export const getTasks = () => request("/api/tasks");
export const createTask = (payload) => request("/api/tasks", { method: "POST", body: payload });
export const getApprovals = () => request("/api/approvals");
export const getNotifications = () => request("/api/notifications");
export const getModels = () => request("/api/models");
export const getIntegrations = () => request("/api/integrations");
export const sendChatMessage = (message, threadId) => request("/api/chat", { method: "POST", body: { message, thread_id: threadId } });

export function streamChat(payload, handlers) {
  const { onThinking, onDelta, onDone, onError } = handlers || {};
  const headers = { "Content-Type": "application/json" };
  if (apiKey) headers["X-API-Key"] = apiKey;
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const responsePromise = DEMO_MODE
    ? demoBackend().then((d) => d.demoStream(payload, apiKey))
    : fetch(API_BASE + "/api/chat/stream", {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        credentials: "include",
      });
  return responsePromise
    .then(async (resp) => {
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new ApiError(data.error || `request failed (${resp.status})`, resp.status);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;
      while (!done) {
        const { value, done: streamDone } = await reader.read();
        done = streamDone;
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const raw = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          const event = (raw.match(/^event: (.+)$/m) || [])[1];
          const dataLine = (raw.match(/^data: (.+)$/m) || [])[1];
          if (!dataLine) continue;
          let parsed;
          try { parsed = JSON.parse(dataLine); } catch { continue; }
          if (event === "thinking") onThinking && onThinking(parsed);
          else if (event === "delta") onDelta && onDelta(parsed);
          else if (event === "done") onDone && onDone(parsed);
          else if (event === "error") onError && onError(parsed);
        }
      }
    });
}
export const listLeaves = () => request("/api/hr/leaves");
export const createLeave = (dateFrom, dateTo, reason) => request("/api/hr/leaves", { method: "POST", body: { date_from: dateFrom, date_to: dateTo, reason } });
export const cancelLeave = (id) => request(`/api/hr/leaves/${id}/cancel`, { method: "POST" });
export const listDocuments = (query = "", accessLevel = "") => { const p = new URLSearchParams(); if (query) p.set("query", query); if (accessLevel) p.set("access_level", accessLevel); const q = p.toString(); return request(`/api/documents${q ? `?${q}` : ""}`); };
export const getDocument = (id) => request(`/api/documents/${id}`);
export const uploadDocument = (payload) => request("/api/documents", { method: "POST", body: payload });
export const deleteDocument = (id) => request(`/api/documents/${id}`, { method: "DELETE" });
export const getDocumentOptions = () => request("/api/documents/options");
export const searchDocuments = (query, topK = 5) => request("/api/documents/search", { method: "POST", body: { query, top_k: topK } });
export const generateArtifact = (payload) => request("/api/artifacts/generate", { method: "POST", body: payload });
export const analyzeFile = (payload) => request("/api/files/analyze", { method: "POST", body: payload });

export const adminListRoles = () => request("/api/admin/roles");
export const adminListUsers = () => request("/api/admin/users");
export const adminListAccessGrants = () => request("/api/admin/access-grants");
export const adminCreateAccessGrant = (payload) => request("/api/admin/access-grants", { method: "POST", body: payload });
export const adminRevokeAccessGrant = (id) => request(`/api/admin/access-grants/${id}/revoke`, { method: "POST" });
export const adminListDocuments = () => request("/api/admin/documents");
export const adminListAgents = () => request("/api/admin/agents");
export const adminGetBranding = () => request("/api/admin/branding");
export const adminUpdateBranding = (payload) => request("/api/admin/branding", { method: "POST", body: payload });
export const adminGetMetrics = () => request("/api/metrics");
export const adminGetLlm = () => request("/api/admin/llm");
export const adminSetLlm = (payload) => request("/api/admin/llm", { method: "POST", body: payload });
export const adminGetControlPlane = () => request("/api/admin/control-plane");
export const getTelegramStatus = () => request("/api/integrations/telegram");
export const generateTelegramCode = () => request("/api/integrations/telegram/code", { method: "POST" });
export const unlinkTelegram = () => request("/api/integrations/telegram/unlink", { method: "POST" });
