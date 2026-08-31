import { motion } from "framer-motion";
import { HR_SPRING } from "@/lib/motionVariants";
import type { ColorSwatch } from "@/types/analysis";

export function DominantColors({ colors }: { colors: ColorSwatch[] }) {
  if (colors.length === 0) {
    return <p className="text-sm text-muted">No colors detected.</p>;
  }

  return (
    <div className="border-t-4 border-black pt-4">
      <span className="font-sans text-xs font-black uppercase tracking-widest text-muted">
        Dominant colors
      </span>
      <div className="mt-2 flex h-[52px] w-full overflow-hidden border-4 border-black shadow-[4px_4px_0_0_#000]">
        {colors.map((color, i) => (
          <motion.div
            key={`${color.hex}-${i}`}
            title={`${color.hex} · ${Math.round(color.proportion * 100)}%`}
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ ...HR_SPRING, delay: i * 0.05 }}
            style={{
              width: `${color.proportion * 100}%`,
              backgroundColor: color.hex,
              transformOrigin: "left",
            }}
          />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        {colors.map((color, i) => (
          <div key={`${color.hex}-legend-${i}`} className="inline-flex items-center gap-1.5">
            <span
              className="h-4 w-4 shrink-0 border-2 border-black"
              style={{ backgroundColor: color.hex }}
            />
            {/* A tight, bordered tag — reads as a physical Pantone swatch
                label rather than loose floating text. */}
            <span className="border-2 border-black px-1 font-mono text-[10px] uppercase text-black">
              {color.hex} · {Math.round(color.proportion * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
