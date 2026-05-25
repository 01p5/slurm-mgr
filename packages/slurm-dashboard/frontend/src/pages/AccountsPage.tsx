import { useState } from "react";
import { RefreshCw, Trash2, Plus, Pencil } from "lucide-react";
import { Card, EmptyState, ErrorBox } from "../components/Card";
import { Button } from "../components/Button";
import { Table, type Column } from "../components/Table";
import { ConfirmModal } from "../components/ConfirmModal";
import { KVEditorModal } from "./PartitionsPage";
import { useFetch } from "../hooks";
import { useClusters, useClusterPath } from "../ClusterContext";
import { api } from "../api";

type Tab = "account" | "user" | "assoc" | "qos";
const TABS: { id: Tab; label: string; path: string; endpoint: string }[] = [
  { id: "account", label: "Accounts", path: "/accounts", endpoint: "accounts" },
  { id: "user",    label: "Users",    path: "/users",    endpoint: "users" },
  { id: "assoc",   label: "Assocs",   path: "/assocs",   endpoint: "" },     // read-only here
  { id: "qos",     label: "QoS",      path: "/qos",      endpoint: "qos" },
];

export function AccountsPage() {
  const { active } = useClusters();
  const path = useClusterPath();
  const [tab, setTab] = useState<Tab>("account");
  const meta = TABS.find((t) => t.id === tab)!;

  const { data, error, loading, reload } = useFetch<{ rows: Record<string, string>[] }>(
    active ? path(meta.path) : null, 0,
  );
  const [del, setDel] = useState<string | null>(null);
  const [edit, setEdit] = useState<{ mode: "create" | "edit"; name: string } | null>(null);

  const rows = data?.rows ?? [];
  const headers = rows[0] ? Object.keys(rows[0]) : [];

  const columns: Column<Record<string, string>>[] = [
    ...headers.map((h) => ({
      key: h, header: h, cell: (r: Record<string, string>) => r[h] || "—",
    })),
    ...(meta.endpoint ? [{
      key: "act", header: "", align: "right" as const,
      cell: (r: Record<string, string>) => {
        const name = r[headers[0]];
        return (
          <div className="flex justify-end gap-1">
            <Button size="sm" variant="ghost" icon={<Pencil size={11} />} onClick={() => setEdit({ mode: "edit", name })}>edit</Button>
            <Button size="sm" variant="ghost" icon={<Trash2 size={11} />} onClick={() => setDel(name)}>delete</Button>
          </div>
        );
      },
    }] : []),
  ];

  return (
    <div className="p-4 h-full grid grid-rows-[auto_1fr] gap-3">
      <div className="flex items-center gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-xs font-display rounded-sm border transition-colors ${
              tab === t.id
                ? "bg-dark-panel text-text-primary border-border-subtle"
                : "bg-transparent text-text-secondary border-transparent hover:text-text-primary"
            }`}
          >
            {t.label}
          </button>
        ))}
        <div className="flex-1" />
        <Button size="sm" variant="ghost" icon={<RefreshCw size={12} />} onClick={reload} loading={loading}>reload</Button>
        {meta.endpoint && (
          <Button size="sm" variant="primary" icon={<Plus size={12} />} onClick={() => setEdit({ mode: "create", name: "" })}>
            new {meta.id}
          </Button>
        )}
      </div>

      <Card title={`${meta.label} — ${active ?? "no cluster"}`} className="h-full">
        {!active && <EmptyState message="Select a cluster." />}
        {error && <ErrorBox message={error} />}
        {active && !error && <Table columns={columns} rows={rows} rowKey={(r, i) => r[headers[0]] ?? String(i)} empty="No rows." />}
      </Card>

      <ConfirmModal
        open={!!del}
        title={`Delete ${meta.id} ${del}?`}
        body={<span>This invokes <code>sacctmgr -i delete {meta.id}</code>. Slurm will reject if there are dependent records.</span>}
        confirmLabel="Delete"
        onConfirm={async () => { await api.delete(path(`/${meta.endpoint}/${encodeURIComponent(del!)}`)); setDel(null); reload(); }}
        onClose={() => setDel(null)}
      />

      <KVEditorModal
        open={!!edit && !!meta.endpoint}
        title={edit?.mode === "create" ? `Create ${meta.id}` : `Edit ${meta.id} ${edit?.name}`}
        nameLabel={edit?.mode === "create" ? `${meta.id} name` : null}
        defaultName={edit?.name ?? ""}
        defaultFields={
          edit?.mode === "create" && meta.id === "account" ? "Description=...\nOrganization=..." :
          edit?.mode === "create" && meta.id === "user"    ? "account=...\nDefaultAccount=...\nAdminLevel=None" :
          edit?.mode === "create" && meta.id === "qos"     ? "Priority=0\nMaxJobsPerUser=10" :
          ""
        }
        confirmLabel={edit?.mode === "create" ? "Create" : "Update"}
        onClose={() => setEdit(null)}
        onConfirm={async (name, kv) => {
          if (edit?.mode === "create") {
            await api.post(path(`/${meta.endpoint}`), { name, ...kv });
          } else {
            await api.patch(path(`/${meta.endpoint}/${encodeURIComponent(name)}`), kv);
          }
          setEdit(null); reload();
        }}
      />
    </div>
  );
}
