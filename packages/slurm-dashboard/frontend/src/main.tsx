import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

// React Router basename — derived from the same VITE_BASE_PATH the rest
// of the SPA uses for sub-path mounting. Standalone build (base="/") →
// basename="" → routes at /hosts, /nodes, etc. Olympus embed build
// (base="/slurm/") → basename="/slurm" → routes at /slurm/hosts etc.
// Keeps the SPA usable both ways with no per-build branching.
const ROUTER_BASENAME =
  (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "") || undefined;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename={ROUTER_BASENAME}>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
