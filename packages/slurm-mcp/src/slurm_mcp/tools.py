"""Tool descriptors + per-tool dispatch table.

Each entry has:

  - ``name``        — MCP tool name (matches the dashboard route family
                      so Olympus's prompts can talk about them uniformly).
  - ``description`` — what the tool does + whether it mutates state. The
                      LLM reads this; be terse but accurate.
  - ``inputSchema`` — JSON Schema for the argument object.
  - ``destructive`` — surfaces both in ``tools/list`` (annotation) and as
                      the recommended ``MCPServerConfig.destructive`` set
                      so the integrator can copy-paste.
  - ``handler``     — callable that takes (SlurmClient, args) → text.

The destructive bit is advisory inside MCP itself (the spec carries no
such notion). Olympus is the enforcer.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from slurmlib import CommandError, SlurmClient


# ---------------------------------------------------------------------
# Handler helpers
# ---------------------------------------------------------------------


def _json_dump(value: Any) -> str:
    """Render any JSON-ish output as a pretty string for the tool's
    text content. Keep below ~30k chars so LLM context stays sane.
    """
    s = json.dumps(value, indent=2, default=str)
    if len(s) > 30_000:
        s = s[:30_000] + "\n\n…[truncated]"
    return s


def _ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _err(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


# ---------------------------------------------------------------------
# Handlers — one per tool
# ---------------------------------------------------------------------


def h_nodes_list(c: SlurmClient, _args: dict) -> dict:
    return _ok(_json_dump(c.sinfo()))


def h_nodes_describe(c: SlurmClient, args: dict) -> dict:
    return _ok(_json_dump(c.scontrol_show_node(args.get("name"))))


def h_jobs_list(c: SlurmClient, _args: dict) -> dict:
    return _ok(_json_dump(c.squeue()))


def h_jobs_describe(c: SlurmClient, args: dict) -> dict:
    return _ok(_json_dump(c.scontrol_show_job(args.get("jobid"))))


def h_partitions_list(c: SlurmClient, _args: dict) -> dict:
    return _ok(_json_dump(c.scontrol_show_partition()))


def h_reservations_list(c: SlurmClient, _args: dict) -> dict:
    return _ok(_json_dump(c.scontrol_show_reservation()))


def h_accounts_list(c: SlurmClient, _args: dict) -> dict:
    return _ok(_json_dump(c.sacctmgr_show("account")))


def h_users_list(c: SlurmClient, _args: dict) -> dict:
    return _ok(_json_dump(c.sacctmgr_show("user")))


def h_assocs_list(c: SlurmClient, _args: dict) -> dict:
    return _ok(_json_dump(c.sacctmgr_show("assoc")))


def h_qos_list(c: SlurmClient, _args: dict) -> dict:
    return _ok(_json_dump(c.sacctmgr_show("qos")))


def h_accounting_query(c: SlurmClient, args: dict) -> dict:
    return _ok(_json_dump(c.sacct(
        starttime=args.get("starttime"),
        endtime=args.get("endtime"),
        users=args.get("users"),
        accounts=args.get("accounts"),
        states=args.get("states"),
    )))


def h_accounting_report(c: SlurmClient, args: dict) -> dict:
    return _ok(c.sreport(list(args.get("args", []))))


def h_fairshare_show(c: SlurmClient, _args: dict) -> dict:
    return _ok(_json_dump(c.sshare()))


def h_priorities_show(c: SlurmClient, _args: dict) -> dict:
    return _ok(_json_dump(c.sprio()))


def h_diagnostics_show(c: SlurmClient, _args: dict) -> dict:
    return _ok(_json_dump(c.sdiag()))


def h_job_stats(c: SlurmClient, args: dict) -> dict:
    jobid = args.get("jobid")
    if not jobid:
        return _err("jobid is required")
    return _ok(_json_dump(c.sstat(str(jobid))))


def h_cluster_config(c: SlurmClient, _args: dict) -> dict:
    return _ok(_json_dump(c.scontrol_show_config()))


# ---- Destructive: jobs ----


def _need(args: dict, key: str) -> str:
    v = args.get(key)
    if v in (None, ""):
        raise ValueError(f"{key} is required")
    return str(v)


def h_jobs_cancel(c: SlurmClient, args: dict) -> dict:
    return _ok_result(c.scancel(_need(args, "jobid"), signal=args.get("signal")))


def h_jobs_hold(c: SlurmClient, args: dict) -> dict:
    return _ok_result(c.scontrol_hold(_need(args, "jobid")))


def h_jobs_release(c: SlurmClient, args: dict) -> dict:
    return _ok_result(c.scontrol_release(_need(args, "jobid")))


def h_jobs_requeue(c: SlurmClient, args: dict) -> dict:
    return _ok_result(c.scontrol_requeue(_need(args, "jobid")))


def h_jobs_update(c: SlurmClient, args: dict) -> dict:
    jobid = _need(args, "jobid")
    fields = dict(args.get("fields") or {})
    if not fields:
        raise ValueError("fields is required (a dict of Key=Value)")
    return _ok_result(c.scontrol_update_job(jobid, **fields))


# ---- Destructive: nodes ----


def h_nodes_set_state(c: SlurmClient, args: dict) -> dict:
    return _ok_result(c.scontrol_update_node(
        _need(args, "name"), _need(args, "state"), reason=args.get("reason"),
    ))


# ---- Destructive: partitions / reservations ----


def h_partitions_create(c: SlurmClient, args: dict) -> dict:
    name = _need(args, "name")
    fields = dict(args.get("fields") or {})
    return _ok_result(c.scontrol_create_partition(name, **fields))


def h_partitions_update(c: SlurmClient, args: dict) -> dict:
    name = _need(args, "name")
    fields = dict(args.get("fields") or {})
    return _ok_result(c.scontrol_update_partition(name, **fields))


def h_partitions_delete(c: SlurmClient, args: dict) -> dict:
    return _ok_result(c.scontrol_delete_partition(_need(args, "name")))


def h_reservations_create(c: SlurmClient, args: dict) -> dict:
    fields = dict(args.get("fields") or {})
    return _ok_result(c.scontrol_create_reservation(**fields))


def h_reservations_update(c: SlurmClient, args: dict) -> dict:
    name = _need(args, "name")
    fields = dict(args.get("fields") or {})
    return _ok_result(c.scontrol_update_reservation(name, **fields))


def h_reservations_delete(c: SlurmClient, args: dict) -> dict:
    return _ok_result(c.scontrol_delete_reservation(_need(args, "name")))


# ---- Destructive: accounts / users / qos ----


def h_accounts_add(c: SlurmClient, args: dict) -> dict:
    name = _need(args, "name")
    fields = dict(args.get("fields") or {})
    return _ok_result(c.sacctmgr_add_account(name, **fields))


def h_accounts_modify(c: SlurmClient, args: dict) -> dict:
    name = _need(args, "name")
    set_fields = dict(args.get("set") or {})
    if not set_fields:
        raise ValueError("`set` is required (a dict of fields to update)")
    return _ok_result(c.sacctmgr_modify_account(name, set_fields))


def h_accounts_delete(c: SlurmClient, args: dict) -> dict:
    return _ok_result(c.sacctmgr_delete_account(_need(args, "name")))


def h_users_add(c: SlurmClient, args: dict) -> dict:
    name = _need(args, "name")
    fields = dict(args.get("fields") or {})
    return _ok_result(c.sacctmgr_add_user(name, account=args.get("account"), **fields))


def h_users_modify(c: SlurmClient, args: dict) -> dict:
    name = _need(args, "name")
    set_fields = dict(args.get("set") or {})
    if not set_fields:
        raise ValueError("`set` is required")
    return _ok_result(c.sacctmgr_modify_user(name, set_fields))


def h_users_delete(c: SlurmClient, args: dict) -> dict:
    return _ok_result(c.sacctmgr_delete_user(_need(args, "name")))


def h_qos_add(c: SlurmClient, args: dict) -> dict:
    name = _need(args, "name")
    fields = dict(args.get("fields") or {})
    return _ok_result(c.sacctmgr_add_qos(name, **fields))


def h_qos_modify(c: SlurmClient, args: dict) -> dict:
    name = _need(args, "name")
    set_fields = dict(args.get("set") or {})
    if not set_fields:
        raise ValueError("`set` is required")
    return _ok_result(c.sacctmgr_modify_qos(name, set_fields))


def h_qos_delete(c: SlurmClient, args: dict) -> dict:
    return _ok_result(c.sacctmgr_delete_qos(_need(args, "name")))


# ---- Cluster-wide ----


def h_cluster_reconfigure(c: SlurmClient, _args: dict) -> dict:
    return _ok_result(c.scontrol_reconfigure())


def _ok_result(result) -> dict:
    """Wrap a successful CommandResult as an MCP text content block."""
    out = (result.stdout or "").strip()
    return _ok(out if out else "ok")


# ---------------------------------------------------------------------
# Tool catalog (passed to MCP tools/list)
# ---------------------------------------------------------------------


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOLS: list[dict[str, Any]] = [
    # ---------- READ-ONLY ----------
    {"name": "nodes_list", "destructive": False,
     "description": "List all nodes via `sinfo --json`.",
     "inputSchema": _schema({})},
    {"name": "nodes_describe", "destructive": False,
     "description": "`scontrol show node <name> --json`. Omit name for all nodes.",
     "inputSchema": _schema({"name": {"type": "string"}})},
    {"name": "jobs_list", "destructive": False,
     "description": "List active jobs via `squeue --json`.",
     "inputSchema": _schema({})},
    {"name": "jobs_describe", "destructive": False,
     "description": "`scontrol show job <jobid> --json`. Omit jobid for all jobs.",
     "inputSchema": _schema({"jobid": {"type": "string"}})},
    {"name": "partitions_list", "destructive": False,
     "description": "`scontrol show partition --json`.",
     "inputSchema": _schema({})},
    {"name": "reservations_list", "destructive": False,
     "description": "`scontrol show reservation --json`.",
     "inputSchema": _schema({})},
    {"name": "accounts_list", "destructive": False,
     "description": "`sacctmgr show account --parsable2`.",
     "inputSchema": _schema({})},
    {"name": "users_list", "destructive": False,
     "description": "`sacctmgr show user --parsable2`.",
     "inputSchema": _schema({})},
    {"name": "assocs_list", "destructive": False,
     "description": "`sacctmgr show assoc --parsable2`.",
     "inputSchema": _schema({})},
    {"name": "qos_list", "destructive": False,
     "description": "`sacctmgr show qos --parsable2`.",
     "inputSchema": _schema({})},
    {"name": "accounting_query", "destructive": False,
     "description": "`sacct --json` over completed jobs. All filters optional; passed straight to sacct.",
     "inputSchema": _schema({
         "starttime": {"type": "string", "description": "YYYY-MM-DD[THH:MM]"},
         "endtime":   {"type": "string"},
         "users":     {"type": "string", "description": "csv"},
         "accounts":  {"type": "string"},
         "states":    {"type": "string", "description": "Slurm state codes, csv"},
     })},
    {"name": "accounting_report", "destructive": False,
     "description": "Run a `sreport` query. Args are passed verbatim (e.g. ['cluster','utilization','start=…','end=…']).",
     "inputSchema": _schema({"args": {"type": "array", "items": {"type": "string"}}}, ["args"])},
    {"name": "fairshare_show", "destructive": False,
     "description": "`sshare --json` — fairshare tree.",
     "inputSchema": _schema({})},
    {"name": "priorities_show", "destructive": False,
     "description": "`sprio --json` — pending-job priority breakdown.",
     "inputSchema": _schema({})},
    {"name": "diagnostics_show", "destructive": False,
     "description": "`sdiag --json` — controller stats.",
     "inputSchema": _schema({})},
    {"name": "job_stats", "destructive": False,
     "description": "`sstat --json -j <jobid>` — live stats for a running step.",
     "inputSchema": _schema({"jobid": {"type": "string"}}, ["jobid"])},
    {"name": "cluster_config", "destructive": False,
     "description": "`scontrol show config --json`.",
     "inputSchema": _schema({})},

    # ---------- DESTRUCTIVE ----------
    {"name": "jobs_cancel", "destructive": True,
     "description": "Cancel a job via `scancel`. Optional ``signal`` to send instead of SIGTERM.",
     "inputSchema": _schema({"jobid": {"type": "string"}, "signal": {"type": "string"}}, ["jobid"])},
    {"name": "jobs_hold", "destructive": True,
     "description": "Hold a pending job (`scontrol hold`).",
     "inputSchema": _schema({"jobid": {"type": "string"}}, ["jobid"])},
    {"name": "jobs_release", "destructive": True,
     "description": "Release a held job (`scontrol release`).",
     "inputSchema": _schema({"jobid": {"type": "string"}}, ["jobid"])},
    {"name": "jobs_requeue", "destructive": True,
     "description": "Requeue a running or completed job (`scontrol requeue`).",
     "inputSchema": _schema({"jobid": {"type": "string"}}, ["jobid"])},
    {"name": "jobs_update", "destructive": True,
     "description": "Update a job (`scontrol update JobId=… <K=V>…`). ``fields`` is a {Key:Value} dict.",
     "inputSchema": _schema(
        {"jobid": {"type": "string"}, "fields": {"type": "object"}}, ["jobid", "fields"])},
    {"name": "nodes_set_state", "destructive": True,
     "description": "Set node state to one of DOWN/DRAIN/RESUME/IDLE/FAIL/FUTURE. Reason required for DOWN/DRAIN.",
     "inputSchema": _schema(
        {"name": {"type": "string"}, "state": {"type": "string"}, "reason": {"type": "string"}},
        ["name", "state"])},
    {"name": "partitions_create", "destructive": True,
     "description": "`scontrol create PartitionName=<name> <K=V>…`. ``fields`` is a {Key:Value} dict.",
     "inputSchema": _schema(
        {"name": {"type": "string"}, "fields": {"type": "object"}}, ["name"])},
    {"name": "partitions_update", "destructive": True,
     "description": "`scontrol update PartitionName=<name> <K=V>…`.",
     "inputSchema": _schema(
        {"name": {"type": "string"}, "fields": {"type": "object"}}, ["name", "fields"])},
    {"name": "partitions_delete", "destructive": True,
     "description": "`scontrol delete PartitionName=<name>`. Rejected if in use.",
     "inputSchema": _schema({"name": {"type": "string"}}, ["name"])},
    {"name": "reservations_create", "destructive": True,
     "description": "`scontrol create reservation <K=V>…`. Caller supplies all fields incl. ReservationName.",
     "inputSchema": _schema({"fields": {"type": "object"}}, ["fields"])},
    {"name": "reservations_update", "destructive": True,
     "description": "`scontrol update ReservationName=<name> <K=V>…`.",
     "inputSchema": _schema(
        {"name": {"type": "string"}, "fields": {"type": "object"}}, ["name", "fields"])},
    {"name": "reservations_delete", "destructive": True,
     "description": "`scontrol delete ReservationName=<name>`.",
     "inputSchema": _schema({"name": {"type": "string"}}, ["name"])},
    {"name": "accounts_add", "destructive": True,
     "description": "`sacctmgr -i add account <name> <K=V>…`.",
     "inputSchema": _schema(
        {"name": {"type": "string"}, "fields": {"type": "object"}}, ["name"])},
    {"name": "accounts_modify", "destructive": True,
     "description": "`sacctmgr -i modify account name=<name> set <K=V>…`. ``set`` is required.",
     "inputSchema": _schema(
        {"name": {"type": "string"}, "set": {"type": "object"}}, ["name", "set"])},
    {"name": "accounts_delete", "destructive": True,
     "description": "`sacctmgr -i delete account name=<name>`.",
     "inputSchema": _schema({"name": {"type": "string"}}, ["name"])},
    {"name": "users_add", "destructive": True,
     "description": "`sacctmgr -i add user <name> account=<account> <K=V>…`.",
     "inputSchema": _schema(
        {"name": {"type": "string"}, "account": {"type": "string"}, "fields": {"type": "object"}},
        ["name"])},
    {"name": "users_modify", "destructive": True,
     "description": "`sacctmgr -i modify user name=<name> set <K=V>…`. ``set`` is required.",
     "inputSchema": _schema(
        {"name": {"type": "string"}, "set": {"type": "object"}}, ["name", "set"])},
    {"name": "users_delete", "destructive": True,
     "description": "`sacctmgr -i delete user name=<name>`.",
     "inputSchema": _schema({"name": {"type": "string"}}, ["name"])},
    {"name": "qos_add", "destructive": True,
     "description": "`sacctmgr -i add qos <name> <K=V>…`.",
     "inputSchema": _schema(
        {"name": {"type": "string"}, "fields": {"type": "object"}}, ["name"])},
    {"name": "qos_modify", "destructive": True,
     "description": "`sacctmgr -i modify qos name=<name> set <K=V>…`.",
     "inputSchema": _schema(
        {"name": {"type": "string"}, "set": {"type": "object"}}, ["name", "set"])},
    {"name": "qos_delete", "destructive": True,
     "description": "`sacctmgr -i delete qos name=<name>`.",
     "inputSchema": _schema({"name": {"type": "string"}}, ["name"])},
    {"name": "cluster_reconfigure", "destructive": True,
     "description": "`scontrol reconfigure` — controller re-reads slurm.conf.",
     "inputSchema": _schema({})},
]


HANDLERS: dict[str, Callable[[SlurmClient, dict], dict]] = {
    "nodes_list":           h_nodes_list,
    "nodes_describe":       h_nodes_describe,
    "jobs_list":            h_jobs_list,
    "jobs_describe":        h_jobs_describe,
    "partitions_list":      h_partitions_list,
    "reservations_list":    h_reservations_list,
    "accounts_list":        h_accounts_list,
    "users_list":           h_users_list,
    "assocs_list":          h_assocs_list,
    "qos_list":             h_qos_list,
    "accounting_query":     h_accounting_query,
    "accounting_report":    h_accounting_report,
    "fairshare_show":       h_fairshare_show,
    "priorities_show":      h_priorities_show,
    "diagnostics_show":     h_diagnostics_show,
    "job_stats":            h_job_stats,
    "cluster_config":       h_cluster_config,
    "jobs_cancel":          h_jobs_cancel,
    "jobs_hold":            h_jobs_hold,
    "jobs_release":         h_jobs_release,
    "jobs_requeue":         h_jobs_requeue,
    "jobs_update":          h_jobs_update,
    "nodes_set_state":      h_nodes_set_state,
    "partitions_create":    h_partitions_create,
    "partitions_update":    h_partitions_update,
    "partitions_delete":    h_partitions_delete,
    "reservations_create":  h_reservations_create,
    "reservations_update":  h_reservations_update,
    "reservations_delete":  h_reservations_delete,
    "accounts_add":         h_accounts_add,
    "accounts_modify":      h_accounts_modify,
    "accounts_delete":      h_accounts_delete,
    "users_add":            h_users_add,
    "users_modify":         h_users_modify,
    "users_delete":         h_users_delete,
    "qos_add":              h_qos_add,
    "qos_modify":           h_qos_modify,
    "qos_delete":           h_qos_delete,
    "cluster_reconfigure":  h_cluster_reconfigure,
}


def dispatch_tool(client: SlurmClient, name: str, arguments: dict) -> dict:
    """Find and call a tool handler. Mirrors the shape Olympus's
    MCPClient.call_tool consumes (content list + isError flag).
    """
    handler = HANDLERS.get(name)
    if handler is None:
        return _err(f"unknown tool {name!r}")
    try:
        return handler(client, arguments or {})
    except CommandError as exc:
        # Surface stderr to the LLM so it can see why Slurm rejected.
        msg = str(exc)
        if exc.result.stderr.strip():
            msg += f"\nstderr: {exc.result.stderr.strip()}"
        return _err(msg)
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:
        return _err(f"{type(exc).__name__}: {exc}")


def tools_descriptor() -> list[dict]:
    """The list returned by MCP ``tools/list`` — strips internal-only
    fields like ``destructive`` from the public envelope but exposes
    it under ``annotations`` so a curious client can see it.
    """
    out = []
    for t in TOOLS:
        desc = {
            "name": t["name"],
            "description": t["description"],
            "inputSchema": t["inputSchema"],
        }
        if t.get("destructive"):
            desc["annotations"] = {"destructive": True}
        out.append(desc)
    return out


def destructive_names() -> list[str]:
    return sorted(t["name"] for t in TOOLS if t.get("destructive"))
