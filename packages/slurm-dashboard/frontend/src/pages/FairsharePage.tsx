import { RefreshCw } from "lucide-react";
import { Card, EmptyState, ErrorBox } from "../components/Card";
import { Button } from "../components/Button";
import { Table, type Column } from "../components/Table";
import { useFetch } from "../hooks";
import { useClusters, useClusterPath } from "../ClusterContext";

type Share = {
  account?: string;
  user?: string;
  raw_shares?: number;
  norm_shares?: number;
  usage?: { raw?: number; normalized?: number };
  effective_usage?: { raw?: number; normalized?: number };
  fairshare?: { factor?: number };
};

type Prio = {
  job_id?: number;
  user?: string;
  priority?: { number?: number };
  partition?: string;
  age?: { number?: number };
  fair_share?: { number?: number };
  qos?: { number?: number };
};

export function FairsharePage() {
  const { active } = useClusters();
  const path = useClusterPath();

  const shareQ = useFetch<{ shares?: Share[] }>(active ? path("/sshare") : null, 30_000);
  const prioQ  = useFetch<{ priorities?: Prio[] }>(active ? path("/sprio") : null, 30_000);

  const numOf = (v: unknown): string =>
    typeof v === "object" && v && "number" in v ? String((v as {number?:number}).number ?? "—") : (v == null ? "—" : String(v));

  const shareColumns: Column<Share>[] = [
    { key: "acct",  header: "Account",   cell: (s) => s.account ?? "—" },
    { key: "user",  header: "User",      cell: (s) => s.user || "—" },
    { key: "raw",   header: "RawShares", align: "right", cell: (s) => s.raw_shares ?? "—" },
    { key: "norm",  header: "NormShares", align: "right", cell: (s) => s.norm_shares?.toFixed?.(4) ?? "—" },
    { key: "usage", header: "Usage", align: "right", cell: (s) => s.effective_usage?.normalized?.toFixed?.(4) ?? "—" },
    { key: "factor", header: "Factor", align: "right", cell: (s) => s.fairshare?.factor?.toFixed?.(4) ?? "—" },
  ];

  const prioColumns: Column<Prio>[] = [
    { key: "id", header: "Job", cell: (p) => String(p.job_id) },
    { key: "user", header: "User", cell: (p) => p.user ?? "—" },
    { key: "part", header: "Partition", cell: (p) => p.partition ?? "—" },
    { key: "prio", header: "Priority", align: "right", cell: (p) => numOf(p.priority) },
    { key: "age",  header: "Age",      align: "right", cell: (p) => numOf(p.age) },
    { key: "fs",   header: "Fairshare", align: "right", cell: (p) => numOf(p.fair_share) },
    { key: "qos",  header: "QoS",      align: "right", cell: (p) => numOf(p.qos) },
  ];

  return (
    <div className="p-4 h-full grid grid-rows-2 gap-4 min-h-0">
      <Card
        title={`sshare — ${active ?? "no cluster"}`}
        actions={<Button size="sm" variant="ghost" icon={<RefreshCw size={12} />} onClick={shareQ.reload} loading={shareQ.loading}>reload</Button>}
      >
        {!active && <EmptyState message="Select a cluster." />}
        {shareQ.error && <ErrorBox message={shareQ.error} />}
        {active && !shareQ.error && (
          <Table columns={shareColumns} rows={shareQ.data?.shares ?? []} rowKey={(s, i) => `${s.account}-${s.user}-${i}`} empty="No share rows." />
        )}
      </Card>

      <Card
        title={`sprio — ${active ?? "no cluster"}`}
        actions={<Button size="sm" variant="ghost" icon={<RefreshCw size={12} />} onClick={prioQ.reload} loading={prioQ.loading}>reload</Button>}
      >
        {!active && <EmptyState message="Select a cluster." />}
        {prioQ.error && <ErrorBox message={prioQ.error} />}
        {active && !prioQ.error && (
          <Table columns={prioColumns} rows={prioQ.data?.priorities ?? []} rowKey={(p, i) => String(p.job_id ?? i)} empty="No pending jobs." />
        )}
      </Card>
    </div>
  );
}
