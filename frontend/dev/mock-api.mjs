// =============================================================================
// DEV-ONLY mock of the Odoo ai_gateway /api/* surface (frontend/src/api/client.js)
//
// Lets the React UI run COMPLETELY standalone for UI/UX work — every screen,
// including login, SSE chat streaming, documents, approvals and the admin
// console — without an Odoo server, PostgreSQL or a local LLM.
//
//   node frontend/dev/mock-api.mjs        (listens on 127.0.0.1:8069)
//
// It returns plausible Persian demo data with an in-memory session cookie.
// NOTHING here is production code: do not ship, do not expose.
// =============================================================================
import http from "node:http";
import crypto from "node:crypto";

const PORT = Number(process.env.MOCK_API_PORT || 8069);

// ---------------------------------------------------------------- demo data
const USER = {
  id: 7,
  name: "سارا محمدی",
  login: "sara@example.com",
  company: "شرکت دموی نوین",
  capabilities: [
    "admin.console.read",
    "document.admin.manage",
    "chat.use",
    "task.manage",
    "leave.request",
  ],
};

const CAPABILITIES = USER.capabilities;

let departments = [
  { id: 1, name: "فروش", member_count: 8 },
  { id: 2, name: "منابع انسانی", member_count: 4 },
  { id: 3, name: "فناوری اطلاعات", member_count: 6 },
  { id: 4, name: "مالی", member_count: 5 },
];

let agents = [
  { id: 1, name: "دستیار منابع انسانی", description: "مرخصی، احکام و درخواست‌های کارکنان", tools: 6, model: "qwen2.5-14b", provider: "vllm-local", tool_count: 6, active: true },
  { id: 2, name: "دستیار فروش", description: "پیگیری لیدها، پیش‌فاکتور و گزارش فروش", tools: 9, model: "qwen2.5-14b", provider: "vllm-local", tool_count: 9, active: true },
  { id: 3, name: "دستیار مالی", description: "هزینه‌ها، بودجه و صورتحساب‌ها", tools: 7, model: "qwen2.5-14b", provider: "vllm-local", tool_count: 7, active: false },
];

let tasks = [
  { id: 11, name: "تهیه پیش‌فاکتور مشتری آریا", state: "open" },
  { id: 12, name: "بازبینی سیاست مرخصی ۱۴۰۵", state: "in_progress" },
  { id: 13, name: "دمو برای هیئت‌مدیره", state: "open" },
];

let approvals = [
  { id: 21, name: "صدور حکم کارمندی برای س. رضایی", requester: "مدیر منابع انسانی", risk: 45, state: "pending" },
  { id: 22, name: "حذف سند سطح سازمان «قیمت‌گذاری»", requester: "مدیر فروش", risk: 82, state: "pending" },
  { id: 23, name: "ایجاد کاربر جدید در دپارتمان مالی", requester: "مدیر سیستم", risk: 30, state: "pending" },
];

let notifications = [
  { id: 31, subject: "درخواست مرخصی شما ثبت شد", body: "مرخصی ۲ تا ۴ مهر در انتظار تایید مدیر است.", date: "2026-09-14 09:12:00", is_read: false },
  { id: 32, subject: "سند جدید در دپارتمان شما", body: "«راهنمای قیمت‌گذاری پاییز» به اسناد فروش اضافه شد.", date: "2026-09-13 16:40:00", is_read: false },
  { id: 33, subject: "تایید در انتظار", body: "یک درخواست پرریسک نیازمند تایید شماست.", date: "2026-09-12 11:05:00", is_read: true },
];

let leaves = [
  { id: 41, date_from: "2026-09-02", date_to: "2026-09-04", leave_type: "مرخصی استحقاقی", reason: "سفر خانوادگی", status: "approved" },
  { id: 42, date_from: "2026-09-23", date_to: "2026-09-25", leave_type: "مرخصی استحقاقی", reason: "", status: "pending_approval" },
];

