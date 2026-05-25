"""ClusterRegistry round-trips through disk, and JsonlAuditLogger
writes one JSON-per-line append-only."""
from __future__ import annotations

import json

from slurmlib import Cluster, ClusterRegistry, JsonlAuditLogger
from slurmlib.audit import AuditRecord


def test_registry_roundtrip(tmp_path):
    reg = ClusterRegistry(tmp_path / "hosts.json")
    reg.add(Cluster(name="prod", host="h", user="u", key_path="/k"))
    reg.add(Cluster(name="dev",  host="h2", user="u2", key_path="/k2",
                    port=2222, jump_host="b@bastion:22"))
    names = [c.name for c in reg.list()]
    assert names == ["prod", "dev"]
    assert reg.get("dev").jump_host == "b@bastion:22"
    reg.remove("prod")
    assert [c.name for c in reg.list()] == ["dev"]


def test_registry_upsert_replaces_existing(tmp_path):
    reg = ClusterRegistry(tmp_path / "hosts.json")
    reg.add(Cluster(name="prod", host="h", user="u", key_path="/k"))
    reg.add(Cluster(name="prod", host="h2", user="u2", key_path="/k2"))
    rows = reg.list()
    assert len(rows) == 1
    assert rows[0].host == "h2"


def test_audit_writes_jsonl(tmp_path):
    audit = JsonlAuditLogger(tmp_path / "audit.jsonl")
    audit.write(AuditRecord(
        record_id="abc", timestamp=0.0, cluster="t",
        command=["sinfo", "--json"], destructive=False,
        phase="pre", actor="dashboard",
    ))
    audit.write(AuditRecord(
        record_id="abc", timestamp=1.0, cluster="t",
        command=["sinfo", "--json"], destructive=False,
        phase="post", actor="dashboard", returncode=0,
        duration_s=0.05, stdout_preview='{"x":1}',
    ))
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["phase"] == "pre"
    assert parsed[1]["returncode"] == 0
    assert parsed[1]["duration_s"] == 0.05


def test_audit_around_context_writes_pre_and_post(tmp_path):
    audit = JsonlAuditLogger(tmp_path / "audit.jsonl")

    class FakeResult:
        stdout = "ok"
        stderr = ""
        returncode = 0
        duration_s = 0.01

    with audit.around("dashboard", "t", ["scancel", "1"], destructive=True) as ctx:
        ctx.set_result(FakeResult())

    parsed = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert len(parsed) == 2
    assert parsed[0]["phase"] == "pre" and parsed[0]["destructive"] is True
    assert parsed[1]["phase"] == "post" and parsed[1]["returncode"] == 0
