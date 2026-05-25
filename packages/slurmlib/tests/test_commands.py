"""Smoke tests for the slurmlib command wrappers.

We don't run real Slurm here. Instead we use ``_FakeRunner`` to capture
the argv we'd send to the cluster, plus stub canned stdout for the JSON
parse paths. This catches the kind of mistake that's hardest to find
later: ``scontrol delete partition foo`` instead of ``scontrol delete
PartitionName=foo``.
"""
from __future__ import annotations

import json
import pytest

from slurmlib.commands import (
    DESTRUCTIVE_TOOLS, CommandError, SlurmClient, parse_parsable2, _kv,
)
from slurmlib.connection import Cluster, _FakeRunner


@pytest.fixture
def runner():
    return _FakeRunner(cluster=Cluster(
        name="t", host="h", user="u", key_path="/k", port=22,
    ))


@pytest.fixture
def client(runner):
    return SlurmClient(runner)


# -------- read-only argv shape --------


def test_sinfo_argv(runner, client):
    runner.responses = [(0, '{"nodes":[]}', "")]
    client.sinfo()
    assert runner.calls == [["sinfo", "--json"]]


def test_squeue_argv(runner, client):
    runner.responses = [(0, '{"jobs":[]}', "")]
    client.squeue()
    assert runner.calls == [["squeue", "--json"]]


def test_sacct_filters(runner, client):
    runner.responses = [(0, '{"jobs":[]}', "")]
    client.sacct(starttime="2026-05-01", users="alice")
    assert runner.calls == [["sacct", "--json", "--starttime", "2026-05-01", "--user", "alice"]]


def test_scontrol_show_node_with_name(runner, client):
    runner.responses = [(0, '{"nodes":[]}', "")]
    client.scontrol_show_node("node01")
    assert runner.calls == [["scontrol", "show", "node", "node01", "--json"]]


def test_scontrol_show_partition_all(runner, client):
    runner.responses = [(0, '{"partitions":[]}', "")]
    client.scontrol_show_partition()
    assert runner.calls == [["scontrol", "show", "partition", "--json"]]


def test_sdiag(runner, client):
    runner.responses = [(0, "{}", "")]
    client.sdiag()
    assert runner.calls == [["sdiag", "--json"]]


# -------- destructive argv shape --------


def test_scancel_basic(runner, client):
    client.scancel("42")
    assert runner.calls == [["scancel", "42"]]


def test_scancel_with_signal(runner, client):
    client.scancel("42", signal="USR1")
    assert runner.calls == [["scancel", "--signal", "USR1", "42"]]


def test_scontrol_hold_release(runner, client):
    client.scontrol_hold("42")
    client.scontrol_release("42")
    assert runner.calls == [
        ["scontrol", "hold", "42"],
        ["scontrol", "release", "42"],
    ]


def test_scontrol_update_job(runner, client):
    client.scontrol_update_job("42", TimeLimit="01:00:00", Partition="debug")
    # _kv sorts by key for stable argv
    assert runner.calls == [["scontrol", "update", "JobId=42",
                             "Partition=debug", "TimeLimit=01:00:00"]]


def test_scontrol_update_node_requires_reason_for_drain(client):
    with pytest.raises(ValueError, match="requires a non-empty reason"):
        client.scontrol_update_node("node01", "DRAIN")


def test_scontrol_update_node_with_reason(runner, client):
    client.scontrol_update_node("node01", "drain", reason="oom")
    assert runner.calls == [["scontrol", "update", "NodeName=node01",
                             "State=DRAIN", "Reason=oom"]]


def test_partition_lifecycle(runner, client):
    client.scontrol_create_partition("debug", Nodes="node[1-4]", MaxTime="01:00:00")
    client.scontrol_update_partition("debug", State="DOWN")
    client.scontrol_delete_partition("debug")
    assert runner.calls == [
        ["scontrol", "create", "PartitionName=debug",
         "MaxTime=01:00:00", "Nodes=node[1-4]"],
        ["scontrol", "update", "PartitionName=debug", "State=DOWN"],
        ["scontrol", "delete", "PartitionName=debug"],
    ]


def test_sacctmgr_interactive_flag(runner, client):
    """Without -i, sacctmgr drops into a confirmation prompt that
    deadlocks SSH exec. Make sure every destructive sacctmgr call
    includes -i."""
    client.sacctmgr_add_account("alpha", Description="x")
    client.sacctmgr_modify_account("alpha", {"Description": "y"})
    client.sacctmgr_delete_account("alpha")
    client.sacctmgr_add_user("bob", account="alpha")
    client.sacctmgr_delete_user("bob")
    client.sacctmgr_add_qos("normal", Priority="100")

    for call in runner.calls:
        assert "-i" in call, f"missing -i: {call}"


def test_sacctmgr_modify_uses_set_keyword(runner, client):
    client.sacctmgr_modify_user("bob", {"DefaultAccount": "alpha"})
    assert runner.calls == [["sacctmgr", "-i", "modify", "user",
                             "name=bob", "set", "DefaultAccount=alpha"]]


def test_reconfigure(runner, client):
    client.scontrol_reconfigure()
    assert runner.calls == [["scontrol", "reconfigure"]]


# -------- error path --------


def test_nonzero_raises_command_error(runner, client):
    runner.responses = [(1, "", "sinfo: error: Unable to contact slurmctld")]
    with pytest.raises(CommandError, match="sinfo"):
        client.sinfo()


def test_invalid_json_raises(runner, client):
    runner.responses = [(0, "not json", "")]
    with pytest.raises(CommandError, match="unparseable JSON"):
        client.sinfo()


# -------- helpers --------


def test_kv_sorts_and_drops_none():
    assert _kv(b=2, a=1, c=None) == ["a=1", "b=2"]


def test_parse_parsable2_basic():
    raw = "alice|main|admin|\nbob|sci|none|\n"
    rows = parse_parsable2(raw, ["User", "DefaultAccount", "Admin"])
    assert rows == [
        {"User": "alice", "DefaultAccount": "main", "Admin": "admin"},
        {"User": "bob",   "DefaultAccount": "sci",  "Admin": "none"},
    ]


def test_parse_parsable2_ignores_blank_lines():
    rows = parse_parsable2("\nalice|m|\n\n", ["User", "DefaultAccount"])
    assert rows == [{"User": "alice", "DefaultAccount": "m"}]


# -------- destructive registry consistency --------


def test_destructive_set_covers_every_destructive_tool():
    """The MCP server's destructive set must match the dashboard's.
    If you add a destructive verb, both surfaces need to know."""
    expected = {
        "jobs_cancel", "jobs_hold", "jobs_release", "jobs_requeue", "jobs_update",
        "nodes_set_state",
        "partitions_create", "partitions_update", "partitions_delete",
        "reservations_create", "reservations_update", "reservations_delete",
        "accounts_add", "accounts_modify", "accounts_delete",
        "users_add", "users_modify", "users_delete",
        "qos_add", "qos_modify", "qos_delete",
        "cluster_reconfigure",
    }
    assert set(DESTRUCTIVE_TOOLS) == expected


# -------- sinfo JSON pass-through --------


def test_sinfo_returns_parsed_dict(runner, client):
    payload = {"meta": {"slurm": {"version": {"major": "23"}}}, "nodes": [{"name": "n1"}]}
    runner.responses = [(0, json.dumps(payload), "")]
    assert client.sinfo() == payload
