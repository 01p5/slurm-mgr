"""SSH connection layer.

Two responsibilities:

1. **Cluster registry** — `~/.slurm-mgr/hosts.json` is the single source of
   truth for which Slurm controllers this install can reach. The dashboard
   reads + writes it from the Hosts page; the MCP server reads it at startup
   keyed by ``--cluster <name>``.

2. **SSH runner** — `SSHRunner` wraps paramiko. One SSH connection per
   ``run()`` call (no pooling for v1 — Slurm commands are short-lived and
   the connect cost is dominated by anything you'd actually do with the
   output). Supports an optional jump host via paramiko's
   `ProxyCommand`-equivalent channel.

The runner returns `CommandResult` regardless of exit code; it is the
caller's job (typically `SlurmClient`) to raise `CommandError` on
non-zero exits. That separation lets the audit log capture every
attempt — success or failure — without forcing the caller to wrap a
try/except.
"""
from __future__ import annotations

import json
import os
import shlex
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

try:
    import paramiko
except ImportError:  # pragma: no cover - dep declared in pyproject
    paramiko = None  # type: ignore[assignment]


# ---------------------------------------------------------------------
# Cluster model + registry
# ---------------------------------------------------------------------


@dataclass(slots=True)
class Cluster:
    """A reachable Slurm login node.

    ``jump_host`` is in the form ``user@host[:port]`` and is optional;
    when set, paramiko opens a channel through it before connecting to
    the inner login node. Useful for bastion topologies.
    """
    name: str
    host: str
    user: str
    key_path: str
    port: int = 22
    jump_host: str | None = None

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: dict) -> "Cluster":
        return cls(
            name=raw["name"],
            host=raw["host"],
            user=raw["user"],
            key_path=raw["key_path"],
            port=int(raw.get("port", 22)),
            jump_host=raw.get("jump_host"),
        )


def _default_registry_path() -> Path:
    """Resolved at call time so tests can override SLURM_MGR_HOSTS via
    monkeypatch after the module is imported."""
    return Path(
        os.environ.get("SLURM_MGR_HOSTS", Path.home() / ".slurm-mgr" / "hosts.json")
    )


# Kept for callers that import the constant directly.
DEFAULT_REGISTRY_PATH = _default_registry_path()


class ClusterRegistry:
    """JSON-on-disk registry. Concurrency-naive — single user, single host
    operations. Last-writer-wins on the file.
    """

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else _default_registry_path()

    def _load(self) -> list[Cluster]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text() or "{}")
        items = raw.get("clusters", [])
        return [Cluster.from_json(c) for c in items]

    def _save(self, clusters: Iterable[Cluster]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"clusters": [c.to_json() for c in clusters]}
        # Two-step rename: never leave a half-written file behind.
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n")
        tmp.replace(self.path)

    def list(self) -> list[Cluster]:
        return self._load()

    def get(self, name: str) -> Cluster:
        for c in self._load():
            if c.name == name:
                return c
        raise KeyError(f"no cluster registered named {name!r}")

    def add(self, cluster: Cluster) -> None:
        current = [c for c in self._load() if c.name != cluster.name]
        current.append(cluster)
        self._save(current)

    def remove(self, name: str) -> None:
        current = [c for c in self._load() if c.name != name]
        self._save(current)


# ---------------------------------------------------------------------
# CommandResult + SSHRunner
# ---------------------------------------------------------------------


@dataclass(slots=True)
class CommandResult:
    argv: list[str]
    stdout: str
    stderr: str
    returncode: int
    duration_s: float
    cluster: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_json(self) -> dict:
        return {
            "argv": list(self.argv),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "duration_s": round(self.duration_s, 4),
            "cluster": self.cluster,
        }


