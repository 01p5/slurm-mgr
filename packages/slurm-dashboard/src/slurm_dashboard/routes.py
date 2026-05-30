"""HTTP route handlers, decoupled from the BaseHTTPRequestHandler shell.

Each handler takes ``(method, path, query, body, deps)`` and returns
``(status, headers, body)``. That seam lets tests drive the routes
directly without opening a socket — the same trick Olympus uses in
``agents/dashboard/src/dashboard/server.py``.

``deps`` is a small object carrying the cluster registry, an SSH-runner
factory, and the audit logger. Tests inject a fake registry + a
``LocalRunner``-wrapping factory.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable

from slurmlib import (
    Cluster,
    ClusterRegistry,
    CommandError,
    JsonlAuditLogger,
    NullAuditLogger,
    SlurmClient,
)
from slurmlib.commands import DESTRUCTIVE_TOOLS
from slurmlib.connection import LocalRunner
from slurm_mcp.server import dispatch as _mcp_dispatch

# ----------------------------------------------------------------------
# Dependency bundle — passed to every route handler.
# ----------------------------------------------------------------------


@dataclass
class Deps:
    registry: ClusterRegistry
    runner_factory: Callable[[Cluster], Any]          # cluster -> Runner
    audit: JsonlAuditLogger | NullAuditLogger


# ----------------------------------------------------------------------
# Tiny utility: build response triple.
# ----------------------------------------------------------------------


def _json(status: int, payload: Any) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(payload, default=str).encode("utf-8")
    return status, {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "Cache-Control": "no-store",
    }, body


def _err(status: int, message: str, **extra) -> tuple[int, dict, bytes]:
    return _json(status, {"error": message, **extra})


def _client_for(deps: Deps, cluster_name: str) -> SlurmClient:
    cluster = deps.registry.get(cluster_name)
    runner = deps.runner_factory(cluster)
    return SlurmClient(runner)


def _safe_destructive_call(
    deps: Deps, cluster_name: str, tool: str, fn: Callable[[], Any],
) -> tuple[int, dict, bytes]:
    """Wrap a destructive call with audit pre/post + uniform error shape."""
    argv_placeholder = [tool]  # the real argv is captured by SlurmClient internally
    with deps.audit.around(
        actor="dashboard", cluster=cluster_name, argv=argv_placeholder,
        destructive=True, note=tool,
    ) as ctx:
        try:
            result = fn()
            ctx.set_result(result)
            return _json(200, {"ok": True, "stdout": getattr(result, "stdout", "")})
        except CommandError as exc:
            ctx.set_result(exc.result)
            return _err(
                502, f"slurm rejected {tool}",
                stderr=exc.result.stderr,
                stdout=exc.result.stdout,
                returncode=exc.result.returncode,
            )
        except ValueError as exc:
            return _err(400, str(exc))


# ----------------------------------------------------------------------
# Route table
# ----------------------------------------------------------------------


_CLUSTER = r"(?P<cluster>[A-Za-z0-9_\-]+)"
_NAME = r"(?P<name>[A-Za-z0-9_\-\.@]+)"
_JOBID = r"(?P<jobid>[A-Za-z0-9_\-\.]+)"


def route(
    method: str,
    path: str,
    query: dict[str, str],
    body: dict[str, Any] | None,
    deps: Deps,
) -> tuple[int, dict[str, str], bytes]:
    """Top-level dispatcher. Returns (status, headers, body)."""
    body = body or {}

    if method == "GET" and path == "/healthz":
        return _json(200, {"ok": True, "service": "slurm-dashboard"})

    if method == "GET" and path == "/audit":
        return _audit_tail(deps)

    if method == "GET" and path == "/tools":
        return _json(200, {
            "destructive": sorted(DESTRUCTIVE_TOOLS),
        })

    # ---- MCP-over-HTTP (S2.A1) ----
    # POST /mcp/<cluster> — JSON-RPC 2.0 envelope on the body, single
    # response on the body (no SSE). Cluster name "local" routes the
    # call through a LocalRunner (matches slurm-mcp's --local mode);
    # any other name resolves via the dashboard's cluster registry.
    # The wire shape mirrors slurm-mcp's stdio loop exactly so
    # Olympus's HttpTransport can talk to it without translation.
    m = re.fullmatch(r"/mcp/(?P<cluster>[A-Za-z0-9_\-\.]+)", path)
    if m and method == "POST":
        return _mcp_handler(m.group("cluster"), body, deps)
    if path.startswith("/mcp") and method == "POST":
        return _err(404, "POST /mcp/<cluster> (use 'local' for local-mode)")

    # ---- Cluster registry ----
    if method == "GET" and path == "/clusters":
        return _json(200, {
            "clusters": [_redacted(c) for c in deps.registry.list()],
        })
    if method == "POST" and path == "/clusters":
        return _add_cluster(body, deps)
    m = re.fullmatch(rf"/clusters/{_CLUSTER}", path)
    if m and method == "DELETE":
        deps.registry.remove(m.group("cluster"))
        return _json(200, {"ok": True})
    m = re.fullmatch(rf"/clusters/{_CLUSTER}/check", path)
    if m and method == "GET":
        return _cluster_check(deps, m.group("cluster"))

    # ---- Everything else lives under /clusters/<name>/... ----
    m = re.fullmatch(rf"/clusters/{_CLUSTER}/(?P<rest>.*)", path)
    if not m:
        return _err(404, f"no route for {method} {path}")
    cluster = m.group("cluster")
    rest = "/" + m.group("rest")

    # Resolve cluster up-front for a clean 404.
    try:
        deps.registry.get(cluster)
    except KeyError as exc:
        return _err(404, str(exc))

    return _cluster_subrouter(method, rest, query, body, deps, cluster)


# ----------------------------------------------------------------------
# Cluster sub-router (all the read-only + destructive ops)
# ----------------------------------------------------------------------


def _cluster_subrouter(
    method: str, path: str, query: dict[str, str], body: dict, deps: Deps, cluster: str,
) -> tuple[int, dict, bytes]:

    # ---- Read-only state ----
    if method == "GET" and path == "/nodes":
        return _read(deps, cluster, lambda c: c.sinfo())
    if method == "GET" and path == "/nodes/details":
        return _read(deps, cluster, lambda c: c.scontrol_show_node())
    if method == "GET" and path == "/jobs":
        return _read(deps, cluster, lambda c: c.squeue())
    m = re.fullmatch(rf"/jobs/{_JOBID}", path)
    if m and method == "GET":
        return _read(deps, cluster, lambda c, j=m.group("jobid"): c.scontrol_show_job(j))
    if method == "GET" and path == "/partitions":
        return _read(deps, cluster, lambda c: c.scontrol_show_partition())
    if method == "GET" and path == "/reservations":
        return _read(deps, cluster, lambda c: c.scontrol_show_reservation())
    if method == "GET" and path == "/config":
        return _read(deps, cluster, lambda c: c.scontrol_show_config())
    if method == "GET" and path == "/diag":
        return _read(deps, cluster, lambda c: c.sdiag())
    if method == "GET" and path == "/sshare":
        return _read(deps, cluster, lambda c: c.sshare())
    if method == "GET" and path == "/sprio":
        return _read(deps, cluster, lambda c: c.sprio())
    if method == "GET" and path == "/sstat":
        jobid = query.get("jobid")
        if not jobid:
            return _err(400, "sstat requires ?jobid=<id>")
        return _read(deps, cluster, lambda c: c.sstat(jobid))
    if method == "GET" and path == "/accounting":
        return _read(
            deps, cluster,
            lambda c: c.sacct(
                starttime=query.get("starttime"),
                endtime=query.get("endtime"),
                users=query.get("users"),
                accounts=query.get("accounts"),
                states=query.get("states"),
            ),
        )
    if method == "GET" and path == "/sreport":
        report_args = query.get("args", "").split()
        if not report_args:
            return _err(400, "sreport requires ?args=...")
        try:
            text = _client_for(deps, cluster).sreport(report_args)
            return _json(200, {"stdout": text})
        except CommandError as exc:
            return _err(502, str(exc), stderr=exc.result.stderr)

    # ---- sacctmgr show (read-only) ----
    for entity, route_path in (
        ("account", "/accounts"),
        ("user", "/users"),
        ("assoc", "/assocs"),
        ("qos", "/qos"),
        ("cluster", "/clusters-registered"),
    ):
        if method == "GET" and path == route_path:
            return _read(
                deps, cluster, lambda c, e=entity: {"rows": c.sacctmgr_show(e)},
            )

    # ---- Destructive: jobs ----
    m = re.fullmatch(rf"/jobs/{_JOBID}/cancel", path)
    if m and method == "POST":
        sig = body.get("signal")
        return _safe_destructive_call(
            deps, cluster, "jobs_cancel",
            lambda j=m.group("jobid"): _client_for(deps, cluster).scancel(j, signal=sig),
        )
    m = re.fullmatch(rf"/jobs/{_JOBID}/hold", path)
    if m and method == "POST":
        return _safe_destructive_call(
            deps, cluster, "jobs_hold",
            lambda j=m.group("jobid"): _client_for(deps, cluster).scontrol_hold(j),
        )
    m = re.fullmatch(rf"/jobs/{_JOBID}/release", path)
    if m and method == "POST":
        return _safe_destructive_call(
            deps, cluster, "jobs_release",
            lambda j=m.group("jobid"): _client_for(deps, cluster).scontrol_release(j),
        )
    m = re.fullmatch(rf"/jobs/{_JOBID}/requeue", path)
    if m and method == "POST":
        return _safe_destructive_call(
            deps, cluster, "jobs_requeue",
            lambda j=m.group("jobid"): _client_for(deps, cluster).scontrol_requeue(j),
        )
    m = re.fullmatch(rf"/jobs/{_JOBID}", path)
    if m and method == "PATCH":
        return _safe_destructive_call(
            deps, cluster, "jobs_update",
            lambda j=m.group("jobid"), f=body: _client_for(deps, cluster).scontrol_update_job(j, **f),
        )

    # ---- Destructive: nodes ----
    m = re.fullmatch(rf"/nodes/{_NAME}/state", path)
    if m and method == "POST":
        state = body.get("state")
        reason = body.get("reason")
        if not state:
            return _err(400, "state is required")
        return _safe_destructive_call(
            deps, cluster, "nodes_set_state",
            lambda n=m.group("name"): _client_for(deps, cluster).scontrol_update_node(
                n, state, reason,
            ),
        )

    # ---- Destructive: partitions ----
    if method == "POST" and path == "/partitions":
        name = body.pop("name", None)
        if not name:
            return _err(400, "name required")
        return _safe_destructive_call(
            deps, cluster, "partitions_create",
            lambda f=body: _client_for(deps, cluster).scontrol_create_partition(name, **f),
        )
    m = re.fullmatch(rf"/partitions/{_NAME}", path)
    if m and method == "PATCH":
        return _safe_destructive_call(
            deps, cluster, "partitions_update",
            lambda n=m.group("name"), f=body:
                _client_for(deps, cluster).scontrol_update_partition(n, **f),
        )
    if m and method == "DELETE":
        return _safe_destructive_call(
            deps, cluster, "partitions_delete",
            lambda n=m.group("name"):
                _client_for(deps, cluster).scontrol_delete_partition(n),
        )

    # ---- Destructive: reservations ----
    if method == "POST" and path == "/reservations":
        return _safe_destructive_call(
            deps, cluster, "reservations_create",
            lambda f=body: _client_for(deps, cluster).scontrol_create_reservation(**f),
        )
    m = re.fullmatch(rf"/reservations/{_NAME}", path)
    if m and method == "PATCH":
        return _safe_destructive_call(
            deps, cluster, "reservations_update",
            lambda n=m.group("name"), f=body:
                _client_for(deps, cluster).scontrol_update_reservation(n, **f),
        )
    if m and method == "DELETE":
        return _safe_destructive_call(
            deps, cluster, "reservations_delete",
            lambda n=m.group("name"):
                _client_for(deps, cluster).scontrol_delete_reservation(n),
        )

    # ---- Destructive: accounts / users / qos ----
    if method == "POST" and path == "/accounts":
        name = body.pop("name", None)
        if not name:
            return _err(400, "name required")
        return _safe_destructive_call(
            deps, cluster, "accounts_add",
            lambda f=body: _client_for(deps, cluster).sacctmgr_add_account(name, **f),
        )
    m = re.fullmatch(rf"/accounts/{_NAME}", path)
    if m and method == "PATCH":
        return _safe_destructive_call(
            deps, cluster, "accounts_modify",
            lambda n=m.group("name"), f=body:
                _client_for(deps, cluster).sacctmgr_modify_account(n, f),
        )
    if m and method == "DELETE":
        return _safe_destructive_call(
            deps, cluster, "accounts_delete",
            lambda n=m.group("name"):
                _client_for(deps, cluster).sacctmgr_delete_account(n),
        )

    if method == "POST" and path == "/users":
        name = body.pop("name", None)
        if not name:
            return _err(400, "name required")
        account = body.pop("account", None)
        return _safe_destructive_call(
            deps, cluster, "users_add",
            lambda f=body: _client_for(deps, cluster).sacctmgr_add_user(
                name, account=account, **f,
            ),
        )
    m = re.fullmatch(rf"/users/{_NAME}", path)
    if m and method == "PATCH":
        return _safe_destructive_call(
            deps, cluster, "users_modify",
            lambda n=m.group("name"), f=body:
                _client_for(deps, cluster).sacctmgr_modify_user(n, f),
        )
    if m and method == "DELETE":
        return _safe_destructive_call(
            deps, cluster, "users_delete",
            lambda n=m.group("name"):
                _client_for(deps, cluster).sacctmgr_delete_user(n),
        )

    if method == "POST" and path == "/qos":
        name = body.pop("name", None)
        if not name:
            return _err(400, "name required")
        return _safe_destructive_call(
            deps, cluster, "qos_add",
            lambda f=body: _client_for(deps, cluster).sacctmgr_add_qos(name, **f),
        )
    m = re.fullmatch(rf"/qos/{_NAME}", path)
    if m and method == "PATCH":
        return _safe_destructive_call(
            deps, cluster, "qos_modify",
            lambda n=m.group("name"), f=body:
                _client_for(deps, cluster).sacctmgr_modify_qos(n, f),
        )
    if m and method == "DELETE":
        return _safe_destructive_call(
            deps, cluster, "qos_delete",
            lambda n=m.group("name"):
                _client_for(deps, cluster).sacctmgr_delete_qos(n),
        )

    # ---- Cluster-wide ----
    if method == "POST" and path == "/reconfigure":
        return _safe_destructive_call(
            deps, cluster, "cluster_reconfigure",
            lambda: _client_for(deps, cluster).scontrol_reconfigure(),
        )

    return _err(404, f"no route for {method} /clusters/{cluster}{path}")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _read(deps: Deps, cluster: str, fn: Callable[[SlurmClient], Any]) -> tuple[int, dict, bytes]:
    """Read-only call. Audited (best-effort, non-blocking on error)."""
    with deps.audit.around(
        actor="dashboard", cluster=cluster, argv=["read"], destructive=False,
    ) as ctx:
        try:
            result = fn(_client_for(deps, cluster))
            ctx.set_result(None)
            return _json(200, result)
        except CommandError as exc:
            ctx.set_result(exc.result)
            return _err(
                502, str(exc),
                stderr=exc.result.stderr, returncode=exc.result.returncode,
            )
        except KeyError as exc:
            return _err(404, str(exc))


def _add_cluster(body: dict, deps: Deps) -> tuple[int, dict, bytes]:
    try:
        cluster = Cluster(
            name=body["name"],
            host=body["host"],
            user=body["user"],
            key_path=body["key_path"],
            port=int(body.get("port", 22)),
            jump_host=body.get("jump_host") or None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _err(400, f"invalid cluster: {exc}")
    deps.registry.add(cluster)
    return _json(201, _redacted(cluster))


def _redacted(cluster: Cluster) -> dict:
    """Strip the key path so the registry endpoint doesn't leak filesystem
    paths to anyone who can hit /clusters. The dashboard runs locally, so
    this is belt-and-suspenders.
    """
    return {
        "name": cluster.name, "host": cluster.host, "user": cluster.user,
        "port": cluster.port, "jump_host": cluster.jump_host,
        "key_present": bool(cluster.key_path),
    }


def _cluster_check(deps: Deps, name: str) -> tuple[int, dict, bytes]:
    """Best-effort reachability probe — runs ``scontrol ping`` and
    returns the parsed result. ``scontrol ping`` exits 0 even when the
    backup controller is down, so we look at stdout for the verdict.
    """
    try:
        client = _client_for(deps, name)
        result = client._run(["scontrol", "ping"], timeout=10)  # noqa: SLF001
        return _json(200 if result.ok else 502, {
            "ok": result.ok,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        })
    except KeyError as exc:
        return _err(404, str(exc))
    except Exception as exc:  # paramiko / network errors
        return _err(502, f"ssh connect failed: {type(exc).__name__}: {exc}")


def _audit_tail(deps: Deps) -> tuple[int, dict, bytes]:
    """Return the last N audit records, newest last. Skipped when the
    audit logger is null (``NullAuditLogger`` doesn't expose a path).
    """
    path = getattr(deps.audit, "path", None)
    if not path or not path.exists():
        return _json(200, {"records": []})
    lines = path.read_text(encoding="utf-8").splitlines()[-200:]
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return _json(200, {"records": records})


# ----------------------------------------------------------------------
# Tiny request parser — used by the HTTP server shell.
# ----------------------------------------------------------------------


def _mcp_handler(
    cluster_name: str, body: dict | None, deps: Deps,
) -> tuple[int, dict, bytes]:
    """JSON-RPC 2.0 over HTTP for the slurm-mcp tool catalog.

    Body must be a single JSON-RPC envelope. We dispatch via
    slurm_mcp.server.dispatch (the same function the stdio loop
    drives) so the wire shape stays in lock-step between stdio + HTTP
    transports — Olympus's HttpTransport speaks the same dialect as
    StdioTransport.

    Notifications (no id field) return 204 with empty body. Anything
    else returns 200 + the JSON-RPC response envelope.
    """
    if not isinstance(body, dict):
        return _err(400, "expected JSON-RPC envelope body")

    # Bind a SlurmClient to the requested cluster. "local" is a magic
    # name matching slurm-mcp's --local flag (LocalRunner, no SSH).
    if cluster_name == "local":
        client: SlurmClient | None = SlurmClient(LocalRunner(cluster_name="local"))
    else:
        try:
            cluster = deps.registry.get(cluster_name)
        except KeyError as exc:
            return _err(404, f"cluster {cluster_name!r} not registered: {exc}")
        client = SlurmClient(deps.runner_factory(cluster))

    response = _mcp_dispatch(body, client)
    if response is None:
        # Notification — spec says no response body.
        return 204, {}, b""
    return _json(200, response)


def parse_request(raw_path: str) -> tuple[str, dict[str, str]]:
    parsed = urllib.parse.urlsplit(raw_path)
    return parsed.path, {
        k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()
    }
