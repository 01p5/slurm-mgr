import clsx from "clsx";
import type { ReactNode } from "react";

export function Card({
  title, actions, children, className,
}: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section
      className={clsx(
        "bg-dark-secondary border border-border-subtle rounded-md overflow-hidden flex flex-col",
        className,
      )}
    >
      {(title || actions) && (
        <header className="flex items-center justify-between px-3 py-2 border-b border-border-subtle bg-dark-tertiary">
          <h2 className="font-display text-[13px] font-semibold text-text-primary uppercase tracking-[0.5px]">
            {title}
          </h2>
          {actions && <div className="flex items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className="flex-1 min-h-0 overflow-auto">{children}</div>
    </section>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="h-full grid place-items-center text-text-muted font-mono text-xs px-6 text-center">
      {message}
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="m-3 p-3 bg-accent-red/10 border border-accent-red/30 rounded-sm font-mono text-xs text-accent-red whitespace-pre-wrap">
      {message}
    </div>
  );
}
