// =============================================================================
// Shared, transport-agnostic mock of the Odoo ai_gateway /api/* surface.
//
// Used by TWO hosts:
//   1. frontend/dev/mock-api.mjs      -> Node http server for `vite dev`
//   2. frontend/src/demo/backend.js   -> in-browser adapter for the static
//      GitHub Pages demo build (VITE_DEMO_MODE=1) where no server exists.
//
// Keep the exported behavior BIT-FOR-BIT identical for both: same routes,
// same JSON shapes, same auth rules, same SSE chat event sequence.
// =============================================================================

// ---------------------------------------------------------------- demo data
// `seed` (browser demo only) rehydrates persisted collections so tab reloads
// keep created tasks/documents/grants; the Node dev server passes nothing.
export function createMockState(seed = null) {
  const state = {
    user: {
      id: 7,
      name: "Sara Mohammadi",
      login: "sara@example.com",
      company: "Nova Demo Inc.",
      capabilities: [
        "admin.console.read",
        "document.admin.manage",
        "chat.use",
        "task.manage",
        "leave.request",
      ],
    },
    departments: [
      { id: 1, name: "Sales", member_count: 8 },
      { id: 2, name: "Human Resources", member_count: 4 },
      { id: 3, name: "Engineering", member_count: 6 },
      { id: 4, name: "Finance", member_count: 5 },
    ],
    agents: [
      { id: 1, name: "HR Assistant", description: "Leave, decrees and employee requests", tools: 6, model: "qwen2.5-14b", provider: "vllm-local", tool_count: 6, active: true },
      { id: 2, name: "Sales Copilot", description: "Lead follow-ups, quotes and sales reports", tools: 9, model: "qwen2.5-14b", provider: "vllm-local", tool_count: 9, active: true },
      { id: 3, name: "Finance Analyst", description: "Expenses, budgets and invoicing", tools: 7, model: "qwen2.5-14b", provider: "vllm-local", tool_count: 7, active: false },
    ],
    tasks: [
      { id: 11, name: "Prepare quote for Aria Industries", state: "open" },
      { id: 12, name: "Review the 2026 leave policy draft", state: "in_progress" },
      { id: 13, name: "Board demo preparation", state: "open" },
    ],
    approvals: [
      { id: 21, name: "Issue employment decree for S. Rezaei", requester: "HR Manager", risk: 45, state: "pending" },
      { id: 22, name: "Delete company-wide document “Pricing”", requester: "Sales Director", risk: 82, state: "pending" },
      { id: 23, name: "Create a new finance user account", requester: "IT Admin", risk: 30, state: "pending" },
    ],
    notifications: [
      { id: 31, subject: "Leave request submitted", body: "Your leave for Sep 23–25 is waiting for your manager's approval.", date: "2026-09-14 09:12:00", is_read: false },
      { id: 32, subject: "New document in your department", body: "“Fall Pricing Guide” was added to Sales documents.", date: "2026-09-13 16:40:00", is_read: false },
      { id: 33, subject: "Approval pending", body: "A high-risk request needs your review.", date: "2026-09-12 11:05:00", is_read: true },
    ],
    leaves: [
      { id: 41, date_from: "2026-09-02", date_to: "2026-09-04", leave_type: "Annual leave", reason: "Family trip", status: "approved" },
      { id: 42, date_from: "2026-09-23", date_to: "2026-09-25", leave_type: "Annual leave", reason: "", status: "pending_approval" },
    ],
    documents: [
      { id: 51, name: "Employee Leave Policy", description: "2026 revised edition, board-approved", access_level: "company", owner: "HR Manager", file_name: "leave-policy.pdf", create_date: "2026-08-20 10:00:00", is_mine: false },
      { id: 52, name: "Fall Pricing Guide", description: "Pricing for the new product line", access_level: "department", department: "Sales", owner: "Sara Mohammadi", file_name: "pricing-fall.xlsx", create_date: "2026-09-10 14:30:00", is_mine: true },
      { id: 53, name: "Investor demo talking points", description: "Personal draft", access_level: "personal", owner: "Sara Mohammadi", file_name: "demo-talk.md", create_date: "2026-09-12 09:15:00", is_mine: true },
      { id: 54, name: "Partnership NDA — confidential", description: "Contracts group members only", access_level: "group", group: "Contracts group", owner: "Legal Counsel", file_name: "nda.docx", create_date: "2026-09-01 12:00:00", is_mine: false },
    ],
    grants: [
      { id: 61, to_user: "Reza Karimi", role: "Sales / Manager", delegated_from: "Sara Mohammadi", expires_on: "2026-09-30", state: "active" },
      { id: 62, to_user: "Mina Ahmadi", role: "HR / Specialist", expires_on: "2026-09-20", state: "active" },
    ],
    roles: [
      { id: 1, name: "Chief Executive", comment: "Full access to every capability", implied_roles: ["base.group_user", "ai.llm_user"], member_count: 2, members: [{ name: "Sara Mohammadi" }, { name: "Ali Madani" }] },
      { id: 2, name: "Sales / Manager", comment: "Manage the sales team and sales docs", implied_roles: ["sales_team.group_sale_manager"], member_count: 3, members: [{ name: "Reza Karimi" }] },
      { id: 3, name: "HR / Specialist", comment: "Leave and decrees at specialist level", implied_roles: ["hr.group_hr_user"], member_count: 4, members: [{ name: "Mina Ahmadi" }] },
    ],
    users: [
      { id: 7, name: "Sara Mohammadi", login: "sara@example.com" },
      { id: 8, name: "Reza Karimi", login: "reza@example.com" },
      { id: 9, name: "Mina Ahmadi", login: "mina@example.com" },
    ],
    branding: { brand_name: "Nova Enterprise", brand_domain: "nova.example.com", company_name: "Nova Demo Inc.", has_logo: true },
    telegram: { available: true, linked: false, linked_date: null, last_message_date: null },
    nextId: 500,
    sessions: new Map(), // sid -> {login}
    apiKeys: new Map(),  // api key -> sid
  };
  if (seed && typeof seed === "object") {
    for (const k of ["departments", "agents", "tasks", "approvals", "notifications", "leaves", "documents", "grants", "roles", "users", "branding", "telegram", "nextId"]) {
      if (seed[k] !== undefined) state[k] = seed[k];
    }
  }
  return state;
}

