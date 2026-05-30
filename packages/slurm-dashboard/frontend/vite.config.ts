import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build output lands at ../static/dist so the Python backend's static
// fallback serves the SPA without a second web server. Dev server
// proxies the same routes as the prod backend (see routes.py).
const API_PATHS = [
  "/healthz",
  "/clusters",
  "/audit",
  "/tools",
  "/mcp",
];

// S2.A2 — base-path support for sub-path serving (e.g. mounted under
// Olympus at /slurm/* via reverse proxy). Set VITE_BASE_PATH=/slurm/
// at build time to rewrite asset URLs accordingly. Dev / standalone
// prod build use "/" — matches how the backend serves index.html.
const BASE = process.env.VITE_BASE_PATH ?? "/";

export default defineConfig({
  base: BASE,
  plugins: [react()],
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5174,
    proxy: Object.fromEntries(API_PATHS.map((p) => [p, "http://127.0.0.1:8770"])),
  },
});
