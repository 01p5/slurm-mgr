import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";
type Size = "sm" | "md";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
};

const BASE =
  "inline-flex items-center justify-center gap-1.5 font-display font-medium " +
  "transition-colors disabled:opacity-50 disabled:cursor-not-allowed " +
  "border focus:outline-none focus:ring-1 focus:ring-accent-blue/40";

const VARIANTS: Record<Variant, string> = {
  primary:   "bg-accent-blue/15 text-accent-blue border-accent-blue/30 hover:bg-accent-blue/25",
  secondary: "bg-dark-panel text-text-primary border-border-subtle hover:border-border-active",
  danger:    "bg-accent-red/15 text-accent-red border-accent-red/30 hover:bg-accent-red/25",
  ghost:     "bg-transparent text-text-secondary border-transparent hover:text-text-primary hover:bg-dark-panel",
};

const SIZES: Record<Size, string> = {
  sm: "h-7 px-2.5 text-xs rounded-sm",
  md: "h-9 px-3.5 text-sm rounded-md",
};

export function Button({
  variant = "secondary", size = "md", loading, icon, children, className, ...rest
}: Props) {
  return (
    <button
      className={clsx(BASE, VARIANTS[variant], SIZES[size], className)}
      disabled={loading || rest.disabled}
      {...rest}
    >
      {loading ? (
        <span className="inline-block h-3 w-3 rounded-full border-2 border-current border-t-transparent animate-spin" />
      ) : icon}
      {children}
    </button>
  );
}
