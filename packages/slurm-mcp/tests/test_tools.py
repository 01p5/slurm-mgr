"""Per-tool handler tests for slurm-mcp.

Drive every tool through ``dispatch_tool`` against a ``_FakeRunner``.
The point is twofold:

  1. each handler builds the right Slurm argv when called via MCP
     (mirror tests we have for SlurmClient directly, but through the
     MCP envelope);

  2. error paths — missing required args, Slurm rejecting the call,
     unknown tool name — all return the well-formed
     ``{content: [{type: "text", text: ...}], isError: True}`` shape
     Olympus's MCPClient expects."""
from __future__ import annotations

import json

import pytest

from slurmlib import SlurmClient
from slurmlib.connection import Cluster, _FakeRunner

from slurm_mcp.tools import (
    HANDLERS, TOOLS, destructive_names, dispatch_tool, tools_descriptor,
)


@pytest.fixture
def runner():
    return _FakeRunner(cluster=Cluster(name="t", host="h", user="u", key_path="/k"))


@pytest.fixture
def client(runner):
    return SlurmClient(runner)


def _ok(result: dict) -> str:
    """Pull the first text block from an MCP tool result, asserting it's
    not an error."""
    assert "isError" not in result or result["isError"] is False, result
    return result["content"][0]["text"]


def _err(result: dict) -> str:
    assert result.get("isError") is True, result
    return result["content"][0]["text"]


# ----------------------------------------------------------------------
# Dispatcher-level — shape, unknown name, error wrapping
# ----------------------------------------------------------------------


def test_dispatch_unknown_tool_returns_error_shape(client):
    out = dispatch_tool(client, "nope", {})
    assert "unknown tool" in _err(out)


def test_dispatch_handles_command_error_with_stderr(runner, client):
    runner.responses = [(2, "", "sinfo: error: Unable to contact slurmctld")]
    text = _err(dispatch_tool(client, "nodes_list", {}))
    assert "stderr" in text and "slurmctld" in text


def test_dispatch_handles_value_error_from_missing_arg(client):
    text = _err(dispatch_tool(client, "jobs_cancel", {}))
    assert "jobid" in text


def test_dispatch_handles_unexpected_exception(client, monkeypatch):
    """Surface internal errors as MCP error content rather than a
    crashed subprocess (which would deadlock Olympus's transport)."""
    def boom(*_a, **_kw): raise RuntimeError("kaboom")
    monkeypatch.setitem(HANDLERS, "nodes_list", boom)
    text = _err(dispatch_tool(client, "nodes_list", {}))
    assert "RuntimeError" in text and "kaboom" in text


# ----------------------------------------------------------------------
# Read-only tools — verify argv via runner.calls + response passthrough
# ----------------------------------------------------------------------


def test_nodes_list(runner, client):
    runner.responses = [(0, '{"nodes":[{"name":"n1"}]}', "")]
    text = _ok(dispatch_tool(client, "nodes_list", {}))
    assert "n1" in text
    assert runner.calls == [["sinfo", "--json"]]


def test_nodes_describe_all(runner, client):
    runner.responses = [(0, "{}", "")]
    dispatch_tool(client, "nodes_describe", {})
    assert runner.calls == [["scontrol", "show", "node", "--json"]]


def test_nodes_describe_named(runner, client):
    runner.responses = [(0, "{}", "")]
    dispatch_tool(client, "nodes_describe", {"name": "n1"})
    assert runner.calls == [["scontrol", "show", "node", "n1", "--json"]]


def test_jobs_list_and_describe(runner, client):
    runner.responses = [(0, "{}", "")] * 3
    dispatch_tool(client, "jobs_list", {})
    dispatch_tool(client, "jobs_describe", {})
    dispatch_tool(client, "jobs_describe", {"jobid": "42"})
    assert runner.calls == [
        ["squeue", "--json"],
        ["scontrol", "show", "job", "--json"],
        ["scontrol", "show", "job", "42", "--json"],
    ]


def test_partitions_reservations_config_diag(runner, client):
    runner.responses = [(0, "{}", "")] * 4
    dispatch_tool(client, "partitions_list", {})
    dispatch_tool(client, "reservations_list", {})
    dispatch_tool(client, "cluster_config", {})
    dispatch_tool(client, "diagnostics_show", {})
    assert runner.calls == [
        ["scontrol", "show", "partition", "--json"],
        ["scontrol", "show", "reservation", "--json"],
        ["scontrol", "show", "config", "--json"],
        ["sdiag", "--json"],
    ]


