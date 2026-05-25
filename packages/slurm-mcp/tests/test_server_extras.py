"""Cover slurm_mcp.server bits not hit by the envelope tests:
``_make_client`` modes, ``main`` arg-parsing, and the dispatch path
when an unexpected exception leaks out of dispatch_tool."""
from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from slurmlib import ClusterRegistry, Cluster
from slurm_mcp.server import _make_client, dispatch, main, serve


# ---- _make_client modes -----------------------------------------------


def test_make_client_local_returns_localrunner_backed_client():
    client = _make_client(cluster_name=None, use_local=True)
    assert client is not None
    assert client.runner.cluster.name == "local"


def test_make_client_with_named_cluster(tmp_path, monkeypatch):
    reg_path = tmp_path / "hosts.json"
    reg = ClusterRegistry(reg_path)
    reg.add(Cluster(name="prod", host="h", user="u", key_path="/k"))
    monkeypatch.setenv("SLURM_MGR_HOSTS", str(reg_path))

    # Ensure paramiko init doesn't actually connect (we never call .run)
    client = _make_client(cluster_name="prod", use_local=False)
    assert client is not None
    assert client.runner.cluster.host == "h"


def test_make_client_neither_returns_none():
    assert _make_client(None, use_local=False) is None


# ---- dispatch internal-error wrapping ---------------------------------


def test_dispatch_returns_internal_error_via_serve_when_handler_blows_up(monkeypatch):
    """If dispatch_tool somehow leaks an exception (it shouldn't, but
    we want belt + suspenders), serve() catches it and returns a -32603
    internal-error envelope instead of crashing the loop."""
    import slurm_mcp.server as srv_mod

    def boom(*_a, **_kw): raise RuntimeError("dispatch boom")

    monkeypatch.setattr(srv_mod, "dispatch", boom)
    stdin = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "x"}) + "\n")
    stdout = io.StringIO()
    serve(client=None, stdin=stdin, stdout=stdout)
    resp = json.loads(stdout.getvalue().strip())
    assert resp["error"]["code"] == -32603
    assert "dispatch boom" in resp["error"]["message"]


def test_dispatch_tool_call_without_client_returns_clear_message():
    resp = dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "nodes_list", "arguments": {}}},
        client=None,
    )
    text = resp["result"]["content"][0]["text"]
    assert resp["result"]["isError"] is True
    assert "no cluster bound" in text


def test_serve_skips_blank_lines():
    stdin = io.StringIO("\n\n" + json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    ) + "\n\n")
    stdout = io.StringIO()
    serve(client=None, stdin=stdin, stdout=stdout)
    lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == 1


# ---- main() argument-parsing ------------------------------------------


def test_main_requires_cluster_or_local(capsys):
    with patch("sys.argv", ["slurm-mcp"]):
        rc = main()
    assert rc == 2
    err = capsys.readouterr().err
    assert "--cluster" in err and "--local" in err


def test_main_with_unknown_cluster_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SLURM_MGR_HOSTS", str(tmp_path / "absent.json"))
    with patch("sys.argv", ["slurm-mcp", "--cluster", "nope"]):
        rc = main()
    assert rc == 2
    assert "no cluster registered" in capsys.readouterr().err


def test_main_local_runs_serve_loop(monkeypatch):
    """With --local and an empty stdin, the serve() loop exits cleanly
    with rc=0. Use a no-op stdin to drive the loop without actually
    reading from the controlling terminal."""
    import slurm_mcp.server as srv_mod

    called: dict = {}

    def fake_serve(client):
        called["client"] = client
        return 0

    monkeypatch.setattr(srv_mod, "serve", fake_serve)
    with patch("sys.argv", ["slurm-mcp", "--local"]):
        rc = main()
    assert rc == 0
    assert called["client"] is not None


# ---- tools_descriptor / destructive_names already tested in test_tools --


def test_dispatch_notification_returns_none():
    assert dispatch({"jsonrpc": "2.0", "method": "notifications/cancelled"}, client=None) is None