let documents = [
  { id: 51, name: "آیین‌نامه مرخصی کارکنان", description: "نسخه به‌روز ۱۴۰۵ مصوب هیئت‌مدیره", access_level: "company", owner: "مدیر منابع انسانی", file_name: "leave-policy.pdf", create_date: "2026-08-20 10:00:00", is_mine: false },
  { id: 52, name: "راهنمای قیمت‌گذاری پاییز", description: "قیمت‌گذاری محصولات سری جدید", access_level: "department", department: "فروش", owner: "سارا محمدی", file_name: "pricing-fall.xlsx", create_date: "2026-09-10 14:30:00", is_mine: true },
  { id: 53, name: "متن صحبت دمو برای سرمایه‌گذار", description: "پیش‌نویس شخصی", access_level: "personal", owner: "سارا محمدی", file_name: "demo-talk.md", create_date: "2026-09-12 09:15:00", is_mine: true },
  { id: 54, name: "قرارداد همکاری — محرمانه", description: "فقط اعضای گروه قراردادها", access_level: "group", group: "گروه قراردادها", owner: "مدیر حقوقی", file_name: "nda.docx", create_date: "2026-09-01 12:00:00", is_mine: false },
];

let grants = [
  { id: 61, to_user: "رضا کریمی", role: "فروش / مدیر", delegated_from: "سارا محمدی", expires_on: "2026-09-30", state: "active" },
  { id: 62, to_user: "مینا احمدی", role: "منابع انسانی / کارشناس", expires_on: "2026-09-20", state: "active" },
];

let roles = [
  { name: "مدیر کل", comment: "دسترسی کامل به همه قابلیت‌ها", implied_roles: ["base.group_user", "ai.llm_user"], member_count: 2, members: [{ name: "سارا محمدی" }, { name: "علی مدنی" }] },
  { name: "فروش / مدیر", comment: "مدیریت تیم فروش و اسناد فروش", implied_roles: ["sales_team.group_sale_manager"], member_count: 3, members: [{ name: "رضا کریمی" }] },
  { name: "منابع انسانی / کارشناس", comment: "مرخصی و احکام در سطح کارشناس", implied_roles: ["hr.group_hr_user"], member_count: 4, members: [{ name: "مینا احمدی" }] },
];

let users = [
  { id: 7, name: "سارا محمدی", login: "sara@example.com" },
  { id: 8, name: "رضا کریمی", login: "reza@example.com" },
  { id: 9, name: "مینا احمدی", login: "mina@example.com" },
];

let branding = { brand_name: "Nova Enterprise", brand_domain: "nova.example.com", company_name: "شرکت دموی نوین", has_logo: true };

let telegram = { available: true, linked: false, linked_date: null, last_message_date: null };

let nextId = 500;
const sessions = new Map(); // sid -> {login}
const apiKeys = new Map();  // api key -> sid  (header-auth fallback for iframe previews)

// ---------------------------------------------------------------- helpers
function json(res, code, body, extraHeaders = {}) {
  const raw = JSON.stringify(body);
  res.writeHead(code, { "Content-Type": "application/json; charset=utf-8", "Content-Length": Buffer.byteLength(raw), ...extraHeaders });
  res.end(raw);
}

function readBody(req) {
  return new Promise((resolve) => {
    let data = "";
    req.on("data", (c) => { data += c; if (data.length > 50 * 1024 * 1024) req.destroy(); });
    req.on("end", () => { try { resolve(data ? JSON.parse(data) : {}); } catch { resolve({}); } });
  });
}

// Same lookup order as the real ai_gateway _authenticate(): ai_session
// cookie first, then X-API-Key / Authorization headers - the header path
// is what keeps login working when this UI runs in a third-party iframe
// (arena/sandbox previews) where browsers drop first-party-looking
// cookies regardless of SameSite=None.
function sessionOf(req) {
  const cookie = req.headers.cookie || "";
  const sid = (cookie.match(/(?:^|;\s*)mock_sid=([a-f0-9]+)/) || [])[1];
  if (sid && sessions.get(sid)) return sid;
  let key = (req.headers["x-api-key"] || "").trim();
  if (!key) {
    const auth = req.headers["authorization"] || "";
    if (auth.startsWith("Bearer ")) key = auth.slice(7).trim();
  }
  const headerSid = key && apiKeys.get(key);
  return headerSid && sessions.get(headerSid) ? headerSid : null;
}

