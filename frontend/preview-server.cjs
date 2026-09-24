#!/usr/bin/env node
// Preview server: serves the built "Nova Enterprise" frontend bundle (the
// exact build that runs on GitHub Pages) and proxies /api/* to the real
// Odoo appliance, so the newest design runs against the REAL backend
// (real login, real cookies/CSRF, real SSE streaming, real tool calls).
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "docs");
const PORT = process.env.PREVIEW_PORT || 5173;
const BACKEND = process.env.PREVIEW_API_TARGET || "http://127.0.0.1:18069";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".map": "application/json",
};

function serveStatic(req, res) {
  let urlPath = decodeURIComponent(req.url.split("?")[0]);
  // The bundle is built with the GitHub Pages project base (/aibox-odoo/),
  // so the preview reproduces that exact URL structure.
  if (urlPath === "/" || urlPath === "/aibox-odoo") {
    res.writeHead(302, { Location: "/aibox-odoo/" });
    return res.end();
  }
  if (urlPath.startsWith("/aibox-odoo/")) urlPath = urlPath.slice("/aibox-odoo".length);
  if (urlPath === "/" || urlPath === "") urlPath = "/index.html";
  let filePath = path.normalize(path.join(ROOT, urlPath));
  if (!filePath.startsWith(ROOT)) { res.writeHead(403); return res.end("forbidden"); }
  fs.stat(filePath, (err, st) => {
    if (err || !st.isFile()) {
      // SPA fallback: any unknown extension-less path renders the app shell.
      if (!path.extname(urlPath)) {
        return fs.createReadStream(path.join(ROOT, "index.html"))
          .on("error", () => { res.writeHead(404); res.end("not found"); })
          .pipe(res.statusCode = 200, res);
      }
      res.writeHead(404); return res.end("not found");
    }
    res.writeHead(200, { "Content-Type": MIME[path.extname(filePath)] || "application/octet-stream" });
    fs.createReadStream(filePath).pipe(res);
  });
}

function proxyApi(req, res) {
  const target = new URL(BACKEND + req.url);
  const opts = {
    protocol: target.protocol,
    hostname: target.hostname,
    port: target.port || 80,
    path: target.pathname + target.search,
    method: req.method,
    headers: { ...req.headers, host: target.host },
  };
  const upstream = http.request(opts, (up) => {
    res.writeHead(up.statusCode || 502, up.headers);
    up.pipe(res); // streams SSE as-is
  });
  upstream.on("error", (e) => {
    if (!res.headersSent) res.writeHead(502, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "backend unreachable: " + e.message }));
  });
  req.pipe(upstream);
}

const server = http.createServer((req, res) => {
  if (req.url === "/api" || req.url.startsWith("/api/")) return proxyApi(req, res);
  return serveStatic(req, res);
});
server.listen(PORT, "0.0.0.0", () => console.log(`preview: bundle on :${PORT}, /api -> ${BACKEND}`));
