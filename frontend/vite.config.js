import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_API_BASE points at the Odoo box's /api/* gateway (roadmap #43-44).
// Defaults to same-origin ('' -> relative /api/...) which is right when
// this frontend is served behind the same reverse proxy as Odoo; set it
// explicitly if the frontend is deployed separately (e.g. Vercel/Netlify
// pointing at a different domain for the Odoo box).
export default defineConfig({
  base: process.env.PAGES_BASE || "/",
  plugins: [react()],
  server: {
    // 0.0.0.0 + open host allowlist: required for remote/preview access
    // (SSH tunnels, sandbox previews, LAN demos). Dev-only setting - the
    // production build is static files served by nginx, see
    // 17_setup_frontend.sh.
    host: true,
    allowedHosts: true,
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8069",
        changeOrigin: true,
      },
    },
  },
});
