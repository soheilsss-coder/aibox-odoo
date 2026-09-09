import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_API_BASE points at the Odoo box's /api/* gateway (roadmap #43-44).
// Defaults to same-origin ('' -> relative /api/...) which is right when
// this frontend is served behind the same reverse proxy as Odoo; set it
// explicitly if the frontend is deployed separately (e.g. Vercel/Netlify
// pointing at a different domain for the Odoo box).
export default defineConfig({
  plugins: [react()],
  // VITE_BASE_PATH lets the same source be published under a sub-path such as
  // a GitHub Pages project site (/<repo>/app/). Empty/"/" is the appliance
  // deployment, where the frontend is served from the site root.
  base: process.env.VITE_BASE_PATH || "/",
  build: {
    outDir: process.env.VITE_OUT_DIR || "dist",
  },
  server: {
    host: "0.0.0.0",
    allowedHosts: true,
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8069",
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    allowedHosts: true,
  },
});
