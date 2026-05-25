"""MCP stdio server for Slurm.

Hand-rolled JSON-RPC 2.0 (protocol revision ``2024-11-05``) so we
match Olympus's ``infra/demo-mcp-server/server.py`` wire shape and
land cleanly through ``libs/agentlib/mcp.py``'s ``StdioTransport``.

One JSON object per line on stdin/stdout. ``notifications/initialized``
is acknowledged silently (no id, no response, per spec).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from slurmlib import ClusterRegistry, SlurmClient
from slurmlib.connection import LocalRunner, SSHRunner

from .tools import dispatch_tool, tools_descriptor


PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "slurm-mcp", "version": "0.1.0"}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# JSON-RPC envelope helpers
# ---------------------------------------------------------------------


def _ok(msg_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------
# Request dispatch — kept dependency-light so we can unit-test it
# without a subprocess.
# ---------------------------------------------------------------------


def dispatch(request: dict, client: SlurmClient | None) -> dict | None:
    """Return the response envelope, or None for notifications.

    ``client`` is None only during early-init flows (initialize +
    notifications/initialized) and for ``tools/list`` calls — those
    don't actually need to hit the cluster.
    """
    method = request.get("method")
    msg_id = request.get("id")
    params = request.get("params") or {}

    # Notifications: spec says no response.
    if msg_id is None:
        return None

    if method == "initialize":
        return _ok(msg_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })

    if method == "tools/list":
        return _ok(msg_id, {"tools": tools_descriptor()})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if client is None:
            return _ok(msg_id, {
                "content": [{"type": "text", "text": "no cluster bound (use --cluster <name> or --local)"}],
                "isError": True,
            })
        return _ok(msg_id, dispatch_tool(client, name, args))

    return _err(msg_id, -32601, f"method not found: {method}")


# ---------------------------------------------------------------------
# Stdio main loop
# ---------------------------------------------------------------------


def _make_client(cluster_name: str | None, use_local: bool) -> SlurmClient | None:
    if use_local:
        return SlurmClient(LocalRunner(cluster_name=cluster_name or "local"))
    if cluster_name:
        reg = ClusterRegistry()
        cluster = reg.get(cluster_name)
        return SlurmClient(SSHRunner(cluster))
    return None


def serve(client: SlurmClient | None,
          stdin=sys.stdin, stdout=sys.stdout) -> int:
    """Run the JSON-RPC loop. Separated from ``main`` so tests can
    drive it with StringIO."""
    try:
        # Force line buffering so Olympus's StdioTransport sees responses
        # immediately. Same trick the demo-mcp-server uses.
        stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"parse error: {exc}"},
            }) + "\n")
            stdout.flush()
            continue

        try:
            response = dispatch(request, client)
        except Exception as exc:  # belt-and-suspenders
            logger.exception("dispatch failed")
            response = _err(request.get("id"), -32603, f"internal error: {exc}")

        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="slurm-mcp")
    parser.add_argument("--cluster", help="Cluster name from ~/.slurm-mgr/hosts.json")
    parser.add_argument("--local", action="store_true",
                        help="Run commands locally (useful on the controller, or for testing).")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level.upper(),
        stream=sys.stderr,                  # never write logs to stdout — Olympus parses that
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not args.cluster and not args.local:
        sys.stderr.write("slurm-mcp: --cluster <name> or --local is required\n")
        return 2
    try:
        client = _make_client(args.cluster, args.local)
    except KeyError as exc:
        sys.stderr.write(f"slurm-mcp: {exc}\n")
        return 2
    return serve(client)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