def test_fairshare_and_priorities(runner, client):
    runner.responses = [(0, "{}", "")] * 2
    dispatch_tool(client, "fairshare_show", {})
    dispatch_tool(client, "priorities_show", {})
    assert runner.calls == [["sshare", "--json"], ["sprio", "--json"]]


def test_job_stats_requires_jobid(client):
    text = _err(dispatch_tool(client, "job_stats", {}))
    assert "jobid is required" in text


def test_job_stats_routes(runner, client):
    runner.responses = [(0, "{}", "")]
    dispatch_tool(client, "job_stats", {"jobid": "55"})
    assert runner.calls == [["sstat", "--json", "-j", "55"]]


def test_accounts_users_assocs_qos_list(runner, client):
    runner.responses = [(0, "alice|m|admin|\n", "")] * 4
    for name in ("accounts_list", "users_list", "assocs_list", "qos_list"):
        dispatch_tool(client, name, {})
    assert [c[1] for c in runner.calls] == ["show"] * 4
    assert [c[2] for c in runner.calls] == ["account", "user", "assoc", "qos"]


def test_accounting_query_routes_filters(runner, client):
    runner.responses = [(0, "{}", "")]
    dispatch_tool(client, "accounting_query", {
        "starttime": "2026-05-01", "endtime": "2026-05-02",
        "users": "alice", "accounts": "sci", "states": "CD",
    })
    assert runner.calls[-1] == [
        "sacct", "--json",
        "--starttime", "2026-05-01",
        "--endtime", "2026-05-02",
        "--user", "alice",
        "--accounts", "sci",
        "--state", "CD",
    ]


def test_accounting_report_passes_args(runner, client):
    runner.responses = [(0, "report-text", "")]
    text = _ok(dispatch_tool(client, "accounting_report",
                             {"args": ["cluster", "utilization"]}))
    assert text == "report-text"
    assert runner.calls[-1] == ["sreport", "--parsable2", "cluster", "utilization"]


# ----------------------------------------------------------------------
# Destructive tools — argv shape
# ----------------------------------------------------------------------


def test_jobs_cancel_with_signal(runner, client):
    dispatch_tool(client, "jobs_cancel", {"jobid": "7", "signal": "USR1"})
    assert runner.calls == [["scancel", "--signal", "USR1", "7"]]


def test_jobs_lifecycle_hold_release_requeue(runner, client):
    runner.responses = [(0, "", "")] * 3
    for verb in ("jobs_hold", "jobs_release", "jobs_requeue"):
        dispatch_tool(client, verb, {"jobid": "9"})
    assert runner.calls == [
        ["scontrol", "hold", "9"],
        ["scontrol", "release", "9"],
        ["scontrol", "requeue", "9"],
    ]


def test_jobs_update_requires_fields(client):
    text = _err(dispatch_tool(client, "jobs_update", {"jobid": "9"}))
    assert "fields" in text


def test_jobs_update_routes(runner, client):
    dispatch_tool(client, "jobs_update", {"jobid": "9", "fields": {"TimeLimit": "02:00:00"}})
    assert runner.calls == [["scontrol", "update", "JobId=9", "TimeLimit=02:00:00"]]


def test_nodes_set_state(runner, client):
    dispatch_tool(client, "nodes_set_state",
                  {"name": "n1", "state": "DRAIN", "reason": "oom"})
    assert runner.calls == [
        ["scontrol", "update", "NodeName=n1", "State=DRAIN", "Reason=oom"],
    ]


def test_nodes_set_state_validates_reason(client):
    text = _err(dispatch_tool(client, "nodes_set_state",
                              {"name": "n1", "state": "DRAIN"}))
    assert "non-empty reason" in text


def test_partition_lifecycle(runner, client):
    runner.responses = [(0, "", "")] * 3
    dispatch_tool(client, "partitions_create",
                  {"name": "debug", "fields": {"MaxTime": "01:00:00"}})
    dispatch_tool(client, "partitions_update",
                  {"name": "debug", "fields": {"State": "DOWN"}})
    dispatch_tool(client, "partitions_delete", {"name": "debug"})
    assert runner.calls == [
        ["scontrol", "create", "PartitionName=debug", "MaxTime=01:00:00"],
        ["scontrol", "update", "PartitionName=debug", "State=DOWN"],
        ["scontrol", "delete", "PartitionName=debug"],
    ]


def test_reservation_lifecycle(runner, client):
    runner.responses = [(0, "", "")] * 3
    dispatch_tool(client, "reservations_create", {
        "fields": {"ReservationName": "r1", "StartTime": "now",
                   "Duration": "01:00:00", "Users": "root"},
    })
    dispatch_tool(client, "reservations_update", {
        "name": "r1", "fields": {"EndTime": "2026-05-26"},
    })
    dispatch_tool(client, "reservations_delete", {"name": "r1"})
    assert runner.calls == [
        ["scontrol", "create", "reservation",
         "Duration=01:00:00", "ReservationName=r1",
         "StartTime=now", "Users=root"],
        ["scontrol", "update", "ReservationName=r1", "EndTime=2026-05-26"],
        ["scontrol", "delete", "ReservationName=r1"],
    ]


