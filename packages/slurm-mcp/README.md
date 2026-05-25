# slurm-mcp

A hand-rolled JSON-RPC 2.0 stdio MCP server (protocol revision
`2024-11-05`) that exposes Slurm management operations as MCP tools.

Designed to plug straight into [Olympus](https://github.com/01p5/01p5)
via `MCPServerConfig`. Same wire shape as Olympus's own
`infra/demo-mcp-server/server.py` — handshake, `tools/list`,
`tools/call`, notifications. Stdlib only.

## Run

```bash
pip install -e ../slurmlib -e .

# Pick a cluster from ~/.slurm-mgr/hosts.json
slurm-mcp --cluster prod
# or, for development on a controller, use local exec:
slurm-mcp --local
```

It then sits on stdin waiting for MCP requests.

## Wire into Olympus

```python
from agentlib import MCPServerConfig
cfg = MCPServerConfig(
    name="slurm_prod",
    command="slurm-mcp",
    args=["--cluster", "prod"],
    destructive={
        "jobs_cancel", "jobs_hold", "jobs_release", "jobs_requeue", "jobs_update",
        "nodes_set_state",
        "partitions_create", "partitions_update", "partitions_delete",
        "reservations_create", "reservations_update", "reservations_delete",
        "accounts_add", "accounts_modify", "accounts_delete",
        "users_add", "users_modify", "users_delete",
        "qos_add", "qos_modify", "qos_delete",
        "cluster_reconfigure",
    },
)
```

Once registered, the destructive ones route through Olympus's approval
queue + audit + (where applicable) rollback before they fire.

## Tool surface

Read-only:

- `nodes_list`, `nodes_describe`
- `jobs_list`, `jobs_describe`
- `partitions_list`
- `reservations_list`
- `accounts_list`, `users_list`, `assocs_list`, `qos_list`
- `accounting_query` (sacct), `accounting_report` (sreport)
- `fairshare_show` (sshare), `priorities_show` (sprio)
- `diagnostics_show` (sdiag), `job_stats` (sstat)
- `cluster_config` (scontrol show config)

Destructive:

- `jobs_cancel`, `jobs_hold`, `jobs_release`, `jobs_requeue`, `jobs_update`
- `nodes_set_state`
- `partitions_create`, `partitions_update`, `partitions_delete`
- `reservations_create`, `reservations_update`, `reservations_delete`
- `accounts_add`, `accounts_modify`, `accounts_delete`
- `users_add`, `users_modify`, `users_delete`
- `qos_add`, `qos_modify`, `qos_delete`
- `cluster_reconfigure`
