"""Coverage for connection.py — Cluster (de)serialization, registry edge
cases, LocalRunner against a real subprocess, and SSHRunner argv-quoting
behaviour through paramiko stubs."""
from __future__ import annotations

import sys
import types

import pytest

from slurmlib.connection import (
    Cluster, ClusterRegistry, CommandResult, LocalRunner, SSHRunner,
    _FakeRunner,
)


# -------- Cluster (de)serialization --------


def test_cluster_to_and_from_json_round_trip():
    c = Cluster(name="x", host="h", user="u", key_path="/k", port=2222, jump_host="b@bastion:22")
    raw = c.to_json()
    assert raw == {"name": "x", "host": "h", "user": "u", "key_path": "/k",
                   "port": 2222, "jump_host": "b@bastion:22"}
    restored = Cluster.from_json(raw)
    assert restored == c


def test_cluster_from_json_applies_default_port():
    c = Cluster.from_json({"name": "x", "host": "h", "user": "u", "key_path": "/k"})
    assert c.port == 22
    assert c.jump_host is None


# -------- ClusterRegistry edge cases --------


def test_get_unknown_cluster_raises(tmp_path):
    reg = ClusterRegistry(tmp_path / "hosts.json")
    with pytest.raises(KeyError, match="no cluster registered"):
        reg.get("nope")


def test_remove_unknown_is_a_noop(tmp_path):
    reg = ClusterRegistry(tmp_path / "hosts.json")
    reg.add(Cluster(name="prod", host="h", user="u", key_path="/k"))
    reg.remove("missing")
    assert [c.name for c in reg.list()] == ["prod"]


def test_list_when_file_missing_returns_empty(tmp_path):
    reg = ClusterRegistry(tmp_path / "absent.json")
    assert reg.list() == []


def test_save_uses_atomic_rename(tmp_path):
    """The two-step rename means we never leave a half-written file
    behind even if the writer crashes. Verify the tmp file isn't left
    around after a normal save."""
    reg = ClusterRegistry(tmp_path / "hosts.json")
    reg.add(Cluster(name="prod", host="h", user="u", key_path="/k"))
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


# -------- LocalRunner exercises a real subprocess --------


def test_local_runner_runs_real_subprocess():
    runner = LocalRunner(cluster_name="here")
    # `printf` is in coreutils on every linux box; use sys.executable
    # for portability across hosts though.
    result = runner.run([sys.executable, "-c", "print('hi')"])
    assert isinstance(result, CommandResult)
    assert result.ok and result.returncode == 0
    assert result.stdout.strip() == "hi"
    assert result.cluster == "here"


def test_local_runner_captures_stderr_and_nonzero_exit():
    runner = LocalRunner()
    result = runner.run([sys.executable, "-c", "import sys; sys.stderr.write('bad\\n'); sys.exit(7)"])
    assert result.returncode == 7
    assert "bad" in result.stderr


def test_local_runner_handles_missing_binary():
    runner = LocalRunner()
    result = runner.run(["definitely-not-a-real-binary-12345"])
    assert result.returncode == 127
    assert "No such file" in result.stderr or "not found" in result.stderr.lower()


def test_local_runner_handles_timeout():
    runner = LocalRunner()
    result = runner.run(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout=1,
    )
    assert result.returncode == 124
    assert "[timeout]" in result.stderr


def test_local_runner_extra_env_merges_with_os_env():
    runner = LocalRunner(env={"SLURM_MGR_TEST_VAR": "yes"})
    result = runner.run([sys.executable, "-c", "import os; print(os.environ.get('SLURM_MGR_TEST_VAR'))"])
    assert result.stdout.strip() == "yes"


# -------- CommandResult helpers --------


def test_command_result_ok_property_and_json():
    r = CommandResult(argv=["sinfo"], stdout="", stderr="", returncode=0, duration_s=0.123456, cluster="t")
    assert r.ok is True
    assert r.to_json()["duration_s"] == 0.1235      # rounded to 4dp
    assert r.to_json()["argv"] == ["sinfo"]


def test_command_result_ok_false_when_nonzero():
    r = CommandResult(argv=[], stdout="", stderr="", returncode=1, duration_s=0.0)
    assert r.ok is False


# -------- _FakeRunner returns empty defaults when responses are exhausted --------


def test_fake_runner_default_response_is_success():
    runner = _FakeRunner(cluster=Cluster(name="t", host="h", user="u", key_path="/k"))
    result = runner.run(["whoami"])
    assert result.ok and result.stdout == ""
    assert runner.calls == [["whoami"]]


# -------- SSHRunner: minimal exercise via paramiko stubs --------


def test_ssh_runner_requires_paramiko(monkeypatch):
    """If paramiko is missing, SSHRunner construction explains the dep
    rather than blowing up with an opaque NameError. We can't easily
    test the import-failure branch (paramiko is installed), but we can
    at least assert the runtime error path stays catchable."""
    cluster = Cluster(name="t", host="h", user="u", key_path="/k")
    # Force the module's `paramiko` symbol to None to hit the guard.
    import slurmlib.connection as conn_mod
    monkeypatch.setattr(conn_mod, "paramiko", None)
    with pytest.raises(RuntimeError, match="paramiko is required"):
        SSHRunner(cluster)


def test_ssh_runner_run_quotes_argv_and_returns_result(monkeypatch):
    """Test the full run() path without a real network connection by
    swapping in a fake paramiko.SSHClient. Catches argv-quoting and
    return-code plumbing in one shot."""
    import slurmlib.connection as conn_mod

    received: dict = {}

    class FakeChannel:
        def recv_exit_status(self): return 0

    class FakeStdout:
        channel = FakeChannel()
        def read(self): return b'{"ok":true}'

    class FakeStderr:
        def read(self): return b""

    class FakeStdin:
        def close(self): pass

    class FakeSSHClient:
        def set_missing_host_key_policy(self, _): pass
        def connect(self, **kwargs): received["connect"] = kwargs
        def exec_command(self, cmd, timeout=60):
            received["cmd"] = cmd
            received["timeout"] = timeout
            return FakeStdin(), FakeStdout(), FakeStderr()
        def close(self): pass

    fake_paramiko = types.SimpleNamespace(
        SSHClient=FakeSSHClient,
        AutoAddPolicy=lambda: None,
    )
    monkeypatch.setattr(conn_mod, "paramiko", fake_paramiko)

    runner = SSHRunner(Cluster(name="t", host="h", user="u", key_path="/k"))
    result = runner.run(["scontrol", "show", "node", "name with space"])

    assert result.ok and result.stdout == '{"ok":true}'
    # shlex.quote should single-quote the space-containing arg
    assert received["cmd"] == "scontrol show node 'name with space'"
    assert received["connect"]["hostname"] == "h"
    assert received["connect"]["look_for_keys"] is False
