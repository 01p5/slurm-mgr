"""Exhaustive route coverage — one test per (verb, path) pair plus the
notable error paths. Together with test_routes.py this drives
routes.py past 90% line coverage and protects the entire HTTP surface
against accidental regressions."""
from __future__ import annotations

import json

import pytest

from slurmlib import (
    Cluster, ClusterRegistry, JsonlAuditLogger, NullAuditLogger,
)
from slurmlib.connection import _FakeRunner

from slurm_dashboard.routes import Deps, parse_request, route


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def runner_holder():
    """A holder so the test can read .calls after make_deps wires it up."""
    return {}


@pytest.fixture
def make_deps(tmp_path, runner_holder):
    def _make(audit=None):
        reg = ClusterRegistry(tmp_path / "hosts.json")
        reg.add(Cluster(name="c1", host="h", user="u", key_path="/k"))

        def factory(cluster: Cluster) -> _FakeRunner:
            if cluster.name not in runner_holder:
                runner_holder[cluster.name] = _FakeRunner(cluster=cluster)
            return runner_holder[cluster.name]

        return Deps(registry=reg, runner_factory=factory,
                    audit=audit or NullAuditLogger())
    return _make


def _decode(triple):
    status, _, payload = triple
    return status, (json.loads(payload.decode("utf-8")) if payload else None)


def _call(method, path, deps, query=None, body=None):
    return _decode(route(method, path, query or {}, body, deps))


# ----------------------------------------------------------------------
# Top-level
# ----------------------------------------------------------------------


def test_tools_route_returns_destructive_set(make_deps):
    status, body = _call("GET", "/tools", make_deps())
    assert status == 200
    assert "jobs_cancel" in body["destructive"]


def test_completely_unknown_top_level_route_is_404(make_deps):
    status, body = _call("GET", "/garbage/here", make_deps())
    assert status == 404 and "no route" in body["error"]


def test_add_cluster_bad_payload(make_deps):
    status, body = _call("POST", "/clusters", make_deps(), body={"name": "no-host"})
    assert status == 400 and "invalid cluster" in body["error"]


# ----------------------------------------------------------------------
# Cluster reachability check
# ----------------------------------------------------------------------


def test_cluster_check_ok(make_deps, runner_holder):
    deps = make_deps()
    # Prime the runner so the runner factory caches a usable instance.
    runner_holder.setdefault("c1", _FakeRunner(cluster=deps.registry.get("c1")))
    runner_holder["c1"].responses = [(0, "Slurmctld(primary) at host is UP", "")]
    status, body = _call("GET", "/clusters/c1/check", deps)
    assert status == 200 and body["ok"] is True
    assert "Slurmctld" in body["stdout"]


def test_cluster_check_unknown_cluster_is_404(make_deps):
    status, body = _call("GET", "/clusters/nope/check", make_deps())
    assert status == 404


def test_cluster_check_runner_factory_blows_up_returns_502(make_deps):
    """If the factory raises (e.g. SSH connect error), the route should
    convert it into a clean 502 instead of an uncaught traceback."""
    deps = make_deps()

    def bad_factory(_cluster):
        raise ConnectionError("dial tcp: i/o timeout")

    deps.runner_factory = bad_factory
    status, body = _call("GET", "/clusters/c1/check", deps)
    assert status == 502 and "ssh connect failed" in body["error"]


# ----------------------------------------------------------------------
# Read-only state endpoints — drive each one
# ----------------------------------------------------------------------


READ_ROUTES = [
    ("/nodes",          ["sinfo", "--json"]),
    ("/nodes/details",  ["scontrol", "show", "node", "--json"]),
    ("/jobs",           ["squeue", "--json"]),
    ("/partitions",     ["scontrol", "show", "partition", "--json"]),
    ("/reservations",   ["scontrol", "show", "reservation", "--json"]),
    ("/config",         ["scontrol", "show", "config", "--json"]),
    ("/diag",           ["sdiag", "--json"]),
    ("/sshare",         ["sshare", "--json"]),
    ("/sprio",          ["sprio", "--json"]),
]


