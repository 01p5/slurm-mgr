"""HTTP route shape tests — exercise the route() dispatcher directly
without spinning a socket, against an in-memory registry + a runner
factory that returns _FakeRunner."""
from __future__ import annotations

import json

import pytest

from slurmlib import Cluster, ClusterRegistry, NullAuditLogger
from slurmlib.connection import _FakeRunner

from slurm_dashboard.routes import Deps, route


@pytest.fixture
def deps(tmp_path):
    reg = ClusterRegistry(tmp_path / "hosts.json")
    reg.add(Cluster(name="t", host="h", user="u", key_path="/k"))

    runners: dict[str, _FakeRunner] = {}

    def factory(cluster: Cluster) -> _FakeRunner:
        if cluster.name not in runners:
            runners[cluster.name] = _FakeRunner(cluster=cluster)
        return runners[cluster.name]

    d = Deps(registry=reg, runner_factory=factory, audit=NullAuditLogger())
    d._runners = runners       # type: ignore[attr-defined]  expose for tests
    return d


def _body(triple):
    status, _, payload = triple
    return status, json.loads(payload.decode("utf-8")) if payload else None


def test_healthz(deps):
    status, body = _body(route("GET", "/healthz", {}, None, deps))
    assert status == 200 and body["ok"] is True


def test_list_clusters_redacts_key(deps):
    status, body = _body(route("GET", "/clusters", {}, None, deps))
    assert status == 200
    assert body["clusters"][0]["key_present"] is True
    assert "key_path" not in body["clusters"][0]


def test_add_cluster(deps):
    status, body = _body(route("POST", "/clusters", {}, {
        "name": "new", "host": "h", "user": "u", "key_path": "/k", "port": 22,
    }, deps))
    assert status == 201
    assert body["name"] == "new"


def test_404_for_missing_cluster(deps):
    status, body = _body(route("GET", "/clusters/missing/nodes", {}, None, deps))
    assert status == 404


def test_sinfo_route_calls_sinfo(deps):
    deps._runners.setdefault("t", _FakeRunner(deps.registry.get("t")))  # type: ignore[attr-defined]
    runner = deps.runner_factory(deps.registry.get("t"))
    runner.responses = [(0, '{"nodes":[]}', "")]
    status, body = _body(route("GET", "/clusters/t/nodes", {}, None, deps))
    assert status == 200
    assert body == {"nodes": []}
    assert runner.calls[-1] == ["sinfo", "--json"]


def test_jobs_cancel_route(deps):
    runner = deps.runner_factory(deps.registry.get("t"))
    runner.responses = [(0, "", "")]
    status, body = _body(route("POST", "/clusters/t/jobs/42/cancel", {}, {}, deps))
    assert status == 200 and body["ok"] is True
    assert runner.calls[-1] == ["scancel", "42"]


def test_node_state_requires_state_field(deps):
    status, body = _body(route("POST", "/clusters/t/nodes/n1/state", {}, {}, deps))
    assert status == 400 and "state is required" in body["error"]


def test_node_state_routes(deps):
    runner = deps.runner_factory(deps.registry.get("t"))
    runner.responses = [(0, "", "")]
    status, body = _body(route("POST", "/clusters/t/nodes/n1/state", {}, {
        "state": "DRAIN", "reason": "oom",
    }, deps))
    assert status == 200
    assert runner.calls[-1] == ["scontrol", "update", "NodeName=n1",
                                "State=DRAIN", "Reason=oom"]


def test_partition_lifecycle_routes(deps):
    runner = deps.runner_factory(deps.registry.get("t"))
    runner.responses = [(0, "", "")] * 3
    route("POST", "/clusters/t/partitions", {}, {"name": "debug", "MaxTime": "01:00:00"}, deps)
    route("PATCH", "/clusters/t/partitions/debug", {}, {"State": "DOWN"}, deps)
    route("DELETE", "/clusters/t/partitions/debug", {}, {}, deps)
    assert runner.calls == [
        ["scontrol", "create", "PartitionName=debug", "MaxTime=01:00:00"],
        ["scontrol", "update", "PartitionName=debug", "State=DOWN"],
        ["scontrol", "delete", "PartitionName=debug"],
    ]


def test_delete_cluster(deps):
    status, _ = _body(route("DELETE", "/clusters/t", {}, None, deps))
    assert status == 200
    status, body = _body(route("GET", "/clusters", {}, None, deps))
    assert body["clusters"] == []


def test_unknown_route_404(deps):
    status, body = _body(route("GET", "/clusters/t/nonsense", {}, None, deps))
    assert status == 404 and "no route" in body["error"]


# ---------------------------------------------------------------------------
# S2.A1 — MCP-over-HTTP route. Mirrors slurm-mcp's stdio dispatch
# exactly; we just exercise the HTTP wrapping here.
# ---------------------------------------------------------------------------


def test_mcp_initialize(deps):
    status, body = _body(route("POST", "/mcp/local", {}, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {},
    }, deps))
    assert status == 200
    assert body["result"]["protocolVersion"] == "2024-11-05"
    assert body["result"]["serverInfo"]["name"] == "slurm-mcp"


def test_mcp_tools_list_returns_full_catalog(deps):
    status, body = _body(route("POST", "/mcp/local", {}, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
    }, deps))
    assert status == 200
    tools = body["result"]["tools"]
    # Catalog has 39 tools (17 read + 22 destructive). Don't pin to 39
    # here — just check it covers the well-known ones so a future
    # catalog expansion doesn't break the test.
    names = {t["name"] for t in tools}
    assert {"nodes_list", "jobs_list", "diagnostics_show",
            "jobs_cancel", "cluster_reconfigure"} <= names


def test_mcp_notification_returns_204(deps):
    status, _ = _body(route("POST", "/mcp/local", {}, {
        "jsonrpc": "2.0", "method": "notifications/initialized",
        # id absent — that's what makes this a notification.
    }, deps))
    assert status == 204


def test_mcp_unknown_cluster_404(deps):
    status, body = _body(route("POST", "/mcp/no-such-cluster", {}, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {},
    }, deps))
    assert status == 404 and "not registered" in body["error"]


def test_mcp_bad_path_404(deps):
    status, body = _body(route("POST", "/mcp", {}, {
        "jsonrpc": "2.0", "id": 4, "method": "tools/list",
    }, deps))
    assert status == 404 and "POST /mcp/<cluster>" in body["error"]


def test_mcp_non_dict_body_400(deps):
    # route()'s top-level `body = body or {}` makes None unreachable
    # at the handler — exercise the explicit non-dict path with a list.
    from slurm_dashboard.routes import _mcp_handler
    status, _, payload = _mcp_handler("local", ["not", "a", "dict"], deps)  # type: ignore[arg-type]
    assert status == 400
    assert b"JSON-RPC envelope" in payload
