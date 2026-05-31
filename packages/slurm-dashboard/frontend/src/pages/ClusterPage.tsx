import { RefreshCw, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Card, EmptyState, ErrorBox } from "../components/Card";
import { Button } from "../components/Button";
import { ConfirmModal } from "../components/ConfirmModal";
import { JsonView } from "./DiagnosticsPage";
import { useFetch } from "../hooks";
import { useClusters, useClusterPath } from "../ClusterContext";
import { api } from "../api";

export function ClusterPage() {
  const { active } = useClusters();
  const path = useClusterPath();
  const { data, error, loading, reload } = useFetch<Record<string, unknown>>(active ? path("/config") : null, 0);
  const [reconfirm, setReconfirm] = useState(false);

  return (
    <div className="p-4 h-full grid grid-rows-[auto_1fr] gap-3 min-h-0">
      <Card
        title={`Controller actions — ${active ?? "no cluster"}`}
      >
        <div className="p-3 flex items-center gap-3">
          <Button
            variant="danger" icon={<RotateCcw size={14} strokeWidth={2.25} />}
            onClick={() => setReconfirm(true)} disabled={!active}
          >
            scontrol reconfigure
          </Button>
          <span className="text-xs text-text-secondary">
            Tells the controller to re-read <code>slurm.conf</code>. Usually safe, but it's a config rollout.
          </span>
        </div>
      </Card>

      <Card
        title={`scontrol show config — ${active ?? "no cluster"}`}
        className="h-full"
        actions={<Button size="sm" variant="ghost" icon={<RefreshCw size={14} strokeWidth={2.25} />} onClick={reload} loading={loading}>reload</Button>}
      >
        {!active && <EmptyState message="Select a cluster." />}
        {error && <ErrorBox message={error} />}
        {data && <JsonView value={data} />}
      </Card>

      <ConfirmModal
        open={reconfirm}
        title="Reconfigure controller?"
        body={<span>Issues <code>scontrol reconfigure</code> on <code className="text-text-primary">{active}</code>.</span>}
        confirmLabel="Reconfigure"
        onConfirm={async () => { await api.post(path("/reconfigure")); setReconfirm(false); }}
        onClose={() => setReconfirm(false)}
      />
    </div>
  );
}
