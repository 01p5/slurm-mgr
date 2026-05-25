# slurm-mgr

A management console + MCP server for [Slurm](https://slurm.schedmd.com/) clusters.

Two surfaces, one core:

1. **Dashboard.** Standalone web UI (React + Tailwind, dark "security console" palette) for inspecting and managing one or more Slurm clusters over SSH. Covers every read-only `s*` command and the safe destructive ones — submission (`srun`/`sbatch`) is deliberately out of scope.
2. **MCP server.** Hand-rolled JSON-RPC 2.0 stdio server (Model Context Protocol `2024-11-05`) exposing the same operations as tools, designed to plug straight into [Olympus](https://github.com/01p5/01p5)'s `MCPServerConfig`. Olympus then gates destructive ops through its approval queue + audit log.

> Built as a sibling to [Olympus](https://github.com/01p5/01p5). The dashboard runs standalone; the MCP server lets Olympus's sysadmin agent drive your cluster with the same safety story it gives kubectl.

## Layout

```
slurm-mgr/
├── packages/
│   ├── slurmlib/             # core SDK — SSH connection, command wrappers, models, audit
│   ├── slurm-dashboard/      # HTTP backend + React/Vite/Tailwind SPA
│   └── slurm-mcp/            # stdio JSON-RPC MCP server (protocol 2024-11-05)
├── docs/
└── scripts/
```

Each package has its own `pyproject.toml` so you can `pip install -e packages/<name>` independently.

## Quick start

### 1. Install (editable)

```bash
git clone git@github.com:01p5/slurm-mgr.git && cd slurm-mgr
pip install -e packages/slurmlib -e packages/slurm-dashboard -e packages/slurm-mcp
```

### 2. Register a cluster

Edit `~/.slurm-mgr/hosts.json` (it'll be created on first dashboard save), or add via the Hosts page:

```json
{
  "clusters": [
    {
      "name": "prod",
      "host": "slurm-login01.example.com",
      "user": "yuxiao",
      "key_path": "/home/yuxiao/.ssh/id_ed25519",
      "port": 22,
      "jump_host": null
    }
  ]
}
```

The configured user must have shell access on the login node, and the relevant `s*` binaries must be on `$PATH`. SSH key auth only — no passwords.

### 3. Run the dashboard

```bash
# backend (stdlib http.server, :8770)
python -m slurm_dashboard.server

# frontend (Vite dev server, :5174 → proxies to :8770)
cd packages/slurm-dashboard/frontend
npm install
npm run dev
```

Open <http://localhost:5174/>.

### 4. Run the MCP server

```bash
# stdio mode — pick a cluster from your registry
slurm-mcp --cluster prod
# or:
python -m slurm_mcp --cluster prod
```

Wire into Olympus:

```python
from agentlib import MCPServerConfig
cfg = MCPServerConfig(
    name="slurm_prod",
    command="slurm-mcp",
    args=["--cluster", "prod"],
    destructive={
        "jobs_cancel", "jobs_hold", "jobs_release", "jobs_requeue", "jobs_update",
        "nodes_set_state", "partitions_create", "partitions_update", "partitions_delete",
        "reservations_create", "reservations_update", "reservations_delete",
        "accounts_add", "accounts_modify", "accounts_delete",
        "users_add", "users_modify", "users_delete",
        "qos_add", "qos_modify", "qos_delete",
        "cluster_reconfigure",
    },
)
```

## Slurm command coverage

| Page / MCP namespace | Slurm commands | Destructive ops |
|----------------------|----------------|-----------------|
| **Hosts**         | (registry mgmt)                                          | save/delete host |
| **Nodes**         | `sinfo --json`, `scontrol show node --json`              | `scontrol update NodeName=... State={DOWN,DRAIN,RESUME,IDLE,FAIL,FUTURE}` |
| **Jobs**          | `squeue --json`, `scontrol show job --json`              | `scancel`, `scontrol hold|release|requeue|update job ...` |
| **Partitions**    | `scontrol show partition --json`                         | `scontrol create|update|delete PartitionName=...` |
| **Reservations**  | `scontrol show reservation --json`                       | `scontrol create|update|delete ReservationName=...` |
| **Accounts**      | `sacctmgr show account/user/assoc/qos/cluster` (`--parsable2`) | `sacctmgr add|modify|delete account|user|qos ...` |
| **Accounting**    | `sacct --json`, `sreport`                                | — |
| **Fairshare**     | `sshare --json`, `sprio --json`                          | — |
| **Diagnostics**   | `sdiag --json`, `sstat --json`                           | — |
| **Cluster**       | `scontrol show config --json`                            | `scontrol reconfigure` |

`--json` works on Slurm ≥ 21.08 for most commands; `sacctmgr` / `sreport` fall back to `--parsable2`. Submission commands (`srun`, `sbatch`, `sbcast`) are deliberately excluded — this is a management plane, not a job-launcher. `scontrol shutdown` is also excluded (too easy to brick a controller with a typo).

## Safety model

The dashboard runs every command via the SSH runner and writes both the pre-call and post-call records to `~/.slurm-mgr/audit.jsonl` (append-only, mirrors the JsonlAuditLogger shape from Olympus). Destructive actions surface a confirmation modal in the UI before they fire.

Through the MCP path, the destructive set is declared in `MCPServerConfig.destructive` so Olympus's `gate_tools` routes those calls through the approval queue. The MCP server itself does **not** add a second confirmation layer — Olympus is the human-in-the-loop for that flow.

## Status

Early. The shape is right; not everything is polished. See `docs/STATUS.md` for what's wired vs scaffolded.
