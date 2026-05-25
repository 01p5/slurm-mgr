"""Wire-shape tests for the MCP stdio server.

We don't spawn a subprocess — we call ``dispatch`` and ``serve``
directly with synthetic input. The point is to catch wire-shape
regressions that would make Olympus's MCPClient fail at the handshake.
"""
from __future__ import annotations

import io
import json

from slurmlib import SlurmClient
from slurmlib.connection import Cluster, _FakeRunner
from slurm_mcp.server import PROTOCOL_VERSION, dispatch, serve
from slurm_mcp.tools import destructive_names, tools_descriptor


def _request(method: str, msg_id: int = 1, **params) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}


def test_initialize_returns_supported_protocol():
    resp = dispatch(_request("initialize"), client=None)
    assert resp["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert "tools" in resp["result"]["capabilities"]
    assert resp["result"]["serverInfo"]["name"] == "slurm-mcp"


def test_notification_initialized_returns_none():
    """notifications/initialized has no id → no response per spec."""
    assert dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}, client=None) is None


def test_tools_list_includes_known_tools():
    resp = dispatch(_request("tools/list"), client=None)
    names = {t["name"] for t in resp["result"]["tools"]}
    assert "nodes_list" in names
    assert "jobs_cancel" in names
    assert "cluster_reconfigure" in names


def test_tools_list_marks_destructive_with_annotation():
    resp = dispatch(_request("tools/list"), client=None)
    by_name = {t["name"]: t for t in resp["result"]["tools"]}
    assert by_name["jobs_cancel"]["annotations"]["destructive"] is True
    assert "annotations" not in by_name["nodes_list"]


def test_unknown_method_returns_jsonrpc_error():
    resp = dispatch(_request("garbage"), client=None)
    assert resp["error"]["code"] == -32601


def test_tools_call_without_client_is_an_error():
    resp = dispatch(_request("tools/call", name="nodes_list", arguments={}), client=None)
    assert resp["result"]["isError"] is True


def test_tools_call_dispatches_to_handler():
    runner = _FakeRunner(cluster=Cluster(
        name="t", host="h", user="u", key_path="/k", port=22,
    ), responses=[(0, '{"nodes":[]}', "")])
    client = SlurmClient(runner)
    resp = dispatch(_request("tools/call", name="nodes_list", arguments={}), client=client)
    assert "isError" not in resp["result"]
    assert runner.calls == [["sinfo", "--json"]]


def test_serve_loop_handles_full_handshake():
    """End-to-end through serve(): initialize → notifications/initialized → tools/list."""
    input_lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]
    stdin = io.StringIO("\n".join(input_lines) + "\n")
    stdout = io.StringIO()
    serve(client=None, stdin=stdin, stdout=stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    # initialize + tools/list — notification produces no response
    assert len(responses) == 2
    assert responses[0]["id"] == 1
    assert responses[0]["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert responses[1]["id"] == 2
    assert {"name": "nodes_list"} in [{"name": t["name"]} for t in responses[1]["result"]["tools"]]


def test_serve_loop_returns_parse_error_for_garbage_lines():
    stdin = io.StringIO("not json\n")
    stdout = io.StringIO()
    serve(client=None, stdin=stdin, stdout=stdout)
    resp = json.loads(stdout.getvalue().strip())
    assert resp["error"]["code"] == -32700


def test_destructive_names_match_dashboard_set():
    """slurm-mcp's advertised destructive list and slurmlib's
    DESTRUCTIVE_TOOLS must agree. If they drift, the recommended
    MCPServerConfig in our README is wrong."""
    from slurmlib.commands import DESTRUCTIVE_TOOLS
    assert set(destructive_names()) == set(DESTRUCTIVE_TOOLS)


def test_every_destructive_tool_has_handler():
    """Catalog and dispatch table must agree."""
    from slurm_mcp.tools import HANDLERS
    for t in tools_descriptor():
        assert t["name"] in HANDLERS, f"no handler for {t['name']}"