@pytest.mark.parametrize("suffix,expected_argv", READ_ROUTES)
def test_read_endpoints_each_invoke_expected_command(make_deps, runner_holder, suffix, expected_argv):
    deps = make_deps()
    runner_holder.setdefault("c1", _FakeRunner(cluster=deps.registry.get("c1")))
    runner_holder["c1"].responses = [(0, "{}", "")]
    status, body = _call("GET", f"/clusters/c1{suffix}", deps)
    assert status == 200, body
    assert runner_holder["c1"].calls[-1] == expected_argv


def test_jobs_describe(make_deps, runner_holder):
    deps = make_deps()
    runner_holder.setdefault("c1", _FakeRunner(cluster=deps.registry.get("c1")))
    runner_holder["c1"].responses = [(0, "{}", "")]
    status, _ = _call("GET", "/clusters/c1/jobs/42", deps)
    assert status == 200
    assert runner_holder["c1"].calls[-1] == ["scontrol", "show", "job", "42", "--json"]


def test_sstat_requires_jobid(make_deps):
    status, body = _call("GET", "/clusters/c1/sstat", make_deps())
    assert status == 400 and "sstat requires" in body["error"]


def test_sstat_routes_with_query(make_deps, runner_holder):
    deps = make_deps()
    runner_holder.setdefault("c1", _FakeRunner(cluster=deps.registry.get("c1")))
    runner_holder["c1"].responses = [(0, "{}", "")]
    status, _ = _call("GET", "/clusters/c1/sstat", deps, query={"jobid": "99"})
    assert status == 200
    assert runner_holder["c1"].calls[-1] == ["sstat", "--json", "-j", "99"]


def test_accounting_uses_query_filters(make_deps, runner_holder):
    deps = make_deps()
    runner_holder.setdefault("c1", _FakeRunner(cluster=deps.registry.get("c1")))
    runner_holder["c1"].responses = [(0, "{}", "")]
    status, _ = _call(
        "GET", "/clusters/c1/accounting", deps,
        query={"starttime": "2026-05-01", "users": "alice", "states": "CD"},
    )
    assert status == 200
    assert runner_holder["c1"].calls[-1] == [
        "sacct", "--json",
        "--starttime", "2026-05-01",
        "--user", "alice",
        "--state", "CD",
    ]


def test_sreport_requires_args(make_deps):
    status, body = _call("GET", "/clusters/c1/sreport", make_deps())
    assert status == 400 and "sreport requires" in body["error"]


def test_sreport_passes_args(make_deps, runner_holder):
    deps = make_deps()
    runner_holder.setdefault("c1", _FakeRunner(cluster=deps.registry.get("c1")))
    runner_holder["c1"].responses = [(0, "report-text", "")]
    status, body = _call("GET", "/clusters/c1/sreport", deps,
                         query={"args": "cluster utilization"})
    assert status == 200 and body["stdout"] == "report-text"
    assert runner_holder["c1"].calls[-1] == ["sreport", "--parsable2", "cluster", "utilization"]


def test_read_endpoint_5xx_when_command_fails(make_deps, runner_holder):
    deps = make_deps()
    runner_holder.setdefault("c1", _FakeRunner(cluster=deps.registry.get("c1")))
    runner_holder["c1"].responses = [(1, "", "controller down")]
    status, body = _call("GET", "/clusters/c1/nodes", deps)
    assert status == 502 and "controller down" in body["stderr"]


# ----------------------------------------------------------------------
# sacctmgr show endpoints
# ----------------------------------------------------------------------


@pytest.mark.parametrize("suffix,entity", [
    ("/accounts",            "account"),
    ("/users",               "user"),
    ("/assocs",              "assoc"),
    ("/qos",                 "qos"),
    ("/clusters-registered", "cluster"),
])
def test_sacctmgr_show_routes(make_deps, runner_holder, suffix, entity):
    deps = make_deps()
    runner_holder.setdefault("c1", _FakeRunner(cluster=deps.registry.get("c1")))
    runner_holder["c1"].responses = [(0, "", "")]
    status, body = _call("GET", f"/clusters/c1{suffix}", deps)
    assert status == 200 and body == {"rows": []}
    assert runner_holder["c1"].calls[-1][:3] == ["sacctmgr", "show", entity]


