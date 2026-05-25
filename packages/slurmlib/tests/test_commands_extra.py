"""Extra command-shape coverage: the wrappers test_commands.py didn't
exercise, plus sacctmgr_show's parsable2 pipeline."""
from __future__ import annotations

import json
import pytest

from slurmlib.commands import SlurmClient, all_destructive, is_destructive
from slurmlib.connection import Cluster, _FakeRunner


@pytest.fixture
def runner():
    return _FakeRunner(cluster=Cluster(name="t", host="h", user="u", key_path="/k"))


@pytest.fixture
def client(runner):
    return SlurmClient(runner)


# -------- All the read-only wrappers we hadn't hit --------


def test_scontrol_show_job_with_id(runner, client):
    runner.responses = [(0, "{}", "")]
    client.scontrol_show_job("100")
    assert runner.calls == [["scontrol", "show", "job", "100", "--json"]]


def test_scontrol_show_reservation(runner, client):
    runner.responses = [(0, "{}", "")]
    client.scontrol_show_reservation("maint")
    assert runner.calls == [["scontrol", "show", "reservation", "maint", "--json"]]


def test_scontrol_show_config(runner, client):
    runner.responses = [(0, "{}", "")]
    client.scontrol_show_config()
    assert runner.calls == [["scontrol", "show", "config", "--json"]]


def test_sshare_sprio_sstat(runner, client):
    runner.responses = [(0, "{}", "")] * 3
    client.sshare(); client.sprio(); client.sstat("123")
    assert runner.calls == [
        ["sshare", "--json"],
        ["sprio", "--json"],
        ["sstat", "--json", "-j", "123"],
    ]


def test_sacct_with_endtime_accounts_states(runner, client):
    runner.responses = [(0, "{}", "")]
    client.sacct(endtime="2026-05-25", accounts="sci", states="CD")
    assert runner.calls == [["sacct", "--json", "--endtime", "2026-05-25",
                             "--accounts", "sci", "--state", "CD"]]


def test_sacctmgr_show_passes_format_and_filters(runner, client):
    raw = "alice|main|admin|\n"
    runner.responses = [(0, raw, "")]
    rows = client.sacctmgr_show("user", where={"DefaultAccount": "main"})
    # Format list is comma-joined and a `where` clause is appended.
    assert runner.calls[-1] == [
        "sacctmgr", "show", "user", "--parsable2", "--noheader",
        "Format=User,DefaultAccount,Admin",
        "where", "DefaultAccount=main",
    ]
    assert rows == [{"User": "alice", "DefaultAccount": "main", "Admin": "admin"}]


def test_sacctmgr_show_rejects_unknown_entity(client):
    with pytest.raises(ValueError, match="unknown sacctmgr entity"):
        client.sacctmgr_show("garbage")


def test_sreport_uses_parsable2(runner, client):
    runner.responses = [(0, "report-body", "")]
    out = client.sreport(["cluster", "utilization"])
    assert runner.calls == [["sreport", "--parsable2", "cluster", "utilization"]]
    assert out == "report-body"


# -------- Destructive wrappers we hadn't hit --------


def test_scontrol_requeue(runner, client):
    client.scontrol_requeue("99")
    assert runner.calls == [["scontrol", "requeue", "99"]]


def test_reservation_lifecycle(runner, client):
    client.scontrol_create_reservation(ReservationName="r", StartTime="now", Duration="01:00:00", Users="root")
    client.scontrol_update_reservation("r", EndTime="2026-05-26")
    client.scontrol_delete_reservation("r")
    assert runner.calls == [
        ["scontrol", "create", "reservation",
         "Duration=01:00:00", "ReservationName=r", "StartTime=now", "Users=root"],
        ["scontrol", "update", "ReservationName=r", "EndTime=2026-05-26"],
        ["scontrol", "delete", "ReservationName=r"],
    ]


def test_user_qos_lifecycle(runner, client):
    client.sacctmgr_add_user("eve", account="sci", AdminLevel="Operator")
    client.sacctmgr_modify_user("eve", {"DefaultAccount": "sci"})
    client.sacctmgr_delete_user("eve")
    client.sacctmgr_add_qos("high", Priority="100")
    client.sacctmgr_modify_qos("high", {"Priority": "200"})
    client.sacctmgr_delete_qos("high")
    assert runner.calls == [
        ["sacctmgr", "-i", "add", "user", "eve", "account=sci", "AdminLevel=Operator"],
        ["sacctmgr", "-i", "modify", "user", "name=eve", "set", "DefaultAccount=sci"],
        ["sacctmgr", "-i", "delete", "user", "name=eve"],
        ["sacctmgr", "-i", "add", "qos", "high", "Priority=100"],
        ["sacctmgr", "-i", "modify", "qos", "name=high", "set", "Priority=200"],
        ["sacctmgr", "-i", "delete", "qos", "name=high"],
    ]


def test_scontrol_update_node_idle_accepts_no_reason(runner, client):
    """Reason is only mandatory for DOWN/DRAIN — IDLE/RESUME etc don't need it."""
    client.scontrol_update_node("node01", "IDLE")
    assert runner.calls == [["scontrol", "update", "NodeName=node01", "State=IDLE"]]


def test_scontrol_update_node_lowercase_state_normalized(runner, client):
    client.scontrol_update_node("node01", "down", reason="oops")
    assert runner.calls == [["scontrol", "update", "NodeName=node01",
                             "State=DOWN", "Reason=oops"]]


# -------- destructive registry helpers --------


def test_is_destructive_and_all_destructive():
    assert is_destructive("jobs_cancel") is True
    assert is_destructive("nodes_list") is False
    all_d = list(all_destructive())
    assert "cluster_reconfigure" in all_d
    assert "nodes_list" not in all_d
    # Sorted for stable output.
    assert all_d == sorted(all_d)


# -------- empty-stdout JSON path returns {} rather than blowing up --------


def test_run_json_handles_empty_stdout(runner, client):
    runner.responses = [(0, "   ", "")]
    assert client.sinfo() == {}


# -------- CommandError carries the result for the caller --------


def test_command_error_carries_result(runner, client):
    runner.responses = [(2, "", "sacctmgr: cannot connect")]
    import pytest as _pt
    with _pt.raises(Exception) as exc_info:
        client.scontrol_show_config()
    assert exc_info.value.result.returncode == 2
    assert "cannot connect" in str(exc_info.value)
