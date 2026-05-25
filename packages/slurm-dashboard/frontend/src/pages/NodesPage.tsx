import { useMemo, useState } from "react";
import { RefreshCw, AlertOctagon } from "lucide-react";
import { Card, EmptyState, ErrorBox } from "../components/Card";
import { Button } from "../components/Button";
import { Badge, stateTone } from "../components/Badge";
import { Table, type Column } from "../components/Table";
import { ConfirmModal } from "../components/ConfirmModal";
import { useFetch } from "../hooks";
import { useClusters, useClusterPath } from "../ClusterContext";
import { api } from "../api";

type Node = {
  name?: string;
  hostname?: string;
  state?: string[];
  cpus?: number;
  real_memory?: number;
  alloc_cpus?: number;
  partitions?: string[];
  reason?: string;
};

type ChangeStateTarget = { node: string; current: string[]; nextState?: string; reason?: string };

const NODE_STATES = ["IDLE", "DOWN", "DRAIN", "RESUME", "FAIL", "FUTURE"];

export function NodesPage() {
  const { active } = useClusters();
  const path = useClusterPath();
  const { data, error, loading, reload } = useFetch<{ nodes?: Node[] }>(active ? path("/nodes") : null, 15_000);
  const [target, setTarget] = useState<ChangeStateTarget | null>(null);

  const rows = useMemo<Node[]>(() => data?.nodes ?? [], [data]);

  const columns: Column<Node>[] = [
    { key: "name",    header: "Node",       cell: (n) => n.name || n.hostname || "?" },
    {
      key: "state", header: "State",
      cell: (n) => (
        <div className="flex flex-wrap gap-1">
          {(n.state ?? []).map((s, i) => <Badge key={i} tone={stateTone(s)}>{s}</Badge>)}
        </div>
      ),
    },
    {
      key: "cpus", header: "CPU",
      cell: (n) => {
        const a = n.alloc_cpus ?? 0, t = n.cpus ?? 0;
        return <span><span className="text-text-secondary">{a}</span>/{t}</span>;
      },
    },
    {
      key: "mem", header: "Mem (MB)",
      cell: (n) => n.real_memory ? n.real_memory.toLocaleString() : "—",
    },
    {
      key: "parts", header: "Partitions",
      cell: (n) => (n.partitions ?? []).join(", ") || "—",
    },
    {
      key: "reason", header: "Reason",
      cell: (n) => n.reason ? <span className="text-accent-yellow">{n.reason}</span> : "—",
    },
    {
      key: "act", header: "", align: "right",
      cell: (n) => (
        <Button
          size="sm" variant="ghost" icon={<AlertOctagon size={12} />}
          onClick={() => setTarget({ node: n.name ?? n.hostname ?? "?", current: n.state ?? [] })}
        >
          set state
        </Button>
      ),
    },
  ];

  return (
    <div className="p-4 h-full">
      <Card
        title={`Nodes — ${active ?? "no cluster"}`}
        className="h-full"
        actions={
          <Button size="sm" variant="ghost" icon={<RefreshCw size={12} />} onClick={reload} loading={loading}>
            reload
          </Button>
        }
      >
        {!active && <EmptyState message="Select a cluster from the topbar (or add one on the Hosts page)." />}
        {error && <ErrorBox message={error} />}
        {active && !error && <Table columns={columns} rows={rows} rowKey={(n, i) => n.name ?? String(i)} empty="No nodes returned." />}
      </Card>

      <ConfirmModal
        open={!!target}
        title={target ? `Update state of ${target.node}?` : ""}
        body={
          <div className="space-y-3">
            <div className="text-xs">
              Current state: {target?.current.map((s, i) => <Badge key={i} tone={stateTone(s)} className="mr-1">{s}</Badge>)}
            </div>
            <label className="block">
              <span className="text-[11px] font-mono uppercase text-text-secondary">New state</span>
              <select
                value={target?.nextState ?? ""}
                onChange={(e) => setTarget(target ? { ...target, nextState: e.target.value } : null)}
                className="mt-1 w-full bg-dark-tertiary border border-border-subtle rounded-sm px-2 py-1.5 font-mono text-xs"
              >
                <option value="">— select —</option>
                {NODE_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="text-[11px] font-mono uppercase text-text-secondary">Reason (required for DOWN/DRAIN)</span>
              <input
                value={target?.reason ?? ""}
                onChange={(e) => setTarget(target ? { ...target, reason: e.target.value } : null)}
                className="mt-1 w-full bg-dark-tertiary border border-border-subtle rounded-sm px-2 py-1.5 font-mono text-xs"
              />
            </label>
          </div>
        }
        confirmLabel="Apply"
        onConfirm={async () => {
          if (!target?.nextState) return;
          await api.post(path(`/nodes/${encodeURIComponent(target.node)}/state`), {
            state: target.nextState, reason: target.reason || null,
          });
          setTarget(null);
          reload();
        }}
        onClose={() => setTarget(null)}
      />
    </div>
  );
}