def test_accounts_lifecycle(runner, client):
    runner.responses = [(0, "", "")] * 3
    dispatch_tool(client, "accounts_add",
                  {"name": "sci", "fields": {"Description": "science"}})
    dispatch_tool(client, "accounts_modify",
                  {"name": "sci", "set": {"Description": "new"}})
    dispatch_tool(client, "accounts_delete", {"name": "sci"})
    assert runner.calls == [
        ["sacctmgr", "-i", "add", "account", "sci", "Description=science"],
        ["sacctmgr", "-i", "modify", "account", "name=sci", "set", "Description=new"],
        ["sacctmgr", "-i", "delete", "account", "name=sci"],
    ]


def test_accounts_modify_requires_set(client):
    text = _err(dispatch_tool(client, "accounts_modify", {"name": "sci"}))
    assert "set" in text.lower()


def test_users_lifecycle(runner, client):
    runner.responses = [(0, "", "")] * 3
    dispatch_tool(client, "users_add",
                  {"name": "eve", "account": "sci", "fields": {"AdminLevel": "Operator"}})
    dispatch_tool(client, "users_modify",
                  {"name": "eve", "set": {"DefaultAccount": "sci"}})
    dispatch_tool(client, "users_delete", {"name": "eve"})
    assert runner.calls == [
        ["sacctmgr", "-i", "add", "user", "eve", "account=sci", "AdminLevel=Operator"],
        ["sacctmgr", "-i", "modify", "user", "name=eve", "set", "DefaultAccount=sci"],
        ["sacctmgr", "-i", "delete", "user", "name=eve"],
    ]


def test_users_modify_requires_set(client):
    text = _err(dispatch_tool(client, "users_modify", {"name": "eve"}))
    assert "set" in text.lower()


def test_qos_lifecycle(runner, client):
    runner.responses = [(0, "", "")] * 3
    dispatch_tool(client, "qos_add",    {"name": "high", "fields": {"Priority": "100"}})
    dispatch_tool(client, "qos_modify", {"name": "high", "set": {"Priority": "200"}})
    dispatch_tool(client, "qos_delete", {"name": "high"})
    assert runner.calls == [
        ["sacctmgr", "-i", "add", "qos", "high", "Priority=100"],
        ["sacctmgr", "-i", "modify", "qos", "name=high", "set", "Priority=200"],
        ["sacctmgr", "-i", "delete", "qos", "name=high"],
    ]


def test_qos_modify_requires_set(client):
    text = _err(dispatch_tool(client, "qos_modify", {"name": "high"}))
    assert "set" in text.lower()


def test_cluster_reconfigure(runner, client):
    runner.responses = [(0, "", "")]
    dispatch_tool(client, "cluster_reconfigure", {})
    assert runner.calls == [["scontrol", "reconfigure"]]


# ----------------------------------------------------------------------
# Catalog ↔ handler ↔ destructive list consistency
# ----------------------------------------------------------------------


def test_every_tool_in_catalog_has_handler():
    catalog_names = {t["name"] for t in TOOLS}
    assert catalog_names == set(HANDLERS), \
        f"catalog/handler drift: {catalog_names ^ set(HANDLERS)}"


def test_tools_descriptor_strips_destructive_field_but_keeps_annotation():
    by_name = {t["name"]: t for t in tools_descriptor()}
    assert "destructive" not in by_name["jobs_cancel"]
    assert by_name["jobs_cancel"]["annotations"]["destructive"] is True
    assert "annotations" not in by_name["nodes_list"]


def test_destructive_names_is_sorted_and_complete():
    names = destructive_names()
    assert names == sorted(names)
    # Should match the catalog's destructive flag.
    expected = sorted(t["name"] for t in TOOLS if t.get("destructive"))
    assert names == expected


def test_large_output_is_truncated():
    """Sanity: 100k of stdout becomes ~30k+marker, not pages of garbage
    in the LLM context."""
    runner = _FakeRunner(cluster=Cluster(name="t", host="h", user="u", key_path="/k"))
    big = json.dumps({"x": "a" * 100_000})
    runner.responses = [(0, big, "")]
    client = SlurmClient(runner)
    text = _ok(dispatch_tool(client, "nodes_list", {}))
    assert "[truncated]" in text
    assert len(text) < 32_000