// A small canned "assistant" so the Chat page streams something plausible.
function cannedReply(message) {
  return (
    "درخواست شما را دریافت کردم: «" + String(message || "").slice(0, 80) + "»\n\n" +
    "این پاسخ از سرویس شبیه‌ساز (mock) توسعه می‌آید، نه مدل واقعی. " +
    "در محیط واقعی، همین‌جا ابزارهای Odoo — مانند ایجاد تسک، ثبت مرخصی یا جستجوی اسناد — " +
    "پس از بررسی هویت، نقش، ریسک و workflow اجرا می‌شوند. " +
    "برای تست رابط کاربر، حالت streaming، نمایش «در حال فکر کردن» و بابل‌های پیام دقیقاً با نسخه‌ی واقعی یکسان است."
  );
}

function streamChat(req, res, body) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
  });
  const send = (event, data) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  const threadId = body.thread_id || `mock-${Date.now()}`;
  const words = cannedReply(body.message).split(" ");
  send("thinking", { status: "routing" });
  let i = 0;
  const timer = setInterval(() => {
    if (res.writableEnded) { clearInterval(timer); return; }
    if (i < words.length) {
      send("delta", { text: (i === 0 ? "" : " ") + words[i] });
      i += 1;
    } else {
      clearInterval(timer);
      send("done", { thread_id: threadId });
      res.end();
    }
  }, 40);
  req.on("close", () => clearInterval(timer));
}