# ----------------------------------------------------------------------
# Destructive routes — every verb
# ----------------------------------------------------------------------


def _prime(make_deps, runner_holder, *, count: int = 1):
    deps = make_deps()
    runner_holder.setdefault("c1", _FakeRunner(cluster=deps.registry.get("c1")))
    runner_holder["c1"].responses = [(0, "", "")] * count
    return deps


def test_job_hold_release_requeue(make_deps, runner_holder):
    deps = _prime(make_deps, runner_holder, count=3)
    _call("POST", "/clusters/c1/jobs/7/hold",    deps, body={})
    _call("POST", "/clusters/c1/jobs/7/release", deps, body={})
    _call("POST", "/clusters/c1/jobs/7/requeue", deps, body={})
    assert runner_holder["c1"].calls == [
        ["scontrol", "hold", "7"],
        ["scontrol", "release", "7"],
        ["scontrol", "requeue", "7"],
    ]


def test_jobs_update(make_deps, runner_holder):
    deps = _prime(make_deps, runner_holder)
    _call("PATCH", "/clusters/c1/jobs/7", deps, body={"TimeLimit": "01:00:00"})
    assert runner_holder["c1"].calls == [["scontrol", "update", "JobId=7", "TimeLimit=01:00:00"]]


def test_partition_create_requires_name(make_deps):
    status, body = _call("POST", "/clusters/c1/partitions", make_deps(), body={})
    assert status == 400 and "name required" in body["error"]


def test_accounts_create_requires_name(make_deps):
    status, body = _call("POST", "/clusters/c1/accounts", make_deps(), body={})
    assert status == 400


def test_users_create_with_account(make_deps, runner_holder):
    deps = _prime(make_deps, runner_holder)
    _call("POST", "/clusters/c1/users", deps,
          body={"name": "eve", "account": "sci", "AdminLevel": "Operator"})
    assert runner_holder["c1"].calls == [
        ["sacctmgr", "-i", "add", "user", "eve", "account=sci", "AdminLevel=Operator"],
    ]


def test_users_create_requires_name(make_deps):
    status, body = _call("POST", "/clusters/c1/users", make_deps(), body={})
    assert status == 400


def test_users_modify_and_delete(make_deps, runner_holder):
    deps = _prime(make_deps, runner_holder, count=2)
    _call("PATCH", "/clusters/c1/users/eve", deps, body={"DefaultAccount": "sci"})
    _call("DELETE", "/clusters/c1/users/eve", deps)
    assert runner_holder["c1"].calls == [
        ["sacctmgr", "-i", "modify", "user", "name=eve", "set", "DefaultAccount=sci"],
        ["sacctmgr", "-i", "delete", "user", "name=eve"],
    ]


def test_qos_create_requires_name_and_lifecycle(make_deps, runner_holder):
    status, _ = _call("POST", "/clusters/c1/qos", make_deps(), body={})
    assert status == 400

    deps = _prime(make_deps, runner_holder, count=3)
    _call("POST",   "/clusters/c1/qos",        deps, body={"name": "high", "Priority": "100"})
    _call("PATCH",  "/clusters/c1/qos/high",   deps, body={"Priority": "200"})
    _call("DELETE", "/clusters/c1/qos/high",   deps)
    assert runner_holder["c1"].calls == [
        ["sacctmgr", "-i", "add", "qos", "high", "Priority=100"],
        ["sacctmgr", "-i", "modify", "qos", "name=high", "set", "Priority=200"],
        ["sacctmgr", "-i", "delete", "qos", "name=high"],
    ]


