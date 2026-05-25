"""Append-only audit log of every Slurm command run through slurmlib.

Lifted in shape from Olympus's ``JsonlAuditLogger`` (``libs/agentlib/
runtime.py``) so cross-project tooling stays uniform. One JSON object
per line; never rewritten in place.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_AUDIT_PATH = Path(
    os.environ.get("SLURM_MGR_AUDIT", Path.home() / ".slurm-mgr" / "audit.jsonl")
)


@dataclass(slots=True)
class AuditRecord:
    record_id: str
    timestamp: float
    cluster: str
    command: list[str]
    destructive: bool
    phase: str                  # "pre" | "post"
    actor: str                  # "dashboard" | "mcp" | "cli"
    returncode: int | None = None
    duration_s: float | None = None
    stdout_preview: str | None = None
    stderr_preview: str | None = None
    note: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None or k == "returncode"}


class NullAuditLogger:
    """Drop calls on the floor. Used in tests and ``slurm-mcp`` when
    Olympus is upstream — Olympus already logs every gated tool call
    through its own JsonlAuditLogger, so doubling up is just noise.
    """

    path = None

    def write(self, record: AuditRecord) -> None:
        return None

    def around(
        self,
        actor: str,
        cluster: str,
        argv: list[str],
        destructive: bool,
        note: str | None = None,
    ) -> "AuditContext":
        # Reuse the same context shape, but writes go through the null
        # write(). That keeps the dashboard's call sites identical.
        return AuditContext(self, actor, cluster, argv, destructive, note)  # type: ignore[arg-type]


class JsonlAuditLogger:
    """Append-only writer. fsyncs each line so a crash doesn't lose
    the last record — Slurm operations are rare enough that the extra
    syscall is invisible.
    """

    def __init__(self, path: Path | str = DEFAULT_AUDIT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: AuditRecord) -> None:
        line = json.dumps(record.to_json(), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # Convenience for callers — wraps a runner.run() with pre/post records.
    def around(
        self,
        actor: str,
        cluster: str,
        argv: list[str],
        destructive: bool,
        note: str | None = None,
    ) -> "AuditContext":
        return AuditContext(self, actor, cluster, argv, destructive, note)


@dataclass(slots=True)
class AuditContext:
    """Tiny context manager. Writes a "pre" record on enter, then a
    "post" record on exit populated from the ``CommandResult`` the
    caller stashes via ``set_result``.
    """
    logger: JsonlAuditLogger
    actor: str
    cluster: str
    argv: list[str]
    destructive: bool
    note: str | None = None
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _result: Any = None

    def __enter__(self) -> "AuditContext":
        self.logger.write(AuditRecord(
            record_id=self.record_id,
            timestamp=time.time(),
            cluster=self.cluster,
            command=list(self.argv),
            destructive=self.destructive,
            phase="pre",
            actor=self.actor,
            note=self.note,
        ))
        return self

    def set_result(self, result) -> None:
        self._result = result

    def __exit__(self, exc_type, exc, tb) -> None:
        result = self._result
        self.logger.write(AuditRecord(
            record_id=self.record_id,
            timestamp=time.time(),
            cluster=self.cluster,
            command=list(self.argv),
            destructive=self.destructive,
            phase="post",
            actor=self.actor,
            returncode=getattr(result, "returncode", None),
            duration_s=getattr(result, "duration_s", None),
            stdout_preview=_truncate(getattr(result, "stdout", None)),
            stderr_preview=_truncate(getattr(result, "stderr", None)),
            note=str(exc) if exc else self.note,
        ))


def _truncate(s: str | None, limit: int = 2_000) -> str | None:
    if s is None:
        return None
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n…[truncated {len(s) - limit} bytes]"
