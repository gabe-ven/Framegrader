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

/** Anchor each tooltip toward the inside of the screen: in the 2-column phone
 * layout the left column opens rightwards and the right column leftwards; at
 * md's 3 columns every cell is wide enough to centre. */
function tooltipPlacement(index: number): string {
  const edge = index % 2 === 0 ? "left-0" : "right-0";
  return `${edge} md:left-1/2 md:right-auto md:-translate-x-1/2`;
}

/** A heavy diagnostic-sheet table: grid-cols-2 on mobile, md:grid-cols-3 on
 * larger screens, wrapped in a thick outer border with thick black rules
 * acting as table-cell dividers between items. */
export function DataStrip({ items }: DataStripProps) {
  return (
    <div className="grid grid-cols-2 border-4 border-black md:grid-cols-3">
      {items.map((item, i) => {
        const classes = [
          // min-w-0 lets a long value ("6384 × 4160") wrap inside its cell
          // instead of forcing the column wider than half a phone screen.
          "min-w-0 border-black p-4",
          isLastInRow(i, items.length, 2) ? "" : "border-r-4",
          isLastInRow(i, items.length, 3) ? "md:border-r-0" : "md:border-r-4",
          isLastRow(i, items.length, 2) ? "" : "border-b-4",
          isLastRow(i, items.length, 3) ? "md:border-b-0" : "md:border-b-4",
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <div key={item.label} className={classes}>
            {/* 4xl from sm up, as designed; at phone width two 4xl values
                side by side don't fit, and "Landscape" ran into the
                dimensions in the next cell. */}
            <div className="break-words font-mono text-2xl font-black tracking-tighter tabular-nums text-text sm:text-4xl">
              {item.value}
            </div>
            {item.context && (
              <div className="mt-1 font-sans text-xs text-muted">{item.context}</div>
            )}
            <div className="mt-1 flex items-center gap-1 font-sans text-xs uppercase tracking-widest text-subtle">
              {item.label}
              {item.hint && (
                <Tooltip content={item.hint} placement={tooltipPlacement(i)}>
                  {/* On touch screens the 12px glyph gets a 44px hit area;
                      the negative margins cancel the extra size so the row's
                      layout doesn't move. */}
                  <span
                    tabIndex={0}
                    aria-label={`About ${item.label}`}
                    className="cursor-help normal-case tracking-normal text-subtle transition-colors hover:text-text focus:text-text focus:outline-none pointer-coarse:-mx-4 pointer-coarse:-my-[14px] pointer-coarse:inline-flex pointer-coarse:size-11 pointer-coarse:items-center pointer-coarse:justify-center"
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
