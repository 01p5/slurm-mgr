import { useMemo, useState } from "react";
import { RefreshCw, Search } from "lucide-react";
import { Card, EmptyState, ErrorBox } from "../components/Card";
import { Button } from "../components/Button";
import { Badge, stateTone } from "../components/Badge";
import { Table, type Column } from "../components/Table";
import { useFetch } from "../hooks";
import { useClusters, useClusterPath } from "../ClusterContext";
import { api } from "../api";

type SacctJob = {
  job_id?: number;
  name?: string;
  user?: string;
  account?: string;
  state?: { current?: string[] };
  time?: { elapsed?: number; submission?: number };
  partition?: string;
};

export function AccountingPage() {
  const { active } = useClusters();
  const path = useClusterPath();
  const [filters, setFilters] = useState({ starttime: "", endtime: "", users: "", accounts: "", states: "" });
  const [reportArgs, setReportArgs] = useState("");
  const [reportOut, setReportOut] = useState("");
  const [reportBusy, setReportBusy] = useState(false);
  const [reportErr, setReportErr] = useState<string | null>(null);

  const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v)).toString();
  const url = active ? path(`/accounting${q ? `?${q}` : ""}`) : null;
  const { data, error, loading, reload } = useFetch<{ jobs?: SacctJob[] }>(url, 0);
  const rows = useMemo<SacctJob[]>(() => data?.jobs ?? [], [data]);

  const stateOf = (j: SacctJob): string => j.state?.current?.[0] ?? "";
  const columns: Column<SacctJob>[] = [
    { key: "id",    header: "Job",    cell: (j) => <span className="text-accent-blue">{String(j.job_id)}</span> },
    { key: "name",  header: "Name",   cell: (j) => j.name ?? "—" },
    { key: "user",  header: "User",   cell: (j) => j.user ?? "—" },
    { key: "acct",  header: "Account", cell: (j) => j.account ?? "—" },
    { key: "part",  header: "Partition", cell: (j) => j.partition ?? "—" },
    { key: "state", header: "Final state", cell: (j) => <Badge tone={stateTone(stateOf(j))}>{stateOf(j) || "?"}</Badge> },
    { key: "el",    header: "Elapsed (s)", align: "right", cell: (j) => j.time?.elapsed ?? "—" },
    { key: "sub",   header: "Submitted",  cell: (j) => j.time?.submission ? new Date(j.time.submission * 1000).toISOString().slice(0, 16).replace("T", " ") : "—" },
  ];

  const runReport = async () => {
    setReportBusy(true); setReportErr(null);
    try {
      const r = await api.get<{ stdout: string }>(path(`/sreport?args=${encodeURIComponent(reportArgs)}`));
      setReportOut(r.stdout);
    } catch (e) {
      setReportErr(e instanceof Error ? e.message : String(e));
    } finally {
      setReportBusy(false);
    }
  };

  const field = (k: keyof typeof filters, ph: string) => (
    <input
      placeholder={ph}
      value={filters[k]}
      onChange={(e) => setFilters({ ...filters, [k]: e.target.value })}
      className="bg-dark-tertiary border border-border-subtle rounded-sm px-2 py-1 font-mono text-xs min-w-0"
    />
  );

  return (
    <div className="p-4 h-full grid grid-rows-[auto_1fr_auto] gap-3 min-h-0">
      <div className="grid grid-cols-6 gap-2">
        {field("starttime", "starttime (e.g. 2026-05-01)")}
        {field("endtime",   "endtime")}
        {field("users",     "users (csv)")}
        {field("accounts",  "accounts (csv)")}
        {field("states",    "states (CD,F,CA,...)")}
        <Button variant="ghost" icon={<RefreshCw size={14} strokeWidth={2.25} />} onClick={reload} loading={loading}>run sacct</Button>
      </div>

      <Card title={`sacct — ${active ?? "no cluster"}`} className="h-full">
        {!active && <EmptyState message="Select a cluster." />}
        {error && <ErrorBox message={error} />}
        {active && !error && <Table columns={columns} rows={rows} rowKey={(j, i) => String(j.job_id ?? i)} empty="No matching records." />}
      </Card>

      <Card title="sreport">
        <div className="px-3 py-2 flex gap-2">
          <input
            value={reportArgs}
            onChange={(e) => setReportArgs(e.target.value)}
            placeholder='e.g. cluster utilization start=2026-05-01 end=2026-05-25'
            className="flex-1 bg-dark-tertiary border border-border-subtle rounded-sm px-2 py-1 font-mono text-xs"
          />
          <Button variant="primary" icon={<Search size={14} strokeWidth={2.25} />} onClick={runReport} loading={reportBusy}>run</Button>
        </div>
        {reportErr && <ErrorBox message={reportErr} />}
        {reportOut && (
          <pre className="px-3 py-2 font-mono text-[11px] text-text-secondary whitespace-pre overflow-auto">
            {reportOut}
          </pre>
        )}
      </Card>
    </div>
  );
}
