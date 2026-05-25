"""End-to-end HTTP server tests — spin up build_server on an
ephemeral port and make real requests. Exercises the
BaseHTTPRequestHandler shell (do_GET/do_POST/_read_body/_maybe_serve_static)
which the unit tests on routes.route can't reach."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.client import HTTPConnection
from pathlib import Path

import pytest

from slurmlib import Cluster, ClusterRegistry, NullAuditLogger
from slurm_dashboard.server import build_server


def _start(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture
def live_server(tmp_path):
    registry = ClusterRegistry(tmp_path / "hosts.json")
    registry.add(Cluster(name="c1", host="h", user="u", key_path="/k"))
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><div id=root></div>")
    (static / "app.js").write_text("// fake js")

    server = build_server(
        host="127.0.0.1", port=0, registry=registry,
        audit=NullAuditLogger(), static_dir=static,
    )
    port = server.server_address[1]
    thread = _start(server)
    try:
        # Wait for the server to be ready (it usually is immediately).
        for _ in range(30):
            try:
                c = HTTPConnection("127.0.0.1", port, timeout=1)
                c.request("GET", "/healthz")
                c.getresponse().read()
                c.close()
                break
            except OSError:
                time.sleep(0.05)
        yield port, static
    finally:
        _stop(server, thread)


def _get(port: int, path: str) -> tuple[int, dict | str]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
        body = r.read().decode("utf-8")
        ct = r.headers.get("Content-Type", "")
        if "json" in ct:
            return r.status, json.loads(body)
        return r.status, body


def _post(port: int, path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def _delete(port: int, path: str) -> int:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="DELETE")
    with urllib.request.urlopen(req) as r:
        return r.status


def _options(port: int, path: str) -> tuple[int, dict[str, str]]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="OPTIONS")
    with urllib.request.urlopen(req) as r:
        return r.status, dict(r.headers)


def test_healthz_over_http(live_server):
    port, _ = live_server
    status, body = _get(port, "/healthz")
    assert status == 200 and body["ok"] is True


def test_clusters_endpoint_over_http(live_server):
    port, _ = live_server
    status, body = _get(port, "/clusters")
    assert status == 200 and body["clusters"][0]["name"] == "c1"


def test_post_then_delete_cluster_over_http(live_server):
    port, _ = live_server
    status, body = _post(port, "/clusters", {
        "name": "new", "host": "h", "user": "u", "key_path": "/k",
    })
    assert status == 201 and body["name"] == "new"
    assert _delete(port, "/clusters/new") == 200


def test_options_returns_cors_headers(live_server):
    port, _ = live_server
    status, headers = _options(port, "/clusters")
    assert status == 204
    assert headers.get("Access-Control-Allow-Origin") == "*"
    assert "POST" in headers.get("Access-Control-Allow-Methods", "")


def test_static_index_served_at_root(live_server):
    port, _ = live_server
    status, body = _get(port, "/")
    assert status == 200 and "<!doctype html>" in body.lower()


def test_static_asset_served_with_mime(live_server):
    port, _ = live_server
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/app.js") as r:
        assert r.status == 200
        assert "javascript" in r.headers.get("Content-Type", "").lower()


def test_unknown_get_falls_back_to_spa_index(live_server):
    """The SPA does client-side routing — any non-API GET we don't
    serve as a file should still return index.html for the React
    router to render."""
    port, _ = live_server
    status, body = _get(port, "/some/spa/route")
    assert status == 200 and "<!doctype html>" in body.lower()


def test_path_traversal_attempt_is_blocked(live_server):
    """Trying to read /etc/passwd via the static-fallback path should
    fail safe (we return the SPA index, not the file).

    urllib normalizes "..", so we have to send the raw path via
    HTTPConnection to actually exercise the guard.
    """
    port, _ = live_server
    c = HTTPConnection("127.0.0.1", port, timeout=2)
    c.request("GET", "/../../../etc/passwd")
    resp = c.getresponse()
    body = resp.read().decode("utf-8", errors="replace")
    c.close()
    # Whatever happens, we must not leak /etc/passwd.
    assert "root:" not in body
    assert "x:0:0:" not in body


def test_unknown_api_route_returns_404(live_server):
    port, _ = live_server
    # API routes that 404 should still return JSON, not the SPA.
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/clusters/nope/check")
    assert excinfo.value.code == 404


def test_post_with_empty_body_is_400_for_clusters(live_server):
    port, _ = live_server
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/clusters",
        data=b"",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req)
    assert excinfo.value.code == 400


def test_garbage_json_body_treated_as_empty(live_server):
    """If the body is malformed, _read_body returns None and the route
    sees no body. /clusters POST then rejects it with 400."""
    port, _ = live_server
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/clusters",
        data=b"{not json",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req)
    assert excinfo.value.code == 400