// ---------------------------------------------------------------- helpers
// Works in both Node (>=19, global crypto) and browsers; falls back to
// Math.random where WebCrypto is unavailable.
function randHex(bytes) {
  const buf = new Uint8Array(bytes);
  if (globalThis.crypto && typeof globalThis.crypto.getRandomValues === "function") {
    globalThis.crypto.getRandomValues(buf);
  } else {
    for (let i = 0; i < buf.length; i += 1) buf[i] = Math.floor(Math.random() * 256);
  }
  return [...buf].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Same lookup order as the real ai_gateway _authenticate(): session id
// first (cookie on the Node host), then X-API-Key / Authorization style
// header keys — the header path keeps login working inside third-party
// iframes where cookies get dropped.
export function authenticate(state, { sid = null, apiKey = "" } = {}) {
  if (sid && state.sessions.get(sid)) return sid;
  const headerSid = apiKey && state.apiKeys.get(String(apiKey).trim());
  return headerSid && state.sessions.get(headerSid) ? headerSid : null;
}

// A small canned "assistant" so the Chat page streams something plausible.
export function cannedReply(message) {
  return (
    "I received your request: “" + String(message || "").slice(0, 80) + "”\n\n" +
    "This answer comes from the built-in demo engine, not the real model. " +
    "In production, this is where Odoo tools — creating tasks, filing leave " +
    "requests, searching documents — run after the backend checks identity, " +
    "role, risk and workflow. For UI work, the streaming behavior, thinking " +
    "state and message bubbles are identical to the real assistant."
  );
}

// SSE chat as a plain list of [event, data] chunks; hosts frame + time them.
export function chatStreamChunks(message, threadId) {
  const words = cannedReply(message).split(" ");
  const chunks = [["thinking", { status: "routing" }]];
  words.forEach((w, i) => chunks.push(["delta", { text: (i === 0 ? "" : " ") + w }]));
  chunks.push(["done", { thread_id: threadId || `mock-${Date.now()}` }]);
  return chunks;
}

function ok(body, extra = {}) { return { status: 200, json: body, ...extra }; }
function err(status, message) { return { status, json: { error: message } }; }

// ---------------------------------------------------------------- router
// Pure request handler. `reqShape` = {
//   method, path,           // e.g. "POST", "/api/documents"
//   query,                  // plain object of search params
//   body,                   // already-parsed JSON body (or {})
//   auth: { sid, apiKey },  // mapped by the host
// }
// Returns { status, json, setSid? } — the host is responsible for turning
// that into bytes/headers (and a Set-Cookie when setSid/sidCleared is set).
export function handleApi(state, { method, path, query = {}, body = {}, auth = {} }) {
  const { user } = state;
  // --- auth ---
  if (path === "/api/login" && method === "POST") {
    if (!body.login || !body.password) return err(400, "Email and password are both required.");
    const sid = randHex(24);
    const apiKey = randHex(20);
    state.sessions.set(sid, { login: body.login });
    state.apiKeys.set(apiKey, sid);
    return {
      status: 200,
      json: { user: { ...user, login: body.login }, api_key: apiKey, expires_at: null },
      setSid: sid,
    };
  }

  const sid = authenticate(state, auth);
  if (!sid) return err(401, "Your session is not valid. Please sign in.");

  // --- me / session ---
  if (path === "/api/me" && method === "GET") return ok(user);
  if (path === "/api/logout" && method === "POST") {
    state.sessions.delete(sid);
    for (const [k, v] of state.apiKeys) if (v === sid) state.apiKeys.delete(k);
    return { status: 200, json: { ok: true }, clearSid: true };
  }
  if (path === "/api/me/capabilities" && method === "GET") return ok({ capabilities: user.capabilities });
  if (path === "/api/workspace" && method === "GET") return ok({ department: { id: 1, name: "Sales" }, user: user.name });

  // --- org / agents / tasks / approvals / notifications ---
  if (path === "/api/departments" && method === "GET") return ok({ departments: state.departments });
  if (path === "/api/agents" && method === "GET") return ok({ agents: state.agents });
  if (path === "/api/tasks") {
    if (method === "GET") return ok({ tasks: state.tasks });
    if (method === "POST") {
      const t = { id: state.nextId++, name: body.name || "Untitled task", state: "open" };
      state.tasks.unshift(t);
      return ok({ task: t });
    }
  }
  if (path === "/api/approvals" && method === "GET") return ok({ approvals: state.approvals });
  if (path === "/api/notifications" && method === "GET") return ok({ notifications: state.notifications });
  if (path === "/api/models" && method === "GET") return ok({ models: [{ name: "qwen2.5-14b-instruct", provider: "vllm-local", active: true }] });
  if (path === "/api/integrations" && method === "GET") return ok({ integrations: [{ key: "telegram", name: "Telegram", status: state.telegram.linked ? "connected" : "available" }] });

  // --- chat (non-streamed sibling; streaming lives in chatStreamChunks) ---
  if (path === "/api/chat" && method === "POST") return ok({ reply: cannedReply(body.message), thread_id: body.thread_id || `mock-${Date.now()}` });

  // --- hr leaves ---
  if (path === "/api/hr/leaves") {
    if (method === "GET") return ok({ leaves: state.leaves });
    if (method === "POST") {
      if (!body.date_from || !body.date_to) return err(400, "A date range is required.");
      const l = { id: state.nextId++, date_from: body.date_from, date_to: body.date_to, leave_type: "Annual leave", reason: body.reason || "", status: "pending_approval" };
      state.leaves.unshift(l);
      return ok({ leave: l });
    }
  }
  let m = path.match(/^\/api\/hr\/leaves\/(\d+)\/cancel$/);
  if (m && method === "POST") {
    const l = state.leaves.find((x) => x.id === Number(m[1]));
    if (l) l.status = "cancelled";
    return ok({ ok: true });
  }

  // --- documents ---
  if (path === "/api/documents" && method === "GET") {
    const level = query.access_level || "";
    const q = String(query.query || "").toLowerCase();
    let out = state.documents;
    if (level) out = out.filter((d) => d.access_level === level);
    if (q) out = out.filter((d) => (d.name + " " + (d.description || "")).toLowerCase().includes(q));
    return ok({ documents: out });
  }
  if (path === "/api/documents" && method === "POST") {
    const dept = state.departments.find((d) => d.id === Number(body.department_id));
    const doc = {
      id: state.nextId++,
      name: body.name || "Untitled document",
      description: body.description || "",
      access_level: body.access_level || "personal",
      department: dept ? dept.name : undefined,
      group: body.group_id ? "Contracts group" : undefined,
      owner: user.name,
      file_name: body.file_name || "",
      create_date: new Date().toISOString().slice(0, 19).replace("T", " "),
      is_mine: true,
    };
    state.documents.unshift(doc);
    return ok({ document: doc });
  }
  m = path.match(/^\/api\/documents\/(\d+)$/);
  if (m && method === "GET") {
    const d = state.documents.find((x) => x.id === Number(m[1]));
    return d ? ok({ document: d }) : err(404, "Document not found.");
  }
  if (m && method === "DELETE") {
    state.documents = state.documents.filter((x) => x.id !== Number(m[1]));
    return ok({ ok: true });
  }
  if (path === "/api/documents/options" && method === "GET") {
    return ok({ departments: state.departments.map((d) => ({ id: d.id, name: d.name })), groups: [{ id: 5, name: "Contracts group" }], own_department_id: 1 });
  }
  if (path === "/api/documents/search" && method === "POST") {
    const q = String(body.query || "");
    const hits = state.documents.filter((d) => q && (d.name + " " + (d.description || "")).includes(q.trim())).slice(0, body.top_k || 5);
    const results = (hits.length ? hits : state.documents.slice(0, 2)).map((d, i) => ({
      document_id: d.id,
      document_name: d.name,
      similarity: (0.92 - i * 0.07).toFixed(2),
      excerpt: `${d.description || d.name} — a sample excerpt from the document for semantic-search UI testing.`,
    }));
    return ok({ results });
  }

  // --- files / artifacts (Chat page attachments) ---
  if (path === "/api/files/analyze" && method === "POST") {
    return ok({ analysis: `Simulated analysis of “${body.filename || "file"}”: a text document with general information; key takeaway: this is demo data from the mock server.` });
  }
  if (path === "/api/artifacts/generate" && method === "POST") return ok({ artifact: { id: state.nextId++, url: "#", name: "artifact" } });

  // --- admin console ---
  if (path === "/api/admin/roles" && method === "GET") return ok({ roles: state.roles });
  if (path === "/api/admin/users" && method === "GET") return ok({ users: state.users });
  if (path === "/api/admin/access-grants") {
    if (method === "GET") return ok({ grants: state.grants });
    if (method === "POST") {
      const u = state.users.find((x) => x.id === Number(body.to_user_id));
      const g = {
        id: state.nextId++,
        to_user: u ? u.name : "User",
        role: state.roles[Number(body.group_id) % state.roles.length]?.name || "Base role",
        expires_on: body.expires_on || "—",
        state: "active",
      };
      state.grants.unshift(g);
      return ok({ grant: g });
    }
  }
  m = path.match(/^\/api\/admin\/access-grants\/(\d+)\/revoke$/);
  if (m && method === "POST") {
    const g = state.grants.find((x) => x.id === Number(m[1]));
    if (g) g.state = "revoked";
    return ok({ ok: true });
  }
  if (path === "/api/admin/documents" && method === "GET") return ok({ documents: state.documents });
  if (path === "/api/admin/agents" && method === "GET") {
    return ok({
      agents: state.agents,
      tools: [
        { name: "create_leave_request", risk_level: 40, requires_approval_from: "manager", description: "File a leave request for yourself" },
        { name: "generate_hr_decree", risk_level: 80, requires_approval_from: "hr_manager", description: "Issue an HR decree on someone else's behalf" },
        { name: "search_documents", risk_level: 10, requires_approval_from: null, description: "Semantic search over documents you can access" },
      ],
    });
  }
  if (path === "/api/admin/branding") {
    if (method === "GET") return ok(state.branding);
    if (method === "POST") {
      state.branding = { ...state.branding, ...body };
      return ok(state.branding);
    }
  }
  if (path === "/api/metrics" && method === "GET") {
    return ok({
      requests_last_hour: 34,
      requests_last_24h: 412,
      errors_last_24h: 3,
      error_rate_24h: 0.007,
      avg_duration_ms_24h: 186,
      top_actions_24h: [
        { action: "chat.stream", calls: 121 },
        { action: "documents.search", calls: 64 },
        { action: "tasks.create", calls: 22 },
        { action: "leaves.create", calls: 9 },
      ],
    });
  }
  if (path === "/api/admin/control-plane" && method === "GET") {
    return ok({
      users: 12,
      departments: 4,
      positions: 9,
      designers: 1,
      access_reviews: 2,
      scim_active_tokens: 0,
      sections: ["identity", "access", "documents", "agents", "observability"],
      sso: [{ name: "—", protocol: "—", active: false }],
      configuration_profiles: [{ name: "baseline", state: "applied", version: "v57" }],
    });
  }

  // --- telegram integration ---
  if (path === "/api/integrations/telegram" && method === "GET") return ok(state.telegram);
  if (path === "/api/integrations/telegram/code" && method === "POST") {
    return ok({ code: randHex(4).toUpperCase(), bot_username: "nova_assistant_bot", expires_in_minutes: 10 });
  }
  if (path === "/api/integrations/telegram/unlink" && method === "POST") {
    state.telegram = { ...state.telegram, linked: false, linked_date: null, last_message_date: null };
    return ok({ ok: true });
  }

  return err(404, `mock: unknown route ${method} ${path}`);
}
