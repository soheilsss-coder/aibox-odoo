let csrfToken = "";

function readCsrfCookie() {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/(?:^|; )ai_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function rememberSession(data) {
  if (data && data.csrf_token) csrfToken = data.csrf_token;
  return data;
}

function csrfHeader(method) {
  return method === "GET" || method === "HEAD" || method === "OPTIONS"
    ? {}
    : { "X-CSRF-Token": csrfToken || readCsrfCookie() };
}

export function getApiKey() { return ""; }
export function setApiKey(_key) {}
export function clearApiKey() {}

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function request(path, { method = "GET", body, jsonRpc = false } = {}) {
  const headers = {};
  let fetchBody;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    fetchBody = JSON.stringify(body);
  }
  Object.assign(headers, csrfHeader(method));
  const resp = await fetch(path, { method, headers, body: fetchBody, credentials: "include" });
  const data = rememberSession(await resp.json().catch(() => ({})));
  if (!resp.ok || data.error) throw new ApiError(data.error || `request failed (${resp.status})`, resp.status);
  return data;
}

export const login = (loginId, password) => request("/api/login", { method: "POST", body: { login: loginId, password } });
export const getMe = () => request("/api/me");
export const logout = () => request("/api/logout", { method: "POST" });
export const getMyCapabilities = () => request("/api/me/capabilities");
export const getWorkspace = () => request("/api/workspace");
export const getDepartments = () => request("/api/departments");
export const getAgents = () => request("/api/agents");
export const getCalendar = (start = "", end = "") => { const p = new URLSearchParams(); if (start) p.set("start", start); if (end) p.set("end", end); const q = p.toString(); return request(`/api/calendar${q ? `?${q}` : ""}`); };
export const createCalendarEvent = (payload) => request("/api/calendar", { method: "POST", body: payload });
export const getTasks = () => request("/api/tasks");
export const createTask = (payload) => request("/api/tasks", { method: "POST", body: payload });
export const getApprovals = () => request("/api/approvals");
export const approveApproval = (id) => request(`/api/approvals/${id}/approve`, { method: "POST" });
export const rejectApproval = (id, note = "") => request(`/api/approvals/${id}/reject`, { method: "POST", body: { note } });
export const getNotifications = () => request("/api/notifications");
export const getModels = () => request("/api/models");
export const getIntegrations = () => request("/api/integrations");
export const getBranding = () => request("/api/branding");
export const adminGetSetup = () => request("/api/admin/setup");
export const adminUpdateCompany = (payload) => request("/api/admin/setup/company", { method: "POST", body: payload });
export const adminListConfigurationProfiles = () => request("/api/admin/configuration-profiles");
export const adminCreateConfigurationProfile = (payload) => request("/api/admin/configuration-profiles", { method: "POST", body: payload });
export const adminGetConfigurationProfile = (id) => request(`/api/admin/configuration-profiles/${id}`);
export const adminUpdateConfigurationProfile = (id, payload) => request(`/api/admin/configuration-profiles/${id}`, { method: "PATCH", body: payload });
export const adminCloneConfigurationProfile = (id, name) => request(`/api/admin/configuration-profiles/${id}/clone`, { method: "POST", body: { name } });
export const adminGetConfigurationProfileHistory = (id) => request(`/api/admin/configuration-profiles/${id}/history`);
export const adminValidateConfigurationProfile = (id) => request(`/api/admin/configuration-profiles/${id}/validate`, { method: "POST" });
export const adminCompileConfigurationProfile = (id) => request(`/api/admin/configuration-profiles/${id}/compile`, { method: "POST" });
export const adminActivateConfigurationProfile = (id) => request(`/api/admin/configuration-profiles/${id}/activate`, { method: "POST" });
export const adminArchiveConfigurationProfile = (id) => request(`/api/admin/configuration-profiles/${id}/archive`, { method: "POST" });
export const adminDryRunConfigurationProfile = (id) => request(`/api/admin/configuration-profiles/${id}/dry-run`, { method: "POST" });
export const adminGetSetupChecklist = () => request("/api/admin/setup/checklist");
export const adminRunSetupChecklist = () => request("/api/admin/setup/checklist/run", { method: "POST" });
export const adminListSetupRuns = () => request("/api/admin/setup/runs");
export const adminGetSetupRun = (runKey) => request(`/api/admin/setup/runs/${encodeURIComponent(runKey)}`);
export const sendChatMessage = (message, threadId) => request("/api/chat", { method: "POST", body: { message, thread_id: threadId } });

export function streamChat(payload, handlers) {
  const { onThinking, onDelta, onDone, onError, signal } = handlers || {};
  return fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...csrfHeader("POST") },
    body: JSON.stringify(payload),
    credentials: "include",
    signal,
  })
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
export const reindexDocument = (id) => request(`/api/documents/${id}/reindex`, { method: "POST" });
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
export const adminListModules = () => request("/api/admin/modules");
export const adminInstallModule = (moduleId) => request("/api/admin/modules/install", { method: "POST", body: { module_id: moduleId } });
export const adminGetModuleReadiness = (moduleId) => request(`/api/admin/modules/${moduleId}/readiness`);
export const getModuleNavigation = () => request("/api/modules/navigation");
export const getModuleMenu = (menuId) => request(`/api/modules/menus/${menuId}`);
export const getTelegramStatus = () => request("/api/integrations/telegram");
export const generateTelegramCode = () => request("/api/integrations/telegram/code", { method: "POST" });
export const unlinkTelegram = () => request("/api/integrations/telegram/unlink", { method: "POST" });
