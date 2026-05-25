import clsx from "clsx";
import type { ReactNode } from "react";

export type Column<T> = {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  width?: string;        // e.g. "w-32"
  align?: "left" | "right" | "center";
};

type Props<T> = {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, i: number) => string;
  empty?: string;
};

export function Table<T>({ columns, rows, rowKey, empty }: Props<T>) {
  if (rows.length === 0) {
    return (
      <div className="h-full grid place-items-center text-text-muted font-mono text-xs">
        {empty ?? "no rows"}
      </div>
    );
  }
  return (
    <div className="w-full">
      <table className="w-full font-mono text-xs">
        <thead className="sticky top-0 bg-dark-tertiary z-10">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={clsx(
                  "text-left font-semibold text-text-secondary uppercase tracking-[0.5px] px-3 py-2 border-b border-border-subtle",
                  c.width,
                  c.align === "right" && "text-right",
                  c.align === "center" && "text-center",
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={rowKey(r, i)}
              className="hover:bg-dark-panel/60 transition-colors border-b border-border-subtle/50"
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={clsx(
                    "px-3 py-2 text-text-primary align-top",
                    c.align === "right" && "text-right",
                    c.align === "center" && "text-center",
                  )}
                >
                  {c.cell(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
