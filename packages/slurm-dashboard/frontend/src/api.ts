// Tiny fetch wrapper. The dashboard backend speaks plain JSON.
//
// On error: throws an Error whose .message is the server's `error`
// field (or, failing that, the HTTP status). Callers can `.catch`
// once at the page level.

export type ApiError = { error: string; [k: string]: unknown };

// S2.A2 — when the SPA is served under a sub-path (Olympus reverse
// proxy at /slurm/*), Vite injects the base via import.meta.env.BASE_URL.
// We prefix every API call with it so a relative-looking call like
// "/healthz" actually hits "/slurm/healthz" — which Olympus then
// strips before forwarding to the slurm-dashboard backend.
// Standalone (BASE_URL === "/") strips to empty → no change.
const API_BASE = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  const url = path.startsWith("/") ? `${API_BASE}${path}` : path;
  const res = await fetch(url, init);
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (data && typeof data === "object" && "error" in (data as object)) {
      msg = String((data as ApiError).error);
    }
    const err = new Error(msg) as Error & { detail?: unknown };
    err.detail = data;
    throw err;
  }
  return data as T;
}

export const api = {
  get:    <T = unknown>(p: string) => request<T>("GET", p),
  post:   <T = unknown>(p: string, body?: unknown) => request<T>("POST", p, body),
  patch:  <T = unknown>(p: string, body?: unknown) => request<T>("PATCH", p, body),
  delete: <T = unknown>(p: string) => request<T>("DELETE", p),
};

// ---- Domain types (just the shape we use from JSON output) ----

export type ClusterSummary = {
  name: string;
  host: string;
  user: string;
  port: number;
  jump_host: string | null;
  key_present: boolean;
};

export type Node = Record<string, unknown> & {
  name?: string;
  hostname?: string;
  state?: string[];
  cpus?: number;
  real_memory?: number;
  partitions?: string[];
  reason?: string;
  // sinfo --json schemas vary by Slurm version; we treat extras as opaque.
};

export type Job = Record<string, unknown> & {
  job_id?: number | string;
  name?: string;
  user_name?: string;
  partition?: string;
  job_state?: string | string[];
  nodes?: string;
  // ditto — schema varies, treat unknowns as opaque.
};

export type SinfoResponse = { nodes?: Node[] } & Record<string, unknown>;
export type SqueueResponse = { jobs?: Job[] } & Record<string, unknown>;

export type DestructiveResult = {
  ok: boolean;
  stdout?: string;
};
