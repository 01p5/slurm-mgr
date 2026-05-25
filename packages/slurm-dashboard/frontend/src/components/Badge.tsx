import clsx from "clsx";
import type { ReactNode } from "react";

type Tone = "neutral" | "green" | "red" | "yellow" | "blue" | "orange" | "purple";

const TONES: Record<Tone, string> = {
  neutral: "bg-dark-panel text-text-secondary border-border-subtle",
  green:   "bg-accent-green/10 text-accent-green border-accent-green/25",
  red:     "bg-accent-red/10 text-accent-red border-accent-red/25",
  yellow:  "bg-accent-yellow/10 text-accent-yellow border-accent-yellow/25",
  blue:    "bg-accent-blue/10 text-accent-blue border-accent-blue/25",
  orange:  "bg-accent-orange/10 text-accent-orange border-accent-orange/25",
  purple:  "bg-accent-purple/10 text-accent-purple border-accent-purple/25",
};

export function Badge({
  tone = "neutral", children, className,
}: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center px-1.5 py-0.5 text-[10.5px] font-mono uppercase tracking-[0.5px] rounded-sm border",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

// Slurm node/job state → tone. Best-effort; falls back to neutral.
export function stateTone(state: string | undefined): Tone {
  if (!state) return "neutral";
  const s = state.toUpperCase();
  if (s.includes("DOWN") || s.includes("FAIL") || s.includes("ERROR") || s.includes("CANCEL")) return "red";
  if (s.includes("DRAIN") || s.includes("RESERV") || s.includes("PENDING")) return "yellow";
  if (s.includes("IDLE") || s.includes("COMPLET") || s.includes("RUNNING")) return "green";
  if (s.includes("ALLOC") || s.includes("MIXED")) return "blue";
  if (s.includes("MAINT")) return "orange";
  return "neutral";
}
