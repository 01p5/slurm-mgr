import { useMemo, useState } from "react";
import { RefreshCw, X, Pause, Play, RotateCw } from "lucide-react";
import { Card, EmptyState, ErrorBox } from "../components/Card";
import { Button } from "../components/Button";
import { Badge, stateTone } from "../components/Badge";
import { Table, type Column } from "../components/Table";
import { ConfirmModal } from "../components/ConfirmModal";
import { useFetch } from "../hooks";
import { useClusters, useClusterPath } from "../ClusterContext";
import { api } from "../api";

type Job = {
  job_id?: number | string;
  name?: string;
  user_name?: string;
  partition?: string;
  job_state?: string | string[];
  nodes?: string;
  cpus?: { number?: number } | number;
  time_limit?: { number?: number } | number;
  // ...other Slurm-version-specific fields
};

type Action = "cancel" | "hold" | "release" | "requeue";

export function JobsPage() {
  const { active } = useClusters();
  const path = useClusterPath();
  const { data, error, loading, reload } = useFetch<{ jobs?: Job[] }>(active ? path("/jobs") : null, 10_000);
  const [filter, setFilter] = useState("");
  const [pending, setPending] = useState<{ action: Action; job: Job } | null>(null);

  const rows = useMemo<Job[]>(() => {
    const all = data?.jobs ?? [];
    if (!filter.trim()) return all;
    const q = filter.toLowerCase();
    return all.filter((j) => JSON.stringify(j).toLowerCase().includes(q));
  }, [data, filter]);

  const stateOf = (j: Job): string => Array.isArray(j.job_state) ? (j.job_state[0] ?? "") : String(j.job_state ?? "");
  const numOf   = (v: unknown): string => typeof v === "object" && v && "number" in v ? String((v as {number?:number}).number ?? "") : String(v ?? "");

  const columns: Column<Job>[] = [
    { key: "id",   header: "Job",        cell: (j) => <span className="text-accent-blue">{String(j.job_id)}</span> },
    { key: "name", header: "Name",       cell: (j) => j.name ?? "—" },
    { key: "user", header: "User",       cell: (j) => j.user_name ?? "—" },
    { key: "part", header: "Partition",  cell: (j) => j.partition ?? "—" },
    { key: "state", header: "State",     cell: (j) => <Badge tone={stateTone(stateOf(j))}>{stateOf(j) || "?"}</Badge> },
    { key: "nodes", header: "Nodes",     cell: (j) => j.nodes || "—" },
    { key: "cpu",   header: "CPU",       cell: (j) => numOf(j.cpus) },
    { key: "tl",    header: "TimeLimit", cell: (j) => numOf(j.time_limit) },
    {
      key: "act", header: "", align: "right",
      cell: (j) => (
        <div className="flex justify-end gap-1">
          <Button size="sm" variant="ghost" icon={<Pause size={11} />}    onClick={() => setPending({ action: "hold",    job: j })}>hold</Button>
          <Button size="sm" variant="ghost" icon={<Play size={11} />}     onClick={() => setPending({ action: "release", job: j })}>release</Button>
          <Button size="sm" variant="ghost" icon={<RotateCw size={11} />} onClick={() => setPending({ action: "requeue", job: j })}>requeue</Button>
          <Button size="sm" variant="ghost" icon={<X size={11} />}        onClick={() => setPending({ action: "cancel",  job: j })}>cancel</Button>
        </div>
      ),
    },
  ];

  const doAction = async () => {
    if (!pending) return;
    const j = pending.job;
    const id = String(j.job_id);
    await api.post(path(`/jobs/${encodeURIComponent(id)}/${pending.action}`));
    setPending(null);
    reload();
  };

  return (
    <div className="p-4 h-full grid grid-rows-[auto_1fr] gap-3">
      <div className="flex items-center gap-3">
        <input
          placeholder="Filter (name, user, partition, state)…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="flex-1 bg-dark-tertiary border border-border-subtle rounded-sm px-2 py-1.5 font-mono text-xs"
        />
        <Button size="sm" variant="ghost" icon={<RefreshCw size={12} />} onClick={reload} loading={loading}>reload</Button>
      </div>

      <Card title={`Jobs — ${active ?? "no cluster"}`} className="h-full">
        {!active && <EmptyState message="Select a cluster to see the queue." />}
        {error && <ErrorBox message={error} />}
        {active && !error && <Table columns={columns} rows={rows} rowKey={(j, i) => String(j.job_id ?? i)} empty="No matching jobs." />}
      </Card>

      <ConfirmModal
        open={!!pending}
        title={pending ? `${pending.action} job ${pending.job.job_id}?` : ""}
        body={
          <div className="text-xs space-y-1">
            <div><span className="text-text-secondary">user:</span> {pending?.job.user_name}</div>
            <div><span className="text-text-secondary">name:</span> {pending?.job.name}</div>
            <div><span className="text-text-secondary">partition:</span> {pending?.job.partition}</div>
            <div className="text-accent-yellow pt-1">
              {pending?.action === "cancel" && "This signals scancel — the job is gone, not paused."}
              {pending?.action === "hold"   && "Job will be blocked from starting until released."}
            </div>
          </div>
        }
        confirmLabel={pending?.action ?? "Confirm"}
        danger={pending?.action === "cancel"}
        onConfirm={doAction}
        onClose={() => setPending(null)}
      />
    </div>
  );
}