class SSHRunner:
    """One-shot SSH command executor for a single cluster.

    Not thread-safe across ``run()`` calls — each call opens a fresh
    connection. That's fine for Slurm operations (the command itself
    dominates), and it sidesteps stale-channel problems entirely.
    """

    def __init__(self, cluster: Cluster, connect_timeout: int = 10):
        if paramiko is None:  # pragma: no cover
            raise RuntimeError(
                "paramiko is required for SSHRunner. pip install paramiko"
            )
        self.cluster = cluster
        self.connect_timeout = connect_timeout

    def _connect(self) -> "paramiko.SSHClient":
        # The lazy-import pattern keeps slurmlib importable on hosts
        # without paramiko (useful for parser-only test scenarios).
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        sock = None
        if self.cluster.jump_host:
            sock = self._open_jump_channel()
        client.connect(
            hostname=self.cluster.host,
            port=self.cluster.port,
            username=self.cluster.user,
            key_filename=self.cluster.key_path,
            timeout=self.connect_timeout,
            banner_timeout=self.connect_timeout,
            auth_timeout=self.connect_timeout,
            allow_agent=False,
            look_for_keys=False,
            sock=sock,
        )
        return client

    def _open_jump_channel(self):
        """Open a direct-tcpip channel through ``jump_host`` to the
        inner host:port. Returns a paramiko.Channel suitable for the
        ``sock=`` arg of SSHClient.connect.
        """
        jump_user, _, jump_rest = (self.cluster.jump_host or "").partition("@")
        jump_host, _, jump_port = jump_rest.partition(":")
        jump_port_i = int(jump_port) if jump_port else 22

        jump = paramiko.SSHClient()
        jump.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        jump.connect(
            hostname=jump_host,
            port=jump_port_i,
            username=jump_user or self.cluster.user,
            key_filename=self.cluster.key_path,
            timeout=self.connect_timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        transport = jump.get_transport()
        if transport is None:  # pragma: no cover - paramiko invariant
            raise RuntimeError("jump host transport not established")
        return transport.open_channel(
            kind="direct-tcpip",
            dest_addr=(self.cluster.host, self.cluster.port),
            src_addr=("127.0.0.1", 0),
        )

    def run(self, argv: list[str], timeout: int = 60) -> CommandResult:
        """Execute argv on the remote and capture stdout/stderr.

        The remote shell joins via shlex.quote — callers pass ``argv``
        as a list and trust the runner to do the quoting. This is the
        same shape as ``subprocess.run`` and avoids the classic shell
        injection foot-gun where a partition name with a space breaks
        argv parsing.
        """
        cmd = " ".join(shlex.quote(a) for a in argv)
        started = time.monotonic()
        client = self._connect()
        try:
            stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
            stdin.close()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            rc = stdout.channel.recv_exit_status()
        finally:
            client.close()
        return CommandResult(
            argv=list(argv),
            stdout=out,
            stderr=err,
            returncode=rc,
            duration_s=time.monotonic() - started,
            cluster=self.cluster.name,
        )


# ---------------------------------------------------------------------
# LocalRunner — a drop-in for tests / running on the controller itself.
# ---------------------------------------------------------------------


class LocalRunner:
    """Same interface as SSHRunner but uses ``subprocess`` locally.

    Used in two cases: (a) deploying the dashboard directly on a Slurm
    login node — skip SSH overhead entirely; (b) tests, where we can
    point at a fake ``slurm`` shim on PATH.
    """

    def __init__(self, cluster_name: str = "local", env: dict | None = None):
        self.cluster = Cluster(
            name=cluster_name, host="localhost", user="local",
            key_path="", port=0,
        )
        self.env = env

    def run(self, argv: list[str], timeout: int = 60) -> CommandResult:
        import subprocess  # noqa: PLC0415 - lazy

        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, **(self.env or {})},
                check=False,
            )
            out, err, rc = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            out, err, rc = exc.stdout or "", (exc.stderr or "") + "\n[timeout]", 124
        except FileNotFoundError as exc:
            out, err, rc = "", f"{exc}", 127
        return CommandResult(
            argv=list(argv),
            stdout=out if isinstance(out, str) else out.decode("utf-8", "replace"),
            stderr=err if isinstance(err, str) else err.decode("utf-8", "replace"),
            returncode=rc,
            duration_s=time.monotonic() - started,
            cluster=self.cluster.name,
        )


# Protocol marker — any object with ``cluster: Cluster`` and
# ``run(argv, timeout=...) -> CommandResult`` is a valid runner.
Runner = SSHRunner | LocalRunner


@dataclass(slots=True)
class _FakeRunner:
    """Test seam. Holds a list of canned (returncode, stdout, stderr)
    tuples and pops them per ``run()`` call. Defined here so callers
    can ``isinstance`` against ``Runner`` without import gymnastics.
    """
    cluster: Cluster
    responses: list[tuple[int, str, str]] = field(default_factory=list)
    calls: list[list[str]] = field(default_factory=list)

    def run(self, argv: list[str], timeout: int = 60) -> CommandResult:
        self.calls.append(list(argv))
        if not self.responses:
            rc, out, err = 0, "", ""
        else:
            rc, out, err = self.responses.pop(0)
        return CommandResult(
            argv=list(argv), stdout=out, stderr=err,
            returncode=rc, duration_s=0.001, cluster=self.cluster.name,
        )
