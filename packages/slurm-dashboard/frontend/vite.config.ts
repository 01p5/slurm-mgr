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
];

export default defineConfig({
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
