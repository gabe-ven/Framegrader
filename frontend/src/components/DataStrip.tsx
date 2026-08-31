import type { ReactNode } from "react";
import { Tooltip } from "./Tooltip";

export interface DataStripItem {
  label: string;
  value: ReactNode;
  /** Optional short contextual descriptor shown below the value (e.g. "Moderate detail"). */
  context?: string;
  /** Optional longer explanation surfaced via an info tooltip. */
  hint?: string;
}

interface DataStripProps {
  items: DataStripItem[];
}

function isLastInRow(index: number, total: number, cols: number): boolean {
  return (index + 1) % cols === 0 || index === total - 1;
}

function isLastRow(index: number, total: number, cols: number): boolean {
  const totalRows = Math.ceil(total / cols);
  const currentRow = Math.floor(index / cols);
  return currentRow === totalRows - 1;
}

/** A heavy diagnostic-sheet table: grid-cols-2 on mobile, md:grid-cols-3 on
 * larger screens, wrapped in a thick outer border with thick black rules
 * acting as table-cell dividers between items. */
export function DataStrip({ items }: DataStripProps) {
  return (
    <div className="grid grid-cols-2 border-4 border-black md:grid-cols-3">
      {items.map((item, i) => {
        const classes = [
          "border-black p-4",
          isLastInRow(i, items.length, 2) ? "" : "border-r-4",
          isLastInRow(i, items.length, 3) ? "md:border-r-0" : "md:border-r-4",
          isLastRow(i, items.length, 2) ? "" : "border-b-4",
          isLastRow(i, items.length, 3) ? "md:border-b-0" : "md:border-b-4",
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <div key={item.label} className={classes}>
            <div className="font-mono text-4xl font-black tracking-tighter tabular-nums text-text">
              {item.value}
            </div>
            {item.context && (
              <div className="mt-1 font-sans text-xs text-muted">{item.context}</div>
            )}
            <div className="mt-1 flex items-center gap-1 font-sans text-xs uppercase tracking-widest text-subtle">
              {item.label}
              {item.hint && (
                <Tooltip content={item.hint}>
                  <span
                    tabIndex={0}
                    aria-label={`About ${item.label}`}
                    className="cursor-help normal-case tracking-normal text-subtle transition-colors hover:text-text focus:text-text focus:outline-none"
                  >
                    &#9432;
                  </span>
                </Tooltip>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
