// =============================================================================
// DEV-ONLY Node host for the shared mock router (frontend/src/demo/mock-core.mjs).
// Serves the Odoo ai_gateway /api/* surface for `vite dev`:
//
//   node frontend/dev/mock-api.mjs        (listens on 127.0.0.1:8069)
//
// Same routes/shapes/auth as the in-browser demo backend (src/demo/backend.js)
// used by the static GitHub Pages build. NOTHING here is production code.
// =============================================================================
import http from "node:http";
import { createMockState, handleApi, chatStreamChunks, authenticate } from "../src/demo/mock-core.mjs";

const PORT = Number(process.env.MOCK_API_PORT || 8069);
const state = createMockState();

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

function sessionSid(req) {
  const cookie = req.headers.cookie || "";
  const sid = (cookie.match(/(?:^|;\s*)mock_sid=([a-f0-9]+)/) || [])[1];
  let key = (req.headers["x-api-key"] || "").trim();
  if (!key) {
    const auth = req.headers["authorization"] || "";
    if (auth.startsWith("Bearer ")) key = auth.slice(7).trim();
  }
  return authenticate(state, { sid, apiKey: key });
}

function streamChat(req, res, body) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
  });
  const chunks = chatStreamChunks(body.message, body.thread_id);
  let i = 0;
  const timer = setInterval(() => {
    if (res.writableEnded) { clearInterval(timer); return; }
    if (i < chunks.length) {
      const [event, data] = chunks[i];
      res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
      i += 1;
    } else {
      clearInterval(timer);
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

  const body = method === "GET" || method === "DELETE" ? {} : await readBody(req);
  const query = {};
  url.searchParams.forEach((v, k) => { query[k] = v; });

  if (path === "/api/chat/stream" && method === "POST") {
    if (!sessionSid(req)) return json(res, 401, { error: "Your session is not valid. Please sign in." });
    return streamChat(req, res, body);
  }

  const out = handleApi(state, {
    method,
    path,
    query,
    body,
    auth: {
      sid: (req.headers.cookie || "").match(/(?:^|;\s*)mock_sid=([a-f0-9]+)/)?.[1] || null,
      apiKey: (req.headers["x-api-key"] || ((req.headers["authorization"] || "").startsWith("Bearer ")
        ? (req.headers["authorization"] || "").slice(7).trim() : "")) || "",
    },
  });

  const headers = {};
  if (out.setSid) headers["Set-Cookie"] = `mock_sid=${out.setSid}; Path=/; HttpOnly; Secure; SameSite=None`;
  if (out.clearSid) headers["Set-Cookie"] = "mock_sid=; Path=/; Secure; SameSite=None; Max-Age=0";
  json(res, out.status, out.json, headers);
}

http.createServer((req, res) => {
  handle(req, res).catch((err) => {
    console.error(err);
    if (!res.headersSent) json(res, 500, { error: "mock: internal error" });
  });
}).listen(PORT, "127.0.0.1", () => {
  console.log(`[mock-api] Odoo ai_gateway mock listening on http://127.0.0.1:${PORT}  (any email/password works)`);
});
