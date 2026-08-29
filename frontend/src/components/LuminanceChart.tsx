import { useMemo } from "react";
import { motion } from "framer-motion";
import * as d3 from "d3";
import type { Histogram } from "@/types/analysis";

const VIEW_W = 400;
const VIEW_H = 180;

export function LuminanceChart({ histogram }: { histogram: Histogram }) {
  const { path, meanX } = useMemo(() => {
    const n = histogram.bins;
    // Rec. 601 weights applied to the marginal R/G/B histograms — an
    // approximation of a true per-pixel luminance histogram, which would
    // require the raw pixel array rather than these three independent
    // 256-bin distributions.
    const luminance = Array.from(
      { length: n },
      (_, i) => 0.299 * histogram.r[i] + 0.587 * histogram.g[i] + 0.114 * histogram.b[i],
    );

    const x = d3.scaleLinear().domain([0, n - 1]).range([0, VIEW_W]);
    const maxVal = Math.max(1, d3.max(luminance) ?? 0);
    const y = d3.scaleLinear().domain([0, maxVal]).range([VIEW_H, 0]);
    const area = d3
      .area<number>()
      .x((_d, i) => x(i))
      .y0(VIEW_H)
      .y1((d) => y(d))
      .curve(d3.curveBasis);

    const totalWeight = d3.sum(luminance);
    const weightedIndex =
      totalWeight > 0
        ? d3.sum(luminance.map((v, i) => v * i)) / totalWeight
        : (n - 1) / 2;

    return { path: area(luminance) ?? "", meanX: x(weightedIndex) };
  }, [histogram]);

  return (
    <div className="border-t border-border pt-4">
      <span className="font-mono text-[10px] uppercase tracking-widest text-muted">
        Luminance
      </span>
      <div className="mt-2 border-b border-border">
        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          preserveAspectRatio="none"
          className="block h-[180px] w-full"
          aria-label="Luminance distribution"
        >
          <defs>
            {/* Very subtle tonal fill — a faint dark wash on the left tapering
                to near-white on the right, just enough to read as shape. */}
            <linearGradient id="lum-fill" x1="0" x2="1">
              <stop offset="0%" stopColor="#000000" stopOpacity="0.08" />
              <stop offset="100%" stopColor="#000000" stopOpacity="0.02" />
            </linearGradient>
          </defs>
          <motion.path
            d={path}
            fill="url(#lum-fill)"
            stroke="#0a0a0a"
            strokeWidth={1.5}
            initial={{ pathLength: 0, fillOpacity: 0 }}
            animate={{ pathLength: 1, fillOpacity: 1 }}
            transition={{ duration: 0.8, ease: "easeOut" }}
          />
          <line
            x1={meanX}
            x2={meanX}
            y1={0}
            y2={VIEW_H}
            stroke="#0a0a0a"
            strokeWidth={1}
            strokeDasharray="3 3"
          />
          <text x={meanX + 4} y={10} className="fill-muted font-mono text-[8px] uppercase">
            Mean
          </text>
        </svg>
      </div>
      {/* Zone System terminology — shadows / midtones / highlights across the
          tonal axis, echoing how photographers read exposure. */}
      <div className="mt-1.5 flex justify-between font-mono text-[8px] uppercase tracking-widest text-subtle">
        <span>Shadows</span>
        <span>Midtones</span>
        <span>Highlights</span>
      </div>
    </div>
  );
}