// ---------------------------------------------------------------- router
async function handle(req, res) {
  const url = new URL(req.url, "http://x");
  const path = url.pathname;
  const method = req.method;

  if (method === "OPTIONS") { res.writeHead(204); res.end(); return; }

  // --- auth ---
  if (path === "/api/login" && method === "POST") {
    const body = await readBody(req);
    if (!body.login || !body.password) return json(res, 400, { error: "ایمیل و رمز عبور لازم است." });
    const sid = crypto.randomBytes(24).toString("hex");
    const apiKey = crypto.randomBytes(20).toString("hex");
    sessions.set(sid, { login: body.login });
    apiKeys.set(apiKey, sid);
    return json(res, 200, { user: { ...USER, login: body.login }, api_key: apiKey, expires_at: null }, {
      "Set-Cookie": `mock_sid=${sid}; Path=/; HttpOnly; Secure; SameSite=None`,
    });
  }

  const sid = sessionOf(req);
  if (!sid) return json(res, 401, { error: "نشست معتبر نیست؛ لطفاً وارد شوید." });

  // --- me / session ---
  if (path === "/api/me" && method === "GET") return json(res, 200, USER);
  if (path === "/api/logout" && method === "POST") {
    sessions.delete(sid);
    for (const [k, v] of apiKeys) if (v === sid) apiKeys.delete(k);
    return json(res, 200, { ok: true }, { "Set-Cookie": "mock_sid=; Path=/; Secure; SameSite=None; Max-Age=0" });
  }
  if (path === "/api/me/capabilities" && method === "GET") return json(res, 200, { capabilities: CAPABILITIES });
  if (path === "/api/workspace" && method === "GET") return json(res, 200, { department: { id: 1, name: "فروش" }, user: USER.name });

  // --- org / agents / tasks / approvals / notifications ---
  if (path === "/api/departments" && method === "GET") return json(res, 200, { departments });
  if (path === "/api/agents" && method === "GET") return json(res, 200, { agents });
  if (path === "/api/tasks") {
    if (method === "GET") return json(res, 200, { tasks });
    if (method === "POST") { const b = await readBody(req); const t = { id: nextId++, name: b.name || "تسک بدون نام", state: "open" }; tasks.unshift(t); return json(res, 200, { task: t }); }
  }
  if (path === "/api/approvals" && method === "GET") return json(res, 200, { approvals });
  if (path === "/api/notifications" && method === "GET") return json(res, 200, { notifications });
  if (path === "/api/models" && method === "GET") return json(res, 200, { models: [{ name: "qwen2.5-14b-instruct", provider: "vllm-local", active: true }] });
  if (path === "/api/integrations" && method === "GET") return json(res, 200, { integrations: [{ key: "telegram", name: "Telegram", status: telegram.linked ? "connected" : "available" }] });

  // --- chat ---
  if (path === "/api/chat" && method === "POST") { const b = await readBody(req); return json(res, 200, { reply: cannedReply(b.message), thread_id: b.thread_id || `mock-${Date.now()}` }); }
  if (path === "/api/chat/stream" && method === "POST") { const b = await readBody(req); return streamChat(req, res, b); }

  // --- hr leaves ---
  if (path === "/api/hr/leaves") {
    if (method === "GET") return json(res, 200, { leaves });
    if (method === "POST") {
      const b = await readBody(req);
      if (!b.date_from || !b.date_to) return json(res, 400, { error: "بازه‌ی تاریخ لازم است." });
      const l = { id: nextId++, date_from: b.date_from, date_to: b.date_to, leave_type: "مرخصی استحقاقی", reason: b.reason || "", status: "pending_approval" };
      leaves.unshift(l);
      return json(res, 200, { leave: l });
    }
  }
  let m = path.match(/^\/api\/hr\/leaves\/(\d+)\/cancel$/);
  if (m && method === "POST") { const l = leaves.find((x) => x.id === Number(m[1])); if (l) l.status = "cancelled"; return json(res, 200, { ok: true }); }

  // --- documents ---
  if (path === "/api/documents" && method === "GET") {
    const level = url.searchParams.get("access_level") || "";
    const q = (url.searchParams.get("query") || "").toLowerCase();
    let out = documents;
    if (level) out = out.filter((d) => d.access_level === level);
    if (q) out = out.filter((d) => (d.name + " " + (d.description || "")).toLowerCase().includes(q));
    return json(res, 200, { documents: out });
  }
  if (path === "/api/documents" && method === "POST") {
    const b = await readBody(req);
    const dept = departments.find((d) => d.id === Number(b.department_id));
    const doc = { id: nextId++, name: b.name || "سند بدون نام", description: b.description || "", access_level: b.access_level || "personal", department: dept ? dept.name : undefined, group: b.group_id ? "گروه قراردادها" : undefined, owner: USER.name, file_name: b.file_name || "", create_date: new Date().toISOString().slice(0, 19).replace("T", " "), is_mine: true };
    documents.unshift(doc);
    return json(res, 200, { document: doc });
  }
  m = path.match(/^\/api\/documents\/(\d+)$/);
  if (m && method === "GET") { const d = documents.find((x) => x.id === Number(m[1])); return d ? json(res, 200, { document: d }) : json(res, 404, { error: "سند یافت نشد." }); }
  if (m && method === "DELETE") { documents = documents.filter((x) => x.id !== Number(m[1])); return json(res, 200, { ok: true }); }
  if (path === "/api/documents/options" && method === "GET") return json(res, 200, { departments: departments.map((d) => ({ id: d.id, name: d.name })), groups: [{ id: 5, name: "گروه قراردادها" }], own_department_id: 1 });
  if (path === "/api/documents/search" && method === "POST") {
    const b = await readBody(req);
    const q = String(b.query || "");
    const hits = documents.filter((d) => q && (d.name + " " + (d.description || "")).includes(q.trim())).slice(0, b.top_k || 5);
    const results = (hits.length ? hits : documents.slice(0, 2)).map((d, i) => ({ document_id: d.id, document_name: d.name, similarity: (0.92 - i * 0.07).toFixed(2), excerpt: `${d.description || d.name} — این متن نمونه‌ی برش ‌خورده از سند برای تست رابط کاربری است.` }));
    return json(res, 200, { results });
  }

  // --- files / artifacts (Chat page attachments) ---
  if (path === "/api/files/analyze" && method === "POST") { const b = await readBody(req); return json(res, 200, { analysis: `تحلیل شبیه‌سازی‌شده‌ی فایل «${b.filename || "file"}»: یک سند متنی حاوی اطلاعات کلی است؛ نکته‌ی اصلی: داده‌ی واقعی نیست.` }); }
  if (path === "/api/artifacts/generate" && method === "POST") return json(res, 200, { artifact: { id: nextId++, url: "#", name: "artifact" } });

  // --- admin console ---
  if (path === "/api/admin/roles" && method === "GET") return json(res, 200, { roles });
  if (path === "/api/admin/users" && method === "GET") return json(res, 200, { users });
  if (path === "/api/admin/access-grants" && method === "GET") return json(res, 200, { grants });
  if (path === "/api/admin/access-grants" && method === "POST") {
    const b = await readBody(req);
    const u = users.find((x) => x.id === Number(b.to_user_id));
    const g = { id: nextId++, to_user: u ? u.name : "کاربر", role: roles[Number(b.group_id) % roles.length]?.name || "نقش پایه", expires_on: b.expires_on || "—", state: "active" };
    grants.unshift(g);
    return json(res, 200, { grant: g });
  }
  m = path.match(/^\/api\/admin\/access-grants\/(\d+)\/revoke$/);
  if (m && method === "POST") { const g = grants.find((x) => x.id === Number(m[1])); if (g) g.state = "revoked"; return json(res, 200, { ok: true }); }
  if (path === "/api/admin/documents" && method === "GET") return json(res, 200, { documents });
  if (path === "/api/admin/agents" && method === "GET") return json(res, 200, { agents, tools: [
    { name: "create_leave_request", risk_level: 40, requires_approval_from: "manager", description: "ثبت درخواست مرخصی برای خود کاربر" },
    { name: "generate_hr_decree", risk_level: 80, requires_approval_from: "hr_manager", description: "صدور حکم کارمندی برای دیگری" },
    { name: "search_documents", risk_level: 10, requires_approval_from: null, description: "جستجوی معنایی در اسناد مجاز" },
  ] });
  if (path === "/api/admin/branding") {
    if (method === "GET") return json(res, 200, branding);
    if (method === "POST") { const b = await readBody(req); branding = { ...branding, ...b }; return json(res, 200, branding); }
  }
  if (path === "/api/metrics" && method === "GET") return json(res, 200, {
    requests_last_hour: 34, requests_last_24h: 412, errors_last_24h: 3,
    error_rate_24h: 0.007, avg_duration_ms_24h: 186,
    top_actions_24h: [{ action: "chat.stream", calls: 121 }, { action: "documents.search", calls: 64 }, { action: "tasks.create", calls: 22 }, { action: "leaves.create", calls: 9 }],
  });
  if (path === "/api/admin/control-plane" && method === "GET") return json(res, 200, {
    users: 12, departments: 4, positions: 9, designers: 1, access_reviews: 2, scim_active_tokens: 0,
    sections: ["identity", "access", "documents", "agents", "observability"],
    sso: [{ name: "—", protocol: "—", active: false }],
    configuration_profiles: [{ name: "baseline", state: "applied", version: "v57" }],
  });

  // --- telegram integration ---
  if (path === "/api/integrations/telegram" && method === "GET") return json(res, 200, telegram);
  if (path === "/api/integrations/telegram/code" && method === "POST") return json(res, 200, { code: crypto.randomBytes(4).toString("hex").toUpperCase(), bot_username: "nova_assistant_bot", expires_in_minutes: 10 });
  if (path === "/api/integrations/telegram/unlink" && method === "POST") { telegram = { ...telegram, linked: false, linked_date: null, last_message_date: null }; return json(res, 200, { ok: true }); }

  json(res, 404, { error: `mock: مسیر ناشناخته ${method} ${path}` });
}

http.createServer((req, res) => {
  handle(req, res).catch((err) => {
    console.error(err);
    if (!res.headersSent) json(res, 500, { error: "mock: خطای داخلی" });
  });
}).listen(PORT, "127.0.0.1", () => {
  console.log(`[mock-api] Odoo ai_gateway mock listening on http://127.0.0.1:${PORT}  (login: هر ایمیل/رمزی)`);
});
