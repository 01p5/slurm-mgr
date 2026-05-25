import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { Card, EmptyState, ErrorBox } from "../components/Card";
import { Button } from "../components/Button";
import { useFetch } from "../hooks";
import { useClusters, useClusterPath } from "../ClusterContext";

export function DiagnosticsPage() {
  const { active } = useClusters();
  const path = useClusterPath();
  const { data, error, loading, reload } = useFetch<Record<string, unknown>>(active ? path("/diag") : null, 15_000);
  const [jobid, setJobid] = useState("");
  const sstat = useFetch<Record<string, unknown>>(active && jobid ? path(`/sstat?jobid=${encodeURIComponent(jobid)}`) : null, 0);

  return (
    <div className="p-4 h-full grid grid-rows-2 gap-3 min-h-0">
      <Card
        title={`sdiag — ${active ?? "no cluster"}`}
        actions={<Button size="sm" variant="ghost" icon={<RefreshCw size={12} />} onClick={reload} loading={loading}>reload</Button>}
      >
        {!active && <EmptyState message="Select a cluster." />}
        {error && <ErrorBox message={error} />}
        {data && <JsonView value={data} />}
      </Card>

      <Card title={`sstat — ${active ?? "no cluster"}`}>
        <div className="px-3 py-2 flex gap-2 border-b border-border-subtle">
          <input
            value={jobid}
            onChange={(e) => setJobid(e.target.value)}
            placeholder="JobID (e.g. 12345 or 12345.batch)"
            className="flex-1 bg-dark-tertiary border border-border-subtle rounded-sm px-2 py-1 font-mono text-xs"
          />
          <Button size="sm" variant="primary" onClick={sstat.reload} loading={sstat.loading} disabled={!jobid}>fetch</Button>
        </div>
        {sstat.error && <ErrorBox message={sstat.error} />}
        {sstat.data && <JsonView value={sstat.data} />}
      </Card>
    </div>
  );
}

export function JsonView({ value }: { value: unknown }) {
  return (
    <pre className="px-3 py-2 font-mono text-[11px] text-text-secondary whitespace-pre overflow-auto">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
