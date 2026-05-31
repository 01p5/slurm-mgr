import { NavLink, Outlet } from "react-router-dom";
import {
  Server, ListChecks, Layers, CalendarClock, Users, BarChart3,
  ScaleIcon, Activity, Cog, Cpu, Plug,
} from "lucide-react";
import clsx from "clsx";
import { useClusters } from "../ClusterContext";

const TABS = [
  { to: "/hosts",        label: "Hosts",        icon: Plug },
  { to: "/nodes",        label: "Nodes",        icon: Cpu },
  { to: "/jobs",         label: "Jobs",         icon: ListChecks },
  { to: "/partitions",   label: "Partitions",   icon: Layers },
  { to: "/reservations", label: "Reservations", icon: CalendarClock },
  { to: "/accounts",     label: "Accounts",     icon: Users },
  { to: "/accounting",   label: "Accounting",   icon: BarChart3 },
  { to: "/fairshare",    label: "Fairshare",    icon: ScaleIcon },
  { to: "/diagnostics",  label: "Diagnostics",  icon: Activity },
  { to: "/cluster",      label: "Cluster",      icon: Cog },
];

export function Layout() {
  const { clusters, active, setActive } = useClusters();

  return (
    <div className="h-full grid grid-rows-[auto_1fr]">
      {/* Topnav */}
      <header className="bg-dark-secondary/80 backdrop-blur-xl border-b border-border-subtle">
        <div className="flex items-center h-14 px-5 gap-6">
          <div className="flex items-baseline gap-2">
            <Server size={18} className="text-accent-purple self-center" />
            <span className="font-display text-base font-bold text-text-primary tracking-tight">
              slurm-mgr
            </span>
            <span className="text-[10px] uppercase tracking-[1.5px] text-text-muted font-mono">
              hpc console
            </span>
          </div>
          <nav className="flex gap-0.5 ml-2 overflow-x-auto">
            {TABS.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  clsx(
                    "flex items-center gap-1.5 px-2.5 py-1.5 rounded-sm text-xs whitespace-nowrap transition-colors border border-transparent",
                    // Accent-tinted active + hover so the slurm-mgr
                    // nav feels distinctively purple — earlier the
                    // styles were generic dark-panel + text-primary,
                    // which made it indistinguishable from the
                    // Olympus shell when embedded under it.
                    isActive
                      ? "bg-accent-purple/10 text-accent-purple border-accent-purple/40"
                      : "text-text-secondary hover:text-accent-purple hover:bg-accent-purple/[0.06]",
                  )
                }
              >
                <Icon size={16} strokeWidth={2.5} />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="flex-1" />
          <ClusterPicker
            clusters={clusters.map((c) => c.name)}
            active={active}
            onPick={setActive}
          />
        </div>
      </header>

      <main className="min-h-0 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}

function ClusterPicker({
  clusters, active, onPick,
}: { clusters: string[]; active: string | null; onPick: (n: string) => void }) {
  if (clusters.length === 0) {
    return (
      <span className="text-xs font-mono text-text-muted">
        no clusters — add one on <NavLink to="/hosts" className="text-accent-purple">Hosts</NavLink>
      </span>
    );
  }
  return (
    <label className="flex items-center gap-2 text-xs font-mono text-text-secondary">
      cluster
      <select
        value={active ?? ""}
        onChange={(e) => onPick(e.target.value)}
        className="bg-dark-panel border border-border-subtle rounded-sm px-2 py-1 text-text-primary focus:outline-none focus:border-border-active"
      >
        {clusters.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
    </label>
  );
}
