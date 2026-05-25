"""HTTP server shell — thin BaseHTTPRequestHandler over ``routes.route``.

Same pattern as Olympus's dashboard server, but smaller (no LLM, no bus,
no SSE for v1). The routes module is the testable surface; this file
just plumbs request/response.
"""
from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from slurmlib import ClusterRegistry, JsonlAuditLogger, SSHRunner

from .routes import Deps, parse_request, route

logger = logging.getLogger(__name__)


# Where the built SPA lives. The vite build outputs here (see frontend/vite.config.ts).
DEFAULT_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "dist"

# Path prefixes that are API endpoints, not SPA routes. If route() returns
# 404 for one of these, the structured JSON error must reach the client —
# don't fall through to index.html.
API_PREFIXES = ("/clusters", "/healthz", "/audit", "/tools")


def _is_api_path(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in API_PREFIXES)


class Handler(BaseHTTPRequestHandler):
    """One request → one ``route()`` call. Static assets fall through
    after the API routes 404."""

    deps: Deps                # type: ignore[assignment]  set by build_server
    static_dir: Path          # type: ignore[assignment]

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Quiet the default BaseHTTPRequestHandler chatter; we have logger.
        logger.info("%s - %s", self.address_string(), format % args)

    # ----- HTTP verbs -----

    def do_GET(self) -> None: self._handle("GET")
    def do_POST(self) -> None: self._handle("POST")
    def do_PATCH(self) -> None: self._handle("PATCH")
    def do_DELETE(self) -> None: self._handle("DELETE")
    def do_OPTIONS(self) -> None:
        # Minimal CORS so the vite dev server can talk to us without a proxy
        # config change. Locked to localhost in practice.
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ----- Core handler -----

    def _handle(self, method: str) -> None:
        path, query = parse_request(self.path)
        body = self._read_body()

        status, headers, payload = route(method, path, query, body, self.deps)

        # API miss → try a static file (the SPA's index.html for any unknown
        # GET so client-side routing works). Mirrors Olympus. But don't
        # eat API-shaped 404s — if the path looked like an API endpoint
        # (clusters/healthz/audit/tools), leave the structured JSON
        # error alone so clients see the real failure.
        if status == 404 and method == "GET" and not _is_api_path(path):
            served = self._maybe_serve_static(path)
            if served:
                return

        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def _read_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return None
        raw = self.rfile.read(length)
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def _maybe_serve_static(self, path: str) -> bool:
        """Serve files under ``static_dir`` with an SPA fallback to
        ``index.html``. Returns True iff something was written.
        """
        if not self.static_dir.exists():
            return False
        rel = path.lstrip("/") or "index.html"
        candidate = (self.static_dir / rel).resolve()
        if not str(candidate).startswith(str(self.static_dir.resolve())):
            return False  # path traversal guard
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.exists():
            # SPA fallback — let the React router handle the URL.
            candidate = self.static_dir / "index.html"
            if not candidate.exists():
                return False
        body = candidate.read_bytes()
        ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
        return True


# ----------------------------------------------------------------------
# Builder + entry-point
# ----------------------------------------------------------------------


def build_server(
    host: str = "127.0.0.1",
    port: int = 8770,
    registry: ClusterRegistry | None = None,
    audit: JsonlAuditLogger | None = None,
    static_dir: Path | None = None,
) -> ThreadingHTTPServer:
    """Wire deps onto the Handler class and return an HTTPServer."""
    reg = registry or ClusterRegistry()
    aud = audit or JsonlAuditLogger()

    def _runner(cluster):  # cluster -> SSHRunner
        return SSHRunner(cluster)

    deps = Deps(registry=reg, runner_factory=_runner, audit=aud)

    handler_cls = type("BoundHandler", (Handler,), {
        "deps": deps,
        "static_dir": static_dir or DEFAULT_STATIC_DIR,
    })
    return ThreadingHTTPServer((host, port), handler_cls)


def main() -> int:
    parser = argparse.ArgumentParser(prog="slurm-dashboard")
    parser.add_argument("--host", default=os.environ.get("SLURM_MGR_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int,
        default=int(os.environ.get("SLURM_MGR_PORT", "8770")),
    )
    parser.add_argument(
        "--static-dir", default=None,
        help="Override path to the built SPA (defaults to packages/slurm-dashboard/static/dist).",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    server = build_server(
        host=args.host,
        port=args.port,
        static_dir=Path(args.static_dir) if args.static_dir else None,
    )
    logger.info("slurm-dashboard listening on http://%s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
