import { useEffect, useState, type ReactNode } from "react";
import { Button } from "./Button";

// Used to gate any destructive op the user clicks (cancel, drain,
// delete partition, etc). The body usually spells out what's about
// to happen so there's no "wait, I meant the other job" foot-gun.

type Props = {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => Promise<void> | void;
  onClose: () => void;
};

export function ConfirmModal({
  open, title, body, confirmLabel = "Confirm", danger = true,
  onConfirm, onClose,
}: Props) {
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}
    >
      <div className="w-full max-w-md bg-dark-secondary border border-border-subtle rounded-md shadow-xl">
        <header className="px-4 py-3 border-b border-border-subtle">
          <h3 className="font-display text-sm font-semibold text-text-primary">{title}</h3>
        </header>
        <div className="px-4 py-3 text-sm text-text-secondary">{body}</div>
        <footer className="px-4 py-3 border-t border-border-subtle flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button
            variant={danger ? "danger" : "primary"}
            loading={busy}
            onClick={async () => {
              setBusy(true);
              try { await onConfirm(); }
              finally { setBusy(false); }
            }}
          >
            {confirmLabel}
          </Button>
        </footer>
      </div>
    </div>
  );
}
