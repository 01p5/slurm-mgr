import {
  createContext, useContext, useEffect, useState, useCallback,
  type ReactNode,
} from "react";
import { api, type ClusterSummary } from "./api";

// The active cluster is the prefix for every API call from every
// page. Stored in localStorage so a refresh doesn't reset it.

const STORAGE_KEY = "slurm-mgr.activeCluster";

type Ctx = {
  clusters: ClusterSummary[];
  active: string | null;
  setActive: (name: string) => void;
  reload: () => Promise<void>;
  loading: boolean;
  error: string | null;
};

const ClusterCtx = createContext<Ctx | null>(null);

export function ClusterProvider({ children }: { children: ReactNode }) {
  const [clusters, setClusters] = useState<ClusterSummary[]>([]);
  const [active, setActiveState] = useState<string | null>(
    () => localStorage.getItem(STORAGE_KEY),
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.get<{ clusters: ClusterSummary[] }>("/clusters");
      setClusters(r.clusters);
      // Default to the first cluster if nothing is selected or if the
      // currently-selected one has been removed.
      if (r.clusters.length > 0 && !r.clusters.find((c) => c.name === active)) {
        setActiveState(r.clusters[0].name);
        localStorage.setItem(STORAGE_KEY, r.clusters[0].name);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [active]);

  const setActive = (name: string) => {
    setActiveState(name);
    localStorage.setItem(STORAGE_KEY, name);
  };

  useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ClusterCtx.Provider value={{ clusters, active, setActive, reload, loading, error }}>
      {children}
    </ClusterCtx.Provider>
  );
}

export function useClusters(): Ctx {
  const c = useContext(ClusterCtx);
  if (!c) throw new Error("useClusters must be used inside <ClusterProvider>");
  return c;
}

export function useClusterPath(): (suffix: string) => string {
  const { active } = useClusters();
  return (suffix) => {
    if (!active) return suffix;
    return `/clusters/${encodeURIComponent(active)}${suffix.startsWith("/") ? suffix : "/" + suffix}`;
  };
}
