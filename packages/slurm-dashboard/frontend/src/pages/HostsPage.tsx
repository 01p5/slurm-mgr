import { useState } from "react";
import { Plus, Trash2, RefreshCw, CheckCircle2, XCircle } from "lucide-react";
import { Card, EmptyState, ErrorBox } from "../components/Card";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { Table, type Column } from "../components/Table";
import { ConfirmModal } from "../components/ConfirmModal";
import { api, type ClusterSummary } from "../api";
import { useClusters } from "../ClusterContext";

export function HostsPage() {
  const { clusters, reload, loading, error } = useClusters();
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [pingStatus, setPingStatus] = useState<Record<string, "ok" | "err" | "busy">>({});
  const [pingMsg, setPingMsg] = useState<Record<string, string>>({});

  const ping = async (name: string) => {
    setPingStatus((s) => ({ ...s, [name]: "busy" }));
    try {
      const r = await api.get<{ ok: boolean; stdout: string; stderr: string }>(
        `/clusters/${encodeURIComponent(name)}/check`,
      );
      setPingStatus((s) => ({ ...s, [name]: r.ok ? "ok" : "err" }));
      setPingMsg((m) => ({ ...m, [name]: r.stdout || r.stderr }));
    } catch (e) {
      setPingStatus((s) => ({ ...s, [name]: "err" }));
      setPingMsg((m) => ({ ...m, [name]: e instanceof Error ? e.message : String(e) }));
    }
  };

  const columns: Column<ClusterSummary>[] = [
    { key: "name",     header: "Name",     cell: (c) => <span className="text-text-primary">{c.name}</span> },
    { key: "host",     header: "Host",     cell: (c) => `${c.user}@${c.host}:${c.port}` },
    { key: "jump",     header: "Jump",     cell: (c) => c.jump_host || <span className="text-text-muted">—</span> },
    { key: "key",      header: "Key",      cell: (c) => c.key_present ? <Badge tone="green">present</Badge> : <Badge tone="red">missing</Badge> },
    {
      key: "ping",
      header: "Reachable",
      cell: (c) => {
        const st = pingStatus[c.name];
        if (st === "busy") return <Badge tone="yellow">checking…</Badge>;
        if (st === "ok")   return <Badge tone="green"><CheckCircle2 size={10} className="mr-1" />ok</Badge>;
        if (st === "err")  return <Badge tone="red"><XCircle size={10} className="mr-1" />error</Badge>;
        return <Button size="sm" variant="ghost" onClick={() => ping(c.name)}>ping</Button>;
      },
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (c) => (
        <Button size="sm" variant="ghost" icon={<Trash2 size={12} />} onClick={() => setDeleting(c.name)}>
          remove
        </Button>
      ),
    },
  ];

  return (
    <div className="p-4 h-full grid grid-rows-[auto_1fr_auto] gap-4">
      <Card
        title="Registered clusters"
        actions={
          <>
            <Button size="sm" variant="ghost" icon={<RefreshCw size={12} />} onClick={reload} loading={loading}>
              reload
            </Button>
            <Button size="sm" variant="primary" icon={<Plus size={12} />} onClick={() => setAdding(true)}>
              add cluster
            </Button>
          </>
        }
      >
        {error && <ErrorBox message={error} />}
        {clusters.length === 0 && !loading ? (
          <EmptyState message="No clusters registered. Click 'add cluster' to point slurm-mgr at a Slurm login node." />
        ) : (
          <Table columns={columns} rows={clusters} rowKey={(c) => c.name} />
        )}
      </Card>

      {Object.entries(pingMsg).length > 0 && (
        <Card title="Last ping output">
          <pre className="px-3 py-2 font-mono text-[11px] text-text-secondary whitespace-pre-wrap">
            {Object.entries(pingMsg).map(([k, v]) => `── ${k} ──\n${v}\n`).join("\n")}
          </pre>
        </Card>
      )}

      <p className="text-[11px] font-mono text-text-muted">
        Clusters live in <code className="text-text-secondary">~/.slurm-mgr/hosts.json</code>. SSH key auth only — no passwords stored. The configured user needs the <code>s*</code> binaries on $PATH.
      </p>

      {adding && (
        <AddClusterModal
          onClose={() => setAdding(false)}
          onSaved={() => { setAdding(false); reload(); }}
        />
      )}

      <ConfirmModal
        open={!!deleting}
        title="Remove cluster?"
        body={
          <span>
            Removes <code className="text-text-primary">{deleting}</code> from the registry. No data on the cluster is changed.
          </span>
        }
        confirmLabel="Remove"
        onConfirm={async () => {
          await api.delete(`/clusters/${encodeURIComponent(deleting!)}`);
          setDeleting(null);
          reload();
        }}
        onClose={() => setDeleting(null)}
      />
    </div>
  );
}

function AddClusterModal({
  onClose, onSaved,
}: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    name: "", host: "", user: "", key_path: "", port: 22, jump_host: "",
  });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true); setErr(null);
    try {
      await api.post("/clusters", {
        ...form,
        jump_host: form.jump_host || null,
      });
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const field = (k: keyof typeof form, label: string, hint?: string, type: string = "text") => (
    <label className="block">
      <span className="text-[11px] font-mono uppercase tracking-[0.5px] text-text-secondary">{label}</span>
      <input
        type={type}
        value={String(form[k] ?? "")}
        onChange={(e) => setForm({ ...form, [k]: type === "number" ? Number(e.target.value) : e.target.value })}
        className="mt-1 w-full bg-dark-tertiary border border-border-subtle rounded-sm px-2 py-1.5 font-mono text-xs text-text-primary focus:outline-none focus:border-border-active"
      />
      {hint && <span className="block text-[10px] text-text-muted mt-1">{hint}</span>}
    </label>
  );

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 backdrop-blur-sm" onClick={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div className="w-full max-w-lg bg-dark-secondary border border-border-subtle rounded-md shadow-xl">
        <header className="px-4 py-3 border-b border-border-subtle">
          <h3 className="font-display text-sm font-semibold text-text-primary">Add cluster</h3>
        </header>
        <div className="px-4 py-3 grid grid-cols-2 gap-3">
          {field("name", "Name", "Used as label + tool prefix")}
          {field("host", "Host", "Slurm login node hostname")}
          {field("user", "User", "SSH username")}
          {field("port", "Port", undefined, "number")}
          <div className="col-span-2">{field("key_path", "Private key path", "Absolute path on this machine")}</div>
          <div className="col-span-2">{field("jump_host", "Jump host (optional)", "user@bastion[:port]")}</div>
        </div>
        {err && <div className="px-4 pb-2"><div className="p-2 bg-accent-red/10 border border-accent-red/30 rounded-sm font-mono text-xs text-accent-red">{err}</div></div>}
        <footer className="px-4 py-3 border-t border-border-subtle flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="primary" onClick={save} loading={busy}>Save</Button>
        </footer>
      </div>
    </div>
  );
}