def test_accounts_modify_and_delete(make_deps, runner_holder):
    deps = _prime(make_deps, runner_holder, count=2)
    _call("PATCH", "/clusters/c1/accounts/sci", deps, body={"Description": "science"})
    _call("DELETE", "/clusters/c1/accounts/sci", deps)
    assert runner_holder["c1"].calls == [
        ["sacctmgr", "-i", "modify", "account", "name=sci", "set", "Description=science"],
        ["sacctmgr", "-i", "delete", "account", "name=sci"],
    ]


def test_reservations_full_lifecycle(make_deps, runner_holder):
    deps = _prime(make_deps, runner_holder, count=3)
    _call("POST", "/clusters/c1/reservations", deps,
          body={"ReservationName": "r1", "StartTime": "now", "Duration": "01:00:00"})
    _call("PATCH", "/clusters/c1/reservations/r1", deps, body={"EndTime": "2026-05-26"})
    _call("DELETE", "/clusters/c1/reservations/r1", deps)
    assert runner_holder["c1"].calls == [
        ["scontrol", "create", "reservation", "Duration=01:00:00",
         "ReservationName=r1", "StartTime=now"],
        ["scontrol", "update", "ReservationName=r1", "EndTime=2026-05-26"],
        ["scontrol", "delete", "ReservationName=r1"],
    ]


def test_reconfigure(make_deps, runner_holder):
    deps = _prime(make_deps, runner_holder)
    _call("POST", "/clusters/c1/reconfigure", deps, body={})
    assert runner_holder["c1"].calls == [["scontrol", "reconfigure"]]


def test_destructive_route_surfaces_command_error(make_deps, runner_holder):
    deps = make_deps()
    runner_holder.setdefault("c1", _FakeRunner(cluster=deps.registry.get("c1")))
    runner_holder["c1"].responses = [(1, "", "scancel: invalid job id")]
    status, body = _call("POST", "/clusters/c1/jobs/garbage/cancel", deps, body={})
    assert status == 502 and "invalid job id" in body["stderr"]


def test_destructive_route_surfaces_validation_error(make_deps):
    # scontrol_update_node raises ValueError if DRAIN without reason
    status, body = _call("POST", "/clusters/c1/nodes/n1/state", make_deps(),
                         body={"state": "DRAIN"})
    assert status == 400 and "non-empty reason" in body["error"]


# ----------------------------------------------------------------------
# /audit
# ----------------------------------------------------------------------


def test_audit_empty_when_logger_is_null(make_deps):
    status, body = _call("GET", "/audit", make_deps())
    assert status == 200 and body == {"records": []}


def test_audit_returns_records_when_jsonl_logger(tmp_path, make_deps):
    audit_path = tmp_path / "audit.jsonl"
    logger = JsonlAuditLogger(audit_path)
    deps = make_deps(audit=logger)
    # Drive an audited read-only call to populate the log.
    deps.registry.add(Cluster(name="c2", host="h", user="u", key_path="/k"))
    _call("GET", "/audit", deps)  # initially empty
    # synthesize a record by hitting healthz? healthz isn't audited.
    # Use a read route on a fake runner instead.
    from slurmlib.audit import AuditRecord
    logger.write(AuditRecord(
        record_id="r1", timestamp=0.0, cluster="c1",
        command=["sinfo", "--json"], destructive=False,
        phase="post", actor="dashboard", returncode=0, duration_s=0.01,
    ))
    status, body = _call("GET", "/audit", deps)
    assert status == 200
    assert len(body["records"]) == 1
    assert body["records"][0]["cluster"] == "c1"


# ----------------------------------------------------------------------
# parse_request helper
# ----------------------------------------------------------------------


def test_parse_request_extracts_path_and_query():
    path, q = parse_request("/clusters/prod/accounting?starttime=2026-01-01&users=alice")
    assert path == "/clusters/prod/accounting"
    assert q == {"starttime": "2026-01-01", "users": "alice"}


def test_parse_request_handles_no_query():
    path, q = parse_request("/healthz")
    assert path == "/healthz" and q == {}
