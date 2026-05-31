import { useMemo, useState } from "react";
import { RefreshCw, Trash2, Plus, Pencil } from "lucide-react";
import { Card, EmptyState, ErrorBox } from "../components/Card";
import { Button } from "../components/Button";
import { Badge, stateTone } from "../components/Badge";
import { Table, type Column } from "../components/Table";
import { ConfirmModal } from "../components/ConfirmModal";
import { useFetch } from "../hooks";
import { useClusters, useClusterPath } from "../ClusterContext";
import { api } from "../api";

type Partition = {
  name?: string;
  state?: string | string[];
  nodes?: { configured?: string } | string;
  max_time?: { number?: number } | number;
  max_nodes?: { number?: number } | number;
  default?: boolean;
};

export function PartitionsPage() {
  const { active } = useClusters();
  const path = useClusterPath();
  const { data, error, loading, reload } = useFetch<{ partitions?: Partition[] }>(active ? path("/partitions") : null, 30_000);
  const [del, setDel] = useState<string | null>(null);
  const [edit, setEdit] = useState<{ mode: "create" | "edit"; name: string; fields: string } | null>(null);

  const rows = useMemo<Partition[]>(() => data?.partitions ?? [], [data]);

  const stateOf = (p: Partition): string => Array.isArray(p.state) ? p.state[0] ?? "" : String(p.state ?? "");
  const nodesOf = (p: Partition): string => {
    const n = p.nodes as { configured?: string } | string | undefined;
    if (!n) return "—";
    return typeof n === "string" ? n : (n.configured ?? "—");
  };
  const numOf = (v: unknown): string =>
    typeof v === "object" && v && "number" in v ? String((v as {number?:number}).number ?? "—") : (v == null ? "—" : String(v));

  const columns: Column<Partition>[] = [
    { key: "name", header: "Name",
      cell: (p) => <span>{p.name}{p.default && <Badge tone="purple" className="ml-1.5">default</Badge>}</span> },
    { key: "state", header: "State", cell: (p) => <Badge tone={stateTone(stateOf(p))}>{stateOf(p) || "?"}</Badge> },
    { key: "nodes", header: "Nodes", cell: (p) => nodesOf(p) },
    { key: "maxt",  header: "MaxTime",  cell: (p) => numOf(p.max_time) },
    { key: "maxn",  header: "MaxNodes", cell: (p) => numOf(p.max_nodes) },
    {
      key: "act", header: "", align: "right",
      cell: (p) => (
        <div className="flex justify-end gap-1">
          <Button size="sm" variant="ghost" icon={<Pencil size={11} />} onClick={() => setEdit({ mode: "edit", name: p.name!, fields: "" })}>edit</Button>
          <Button size="sm" variant="ghost" icon={<Trash2 size={11} />} onClick={() => setDel(p.name ?? "")}>delete</Button>
        </div>
      ),
    },
  ];

  return (
    <div className="p-4 h-full">
      <Card
        title={`Partitions — ${active ?? "no cluster"}`}
        className="h-full"
        actions={
          <>
            <Button size="sm" variant="ghost" icon={<RefreshCw size={14} strokeWidth={2.25} />} onClick={reload} loading={loading}>reload</Button>
            <Button size="sm" variant="primary" icon={<Plus size={14} strokeWidth={2.25} />} onClick={() => setEdit({ mode: "create", name: "", fields: "" })}>new</Button>
          </>
        }
      >
        {!active && <EmptyState message="Select a cluster." />}
        {error && <ErrorBox message={error} />}
        {active && !error && <Table columns={columns} rows={rows} rowKey={(p, i) => p.name ?? String(i)} empty="No partitions configured." />}
      </Card>

      <ConfirmModal
        open={!!del}
        title={`Delete partition ${del}?`}
        body={<span>Partitions with running jobs can't be deleted. Slurm will reject if it's in use.</span>}
        confirmLabel="Delete"
        onConfirm={async () => {
          await api.delete(path(`/partitions/${encodeURIComponent(del!)}`));
          setDel(null); reload();
        }}
        onClose={() => setDel(null)}
      />

      <KVEditorModal
        open={!!edit}
        title={edit?.mode === "create" ? "Create partition" : `Edit ${edit?.name}`}
        nameLabel={edit?.mode === "create" ? "PartitionName" : null}
        defaultName={edit?.name ?? ""}
        defaultFields={edit?.fields ?? ""}
        confirmLabel={edit?.mode === "create" ? "Create" : "Update"}
        onClose={() => setEdit(null)}
        onConfirm={async (name, kv) => {
          if (edit?.mode === "create") {
            await api.post(path("/partitions"), { name, ...kv });
          } else {
            await api.patch(path(`/partitions/${encodeURIComponent(name)}`), kv);
          }
          setEdit(null); reload();
        }}
      />
    </div>
  );
}

// Generic K=V editor used by Partitions, Reservations, etc.
// The text area is plain `Key=Value` per line (Slurm-native style)
// so the user can paste straight from `scontrol show`.
export function KVEditorModal({
  open, title, nameLabel, defaultName, defaultFields, confirmLabel,
  onClose, onConfirm,
}: {
  open: boolean;
  title: string;
  nameLabel: string | null;       // null when editing an existing entity (name is fixed)
  defaultName: string;
  defaultFields: string;
  confirmLabel: string;
  onClose: () => void;
  onConfirm: (name: string, fields: Record<string, string>) => Promise<void>;
}) {
  const [name, setName] = useState(defaultName);
  const [text, setText] = useState(defaultFields);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const parse = (): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eq = trimmed.indexOf("=");
      if (eq < 0) continue;
      out[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1).trim();
    }
    return out;
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 backdrop-blur-sm" onClick={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div className="w-full max-w-lg bg-dark-secondary border border-border-subtle rounded-md shadow-xl">
        <header className="px-4 py-3 border-b border-border-subtle">
          <h3 className="font-display text-sm font-semibold text-text-primary">{title}</h3>
        </header>
        <div className="px-4 py-3 space-y-3">
          {nameLabel && (
            <label className="block">
              <span className="text-[11px] font-mono uppercase text-text-secondary">{nameLabel}</span>
              <input
                value={name} onChange={(e) => setName(e.target.value)}
                className="mt-1 w-full bg-dark-tertiary border border-border-subtle rounded-sm px-2 py-1.5 font-mono text-xs"
              />
            </label>
          )}
          <label className="block">
            <span className="text-[11px] font-mono uppercase text-text-secondary">Fields (one Key=Value per line)</span>
            <textarea
              value={text} onChange={(e) => setText(e.target.value)}
              rows={8}
              spellCheck={false}
              placeholder={"MaxTime=24:00:00\nNodes=node[1-4]\nDefault=YES"}
              className="mt-1 w-full bg-dark-tertiary border border-border-subtle rounded-sm px-2 py-1.5 font-mono text-xs"
            />
          </label>
          {err && <div className="p-2 bg-accent-red/10 border border-accent-red/30 rounded-sm font-mono text-xs text-accent-red">{err}</div>}
        </div>
        <footer className="px-4 py-3 border-t border-border-subtle flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button
            variant="primary" loading={busy}
            onClick={async () => {
              setBusy(true); setErr(null);
              try { await onConfirm(name, parse()); }
              catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
              finally { setBusy(false); }
            }}
          >{confirmLabel}</Button>
        </footer>
      </div>
    </div>
  );
}
