# slurmlib

Pure-Python core for slurm-mgr. No HTTP, no React. Just:

- **`connection.py`** — `Cluster`, `ClusterRegistry` (reads/writes `~/.slurm-mgr/hosts.json`), `SSHRunner` (paramiko wrapper with jump-host support).
- **`commands.py`** — `SlurmClient`, typed wrappers around the read-only `s*` commands (with `--json` where Slurm supports it) and the safe destructive ops.
- **`models.py`** — small dataclasses for parsed results.
- **`audit.py`** — `JsonlAuditLogger`, append-only command log. Mirrors the shape from Olympus's `libs/agentlib/runtime.py`.

If you want a fifth surface (CLI, TUI, exporter), this is the only package to import.
