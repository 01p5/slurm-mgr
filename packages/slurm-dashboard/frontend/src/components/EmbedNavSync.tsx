import { useEffect } from "react";
import { useLocation } from "react-router-dom";


/**
 * Tiny no-op renderer that posts a message to the parent frame on
 * every React Router URL change. Used when slurm-dashboard is
 * embedded under another shell (e.g. Olympus's /capabilities/slurm
 * iframe) — the parent listens for these messages and mirrors the
 * inner path into its own URL bar so a hard refresh restores the
 * user's place inside the iframe.
 *
 * Standalone (no parent frame): the window.parent === window check
 * short-circuits and this hook becomes a no-op.
 *
 * Message shape (validated by the parent):
 *   { type: "embedded-nav", path: "<window.location.pathname>" }
 *
 * Same-origin only (the parent is on the same domain via reverse
 * proxy), so we target window.location.origin explicitly rather
 * than the lax "*".
 */
export function EmbedNavSync(): null {
  const location = useLocation();
  useEffect(() => {
    if (window.parent === window) return;
    window.parent.postMessage(
      {
        type: "embedded-nav",
        path: window.location.pathname,
      },
      window.location.origin,
    );
  }, [location.pathname, location.search]);
  return null;
}
