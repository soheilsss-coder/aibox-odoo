import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_API_BASE points at the Odoo box's /api/* gateway (roadmap #43-44).
// Defaults to same-origin ('' -> relative /api/...) which is right when
// this frontend is served behind the same reverse proxy as Odoo; set it
// explicitly if the frontend is deployed separately (e.g. Vercel/Netlify
// pointing at a different domain for the Odoo box).
export default defineConfig({
  plugins: [react()],
  // The built bundle is deployed BOTH as the review preview (served under
  // /aibox-odoo/) and as GitHub Pages (https://<owner>.github.io/aibox-odoo/).
  base: "/aibox-odoo/",
  server: {
    port: 5173,
    // The appliance is reached through proxy hosts that change per sandbox /
    // tunnel (e.g. <port>-<id>.e2b.app). This is a demo/dev server, not a
    // public production host - allow any Host header it receives.
    allowedHosts: true,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8069",
        changeOrigin: true,
      },
    },
  },
});
