import { useMemo, useState } from "react";
import { RefreshCw, Trash2, Plus, Pencil } from "lucide-react";
import { Card, EmptyState, ErrorBox } from "../components/Card";
import { Button } from "../components/Button";
import { Badge, stateTone } from "../components/Badge";
import { Table, type Column } from "../components/Table";
import { ConfirmModal } from "../components/ConfirmModal";
import { KVEditorModal } from "./PartitionsPage";
import { useFetch } from "../hooks";
import { useClusters, useClusterPath } from "../ClusterContext";
import { api } from "../api";

type Reservation = {
  name?: string;
  start_time?: { number?: number };
  end_time?: { number?: number };
  state?: string;
  users?: string;
  accounts?: string;
  nodes?: string;
  partition?: string;
};

const fmtTime = (t: unknown): string => {
  if (typeof t !== "object" || !t) return "—";
  const n = (t as {number?:number}).number;
  if (!n) return "—";
  return new Date(n * 1000).toISOString().replace("T", " ").slice(0, 16);
};

export function ReservationsPage() {
  const { active } = useClusters();
  const path = useClusterPath();
  const { data, error, loading, reload } = useFetch<{ reservations?: Reservation[] }>(active ? path("/reservations") : null, 30_000);
  const [del, setDel] = useState<string | null>(null);
  const [edit, setEdit] = useState<{ mode: "create" | "edit"; name: string } | null>(null);

  const rows = useMemo<Reservation[]>(() => data?.reservations ?? [], [data]);

  const columns: Column<Reservation>[] = [
    { key: "name",  header: "Name",  cell: (r) => r.name ?? "?" },
    { key: "state", header: "State", cell: (r) => <Badge tone={stateTone(r.state)}>{r.state ?? "?"}</Badge> },
    { key: "start", header: "Start", cell: (r) => fmtTime(r.start_time) },
    { key: "end",   header: "End",   cell: (r) => fmtTime(r.end_time) },
    { key: "users", header: "Users", cell: (r) => r.users || "—" },
    { key: "accts", header: "Accounts", cell: (r) => r.accounts || "—" },
    { key: "nodes", header: "Nodes", cell: (r) => r.nodes || "—" },
    { key: "part",  header: "Partition", cell: (r) => r.partition || "—" },
    {
      key: "act", header: "", align: "right",
      cell: (r) => (
        <div className="flex justify-end gap-1">
          <Button size="sm" variant="ghost" icon={<Pencil size={11} />} onClick={() => setEdit({ mode: "edit", name: r.name! })}>edit</Button>
          <Button size="sm" variant="ghost" icon={<Trash2 size={11} />} onClick={() => setDel(r.name ?? "")}>delete</Button>
        </div>
      ),
    },
  ];

  return (
    <div className="p-4 h-full">
      <Card
        title={`Reservations — ${active ?? "no cluster"}`}
        className="h-full"
        actions={
          <>
            <Button size="sm" variant="ghost" icon={<RefreshCw size={14} strokeWidth={2.25} />} onClick={reload} loading={loading}>reload</Button>
            <Button size="sm" variant="primary" icon={<Plus size={14} strokeWidth={2.25} />} onClick={() => setEdit({ mode: "create", name: "" })}>new</Button>
          </>
        }
      >
        {!active && <EmptyState message="Select a cluster." />}
        {error && <ErrorBox message={error} />}
        {active && !error && <Table columns={columns} rows={rows} rowKey={(r, i) => r.name ?? String(i)} empty="No reservations." />}
      </Card>

      <ConfirmModal
        open={!!del}
        title={`Delete reservation ${del}?`}
        body={<span>Frees the reserved nodes immediately.</span>}
        confirmLabel="Delete"
        onConfirm={async () => { await api.delete(path(`/reservations/${encodeURIComponent(del!)}`)); setDel(null); reload(); }}
        onClose={() => setDel(null)}
      />

      <KVEditorModal
        open={!!edit}
        title={edit?.mode === "create" ? "Create reservation" : `Edit ${edit?.name}`}
        nameLabel={edit?.mode === "create" ? "ReservationName" : null}
        defaultName={edit?.name ?? ""}
        defaultFields={edit?.mode === "create"
          ? "StartTime=now\nDuration=01:00:00\nUsers=root\nFlags=DAILY"
          : ""}
        confirmLabel={edit?.mode === "create" ? "Create" : "Update"}
        onClose={() => setEdit(null)}
        onConfirm={async (name, kv) => {
          if (edit?.mode === "create") {
            // Reservation create endpoint takes ReservationName plus arbitrary fields.
            await api.post(path("/reservations"), { ReservationName: name, ...kv });
          } else {
            await api.patch(path(`/reservations/${encodeURIComponent(name)}`), kv);
          }
          setEdit(null); reload();
        }}
      />
    </div>
  );
}
