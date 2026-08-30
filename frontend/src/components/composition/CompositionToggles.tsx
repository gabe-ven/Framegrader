import { motion } from "framer-motion";
import type { OverlayToggles } from "./CompositionOverlay";

const PILL_SPRING = { type: "spring" as const, stiffness: 400, damping: 30 };

interface ToggleDef {
  key: keyof OverlayToggles;
  label: string;
  available: boolean;
}

interface CompositionTogglesProps {
  toggles: OverlayToggles;
  onToggle: (key: keyof OverlayToggles) => void;
  linesAvailable: boolean;
  horizonAvailable: boolean;
  /** "pills" (default) — a horizontal wrap of bordered pills. "rows" — a
   * stacked, full-width list with a filled/outline square per toggle. */
  variant?: "pills" | "rows";
}

/** The overlay-layer toggle control, shared by every place that hosts a
 * CompositionOverlayLayers instance. */
export function CompositionToggles({
  toggles,
  onToggle,
  linesAvailable,
  horizonAvailable,
  variant = "pills",
}: CompositionTogglesProps) {
  const toggleDefs: ToggleDef[] = [
    { key: "thirds", label: "Rule of thirds", available: true },
    { key: "subject", label: "Subject", available: true },
    { key: "lines", label: "Leading lines", available: linesAvailable },
    { key: "horizon", label: "Horizon", available: horizonAvailable },
    { key: "edges", label: "Edges", available: true },
  ];

  if (variant === "rows") {
    return (
      <div className="flex flex-wrap gap-4">
        {toggleDefs.map((def) => {
          const active = toggles[def.key];
          const on = def.available && active;
          return (
            <button
              key={def.key}
              type="button"
              disabled={!def.available}
              onClick={() => onToggle(def.key)}
              className={`flex items-center gap-2 font-mono text-xs uppercase tracking-widest transition-colors ${
                !def.available
                  ? "cursor-not-allowed text-subtle"
                  : active
                    ? "text-text"
                    : "text-subtle hover:text-text"
              }`}
            >
              <span
                className={`inline-block h-3 w-3 shrink-0 border border-current ${on ? "bg-current" : ""}`}
              />
              <span>{def.label}</span>
              {!def.available && <span className="text-subtle">(none)</span>}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {toggleDefs.map((def) => {
        const active = toggles[def.key];
        return (
          <motion.button
            key={def.key}
            type="button"
            disabled={!def.available}
            onClick={() => onToggle(def.key)}
            whileHover={def.available ? { scale: 0.98 } : undefined}
            whileTap={def.available ? { scale: 0.95 } : undefined}
            transition={PILL_SPRING}
            className={`flex items-center gap-2 border px-3 py-1.5 font-mono text-[10px] uppercase tracking-wide transition-colors ${
              !def.available
                ? "cursor-not-allowed border-border text-subtle"
                : active
                  ? "border-text bg-text text-bg"
                  : "border-border text-muted hover:border-border-strong"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 bg-current ${!def.available || !active ? "opacity-30" : ""}`}
            />
            {def.label}
            {!def.available && <span className="text-[9px] text-subtle">(none)</span>}
          </motion.button>
        );
      })}
    </div>
  );
}
