"""Typed wrappers around the Slurm ``s*`` command line.

`SlurmClient` is a thin layer:

  - build argv (no shell expansion ever),
  - run via the injected ``Runner``,
  - on non-zero exit, raise ``CommandError`` carrying the full
    ``CommandResult`` so callers can surface stderr to the UI,
  - on success, parse stdout — JSON where Slurm supports ``--json``
    (most commands on Slurm ≥ 21.08), pipe-delimited fallback via
    ``--parsable2 --noheader`` for ``sacctmgr show``.

Audit logging lives one layer up (dashboard / MCP server) so the
client doesn't have to know who's calling.

Submission commands (``srun``, ``sbatch``, ``sbcast``) are intentionally
absent — this project is a *management* plane. ``scontrol shutdown``
is also absent (too easy to brick a controller with a typo).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from .connection import CommandResult


class _RunnerProto(Protocol):
    cluster: Any
    def run(self, argv: list[str], timeout: int = 60) -> CommandResult: ...


class CommandError(RuntimeError):
    """Raised when a Slurm command exits non-zero."""

    def __init__(self, result: CommandResult, message: str | None = None):
        self.result = result
        msg = message or (
            f"{result.argv[0] if result.argv else '?'} "
            f"exited {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
        )
        super().__init__(msg)


# ---------------------------------------------------------------------
# Pipe-delimited parser for `sacctmgr show ... --parsable2 --noheader`
# ---------------------------------------------------------------------


def parse_parsable2(stdout: str, fields: list[str]) -> list[dict[str, str]]:
    """sacctmgr --parsable2 emits one row per line, ``|``-delimited.

    --noheader strips the header row. We supply the field list to
    re-key the columns. Empty trailing lines are ignored.
    """
    out: list[dict[str, str]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        # parsable2 always emits a trailing | so len(parts) == len(fields) + 1
        if len(parts) and parts[-1] == "":
            parts = parts[:-1]
        row: dict[str, str] = {}
        for i, name in enumerate(fields):
            row[name] = parts[i] if i < len(parts) else ""
        out.append(row)
    return out


def _kv(**kwargs: Any) -> list[str]:
    """Turn ``Key=Value`` pairs into a stable, sorted argv list.

    None values are dropped (so callers can pass ``foo=None`` for
    "don't set"). All values are stringified — Slurm's CLI doesn't
    care about Python types.
    """
    return [f"{k}={v}" for k, v in sorted(kwargs.items()) if v is not None]


# ---------------------------------------------------------------------
# SlurmClient
# ---------------------------------------------------------------------


@dataclass
class SlurmClient:
    runner: _RunnerProto
    default_timeout: int = 60

    # Internal --------------------------------------------------------

    def _run(self, argv: list[str], timeout: int | None = None) -> CommandResult:
        return self.runner.run(argv, timeout=timeout or self.default_timeout)

    def _run_json(self, argv: list[str], timeout: int | None = None) -> dict:
        result = self._run(argv, timeout)
        if not result.ok:
            raise CommandError(result)
        if not result.stdout.strip():
            return {}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise CommandError(
                result,
                f"{argv[0]} produced unparseable JSON: {exc}; "
                f"first 200 bytes: {result.stdout[:200]!r}",
            ) from exc

    def _run_ok(self, argv: list[str], timeout: int | None = None) -> CommandResult:
        result = self._run(argv, timeout)
        if not result.ok:
            raise CommandError(result)
        return result

    # ------------------------------------------------------------------
    # READ-ONLY: cluster state
    # ------------------------------------------------------------------

    def sinfo(self) -> dict:
        """``sinfo --json`` — node + partition snapshot."""
        return self._run_json(["sinfo", "--json"])

    def squeue(self) -> dict:
        """``squeue --json`` — currently queued/running jobs."""
        return self._run_json(["squeue", "--json"])

    def sacct(
        self,
        starttime: str | None = None,
        endtime: str | None = None,
        users: str | None = None,
        accounts: str | None = None,
        states: str | None = None,
    ) -> dict:
        """``sacct --json`` — accounting records (completed jobs)."""
        argv = ["sacct", "--json"]
        if starttime: argv += ["--starttime", starttime]
        if endtime:   argv += ["--endtime", endtime]
        if users:     argv += ["--user", users]
        if accounts:  argv += ["--accounts", accounts]
        if states:    argv += ["--state", states]
        return self._run_json(argv)

    def scontrol_show_node(self, name: str | None = None) -> dict:
        argv = ["scontrol", "show", "node"]
        if name:
            argv.append(name)
        argv.append("--json")
        return self._run_json(argv)

    def scontrol_show_partition(self, name: str | None = None) -> dict:
        argv = ["scontrol", "show", "partition"]
        if name:
            argv.append(name)
        argv.append("--json")
        return self._run_json(argv)

    def scontrol_show_job(self, jobid: str | None = None) -> dict:
        argv = ["scontrol", "show", "job"]
        if jobid:
            argv.append(str(jobid))
        argv.append("--json")
        return self._run_json(argv)

    def scontrol_show_reservation(self, name: str | None = None) -> dict:
        argv = ["scontrol", "show", "reservation"]
        if name:
            argv.append(name)
        argv.append("--json")
        return self._run_json(argv)

    def scontrol_show_config(self) -> dict:
        return self._run_json(["scontrol", "show", "config", "--json"])

    def sshare(self) -> dict:
        """``sshare --json`` — fairshare tree."""
        return self._run_json(["sshare", "--json"])

    def sprio(self) -> dict:
        """``sprio --json`` — pending-job priority breakdown."""
        return self._run_json(["sprio", "--json"])

    def sstat(self, jobid: str) -> dict:
        """``sstat --json`` — live stats for a running job step."""
        return self._run_json(["sstat", "--json", "-j", str(jobid)])

    def sdiag(self) -> dict:
        """``sdiag --json`` — controller diagnostics."""
        return self._run_json(["sdiag", "--json"])

    # ------------------------------------------------------------------
    # READ-ONLY: accounting (sacctmgr show — parsable2 fallback)
    # ------------------------------------------------------------------

    _ACCT_FIELDS = {
        "account": ["Account", "Description", "Organization"],
        "user":    ["User", "DefaultAccount", "Admin"],
        "assoc":   ["Cluster", "Account", "User", "Partition", "Share",
                    "Priority", "MaxJobs", "MaxNodes", "MaxCPUs",
                    "MaxWall", "GrpJobs", "QOS"],
        "qos":     ["Name", "Priority", "GraceTime", "Preempt", "PreemptMode",
                    "Flags", "MaxJobs", "MaxNodes", "MaxWall"],
        "cluster": ["Cluster", "ControlHost", "ControlPort", "RPC",
                    "Share", "GrpJobs", "GrpTRES"],
    }

    def sacctmgr_show(
        self, entity: str, where: dict[str, str] | None = None,
    ) -> list[dict[str, str]]:
        """``sacctmgr show <entity> --parsable2 --noheader``.

        ``entity`` is one of: account, user, assoc, qos, cluster.
        ``where`` is an optional set of WHERE-style filters.
        """
        if entity not in self._ACCT_FIELDS:
            raise ValueError(f"unknown sacctmgr entity {entity!r}")
        argv = ["sacctmgr", "show", entity, "--parsable2", "--noheader"]
        # Pass an explicit Format list so column order matches our parser.
        argv += [f"Format={','.join(self._ACCT_FIELDS[entity])}"]
        if where:
            argv += ["where"] + [f"{k}={v}" for k, v in where.items()]
        result = self._run_ok(argv)
        return parse_parsable2(result.stdout, self._ACCT_FIELDS[entity])

    def sreport(self, report_args: list[str]) -> str:
        """``sreport <args>`` — text output. ``sreport`` doesn't support
        ``--json`` consistently across versions; just return stdout as
        a fenced block for the UI to render.
        """
        result = self._run_ok(["sreport", "--parsable2"] + list(report_args))
        return result.stdout

    # ------------------------------------------------------------------
    # DESTRUCTIVE: jobs
    # ------------------------------------------------------------------

    def scancel(self, jobid: str, signal: str | None = None) -> CommandResult:
        argv = ["scancel"]
        if signal:
            argv += ["--signal", signal]
        argv.append(str(jobid))
        return self._run_ok(argv)

    def scontrol_hold(self, jobid: str) -> CommandResult:
        return self._run_ok(["scontrol", "hold", str(jobid)])

    def scontrol_release(self, jobid: str) -> CommandResult:
        return self._run_ok(["scontrol", "release", str(jobid)])

    def scontrol_requeue(self, jobid: str) -> CommandResult:
        return self._run_ok(["scontrol", "requeue", str(jobid)])

    def scontrol_update_job(self, jobid: str, **fields: Any) -> CommandResult:
        argv = ["scontrol", "update", f"JobId={jobid}"] + _kv(**fields)
        return self._run_ok(argv)

    # ------------------------------------------------------------------
    # DESTRUCTIVE: nodes
    # ------------------------------------------------------------------

    def scontrol_update_node(
        self, node: str, state: str, reason: str | None = None,
    ) -> CommandResult:
        """Set node state. Valid values: DOWN, DRAIN, RESUME, IDLE, FAIL, FUTURE.
        ``reason`` is required by Slurm when transitioning to DOWN or DRAIN.
        """
        state_u = state.upper()
        if state_u in {"DOWN", "DRAIN"} and not reason:
            raise ValueError(f"state={state_u} requires a non-empty reason")
        argv = ["scontrol", "update", f"NodeName={node}", f"State={state_u}"]
        if reason:
            argv += [f"Reason={reason}"]
        return self._run_ok(argv)

    # ------------------------------------------------------------------
    # DESTRUCTIVE: partitions
    # ------------------------------------------------------------------

    def scontrol_create_partition(self, name: str, **fields: Any) -> CommandResult:
        argv = ["scontrol", "create", f"PartitionName={name}"] + _kv(**fields)
        return self._run_ok(argv)

    def scontrol_update_partition(self, name: str, **fields: Any) -> CommandResult:
        argv = ["scontrol", "update", f"PartitionName={name}"] + _kv(**fields)
        return self._run_ok(argv)

    def scontrol_delete_partition(self, name: str) -> CommandResult:
        return self._run_ok(["scontrol", "delete", f"PartitionName={name}"])

    # ------------------------------------------------------------------
    # DESTRUCTIVE: reservations
    # ------------------------------------------------------------------

    def scontrol_create_reservation(self, **fields: Any) -> CommandResult:
        """``scontrol create reservation <K=V>...``. Caller passes
        ``ReservationName=foo`` etc. via kwargs. Slurm validates the
        required fields.
        """
        return self._run_ok(["scontrol", "create", "reservation"] + _kv(**fields))

    def scontrol_update_reservation(self, name: str, **fields: Any) -> CommandResult:
        argv = ["scontrol", "update", f"ReservationName={name}"] + _kv(**fields)
        return self._run_ok(argv)

    def scontrol_delete_reservation(self, name: str) -> CommandResult:
        return self._run_ok(["scontrol", "delete", f"ReservationName={name}"])

    # ------------------------------------------------------------------
    # DESTRUCTIVE: accounts / users / qos via sacctmgr
    # ``-i`` is mandatory: without it sacctmgr drops into an
    # interactive prompt that hangs SSH exec.
    # ------------------------------------------------------------------

    def sacctmgr_add_account(self, name: str, **fields: Any) -> CommandResult:
        argv = ["sacctmgr", "-i", "add", "account", name] + _kv(**fields)
        return self._run_ok(argv)

    def sacctmgr_modify_account(
        self, name: str, set_fields: dict[str, Any],
    ) -> CommandResult:
        argv = (
            ["sacctmgr", "-i", "modify", "account", f"name={name}", "set"]
            + _kv(**set_fields)
        )
        return self._run_ok(argv)

    def sacctmgr_delete_account(self, name: str) -> CommandResult:
        return self._run_ok(["sacctmgr", "-i", "delete", "account", f"name={name}"])

    def sacctmgr_add_user(
        self, name: str, account: str | None = None, **fields: Any,
    ) -> CommandResult:
        argv = ["sacctmgr", "-i", "add", "user", name]
        if account:
            argv.append(f"account={account}")
        argv += _kv(**fields)
        return self._run_ok(argv)

    def sacctmgr_modify_user(
        self, name: str, set_fields: dict[str, Any],
    ) -> CommandResult:
        argv = (
            ["sacctmgr", "-i", "modify", "user", f"name={name}", "set"]
            + _kv(**set_fields)
        )
        return self._run_ok(argv)

    def sacctmgr_delete_user(self, name: str) -> CommandResult:
        return self._run_ok(["sacctmgr", "-i", "delete", "user", f"name={name}"])

    def sacctmgr_add_qos(self, name: str, **fields: Any) -> CommandResult:
        argv = ["sacctmgr", "-i", "add", "qos", name] + _kv(**fields)
        return self._run_ok(argv)

    def sacctmgr_modify_qos(
        self, name: str, set_fields: dict[str, Any],
    ) -> CommandResult:
        argv = (
            ["sacctmgr", "-i", "modify", "qos", f"name={name}", "set"]
            + _kv(**set_fields)
        )
        return self._run_ok(argv)

    def sacctmgr_delete_qos(self, name: str) -> CommandResult:
        return self._run_ok(["sacctmgr", "-i", "delete", "qos", f"name={name}"])

    # ------------------------------------------------------------------
    # DESTRUCTIVE: cluster-wide
    # ------------------------------------------------------------------

    def scontrol_reconfigure(self) -> CommandResult:
        """Tell the controller to reread slurm.conf. Generally safe but
        it's a config rollout so we treat it as destructive in the UI.
        """
        return self._run_ok(["scontrol", "reconfigure"])


# ---------------------------------------------------------------------
# Destructive tool registry — single source of truth shared between
# the dashboard's confirm-modal logic and the MCP server's
# ``MCPServerConfig.destructive`` advertisement.
# ---------------------------------------------------------------------


DESTRUCTIVE_TOOLS: frozenset[str] = frozenset({
    "jobs_cancel", "jobs_hold", "jobs_release", "jobs_requeue", "jobs_update",
    "nodes_set_state",
    "partitions_create", "partitions_update", "partitions_delete",
    "reservations_create", "reservations_update", "reservations_delete",
    "accounts_add", "accounts_modify", "accounts_delete",
    "users_add", "users_modify", "users_delete",
    "qos_add", "qos_modify", "qos_delete",
    "cluster_reconfigure",
})


def is_destructive(tool_name: str) -> bool:
    return tool_name in DESTRUCTIVE_TOOLS


def all_destructive() -> Iterable[str]:
    return iter(sorted(DESTRUCTIVE_TOOLS))
