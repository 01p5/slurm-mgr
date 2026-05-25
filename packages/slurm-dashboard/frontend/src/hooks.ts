import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

// Simple "fetch JSON from `path`, re-fetch on demand, autoload on
// mount, return {data, error, loading, reload}" hook. Nothing fancy —
// no SWR-style caching. The dashboard's data is fresh-or-bust.

export function useFetch<T>(path: string | null, refreshMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const lastPath = useRef<string | null>(null);

  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.get<T>(path);
      setData(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    if (path !== lastPath.current) {
      lastPath.current = path;
      setData(null);
    }
    reload();
  }, [path, reload]);

  useEffect(() => {
    if (!refreshMs || !path) return;
    const id = window.setInterval(reload, refreshMs);
    return () => window.clearInterval(id);
  }, [refreshMs, path, reload]);

  return { data, error, loading, reload };
}
